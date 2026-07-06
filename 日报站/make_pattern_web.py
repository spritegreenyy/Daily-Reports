#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货形态日报 → 交互网页生成器

从 期货形态_YYYYMMDD.pdf 里解析全部真实数据（pdftotext）并抽出每个形态的
K线图（pdfimages，PDF 内嵌的原图，无损），生成一个自包含交互网页：
筛选（方向/状态）、排序（可信度/盈亏比/距触发）、搜索、点图放大。

用法：
    python3 make_pattern_web.py                          # 自动找 日报/ 里最新的期货形态 PDF
    python3 make_pattern_web.py 日报/20260703/期货形态_20260703.pdf

输出：与 PDF 同目录同名的 .html（日报台会自动优先显示网页版，PDF 退为切换按钮）
"""

import base64
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
ROOT = SITE_DIR.parent
REPORT_DIR = ROOT / "日报"

CARD_RE = re.compile(
    r"^\s*(?P<name>\S+?)\s+(?:等权指数·base100\s+)?"
    r"(?P<pattern>上升三角|下降三角|上升楔形|下降楔形|三角|矩形|楔形|旗形)\s*·\s*(?P<bias>偏多|偏空)"
    r"\s+可信度\s*(?P<conf>[\d.]+)\s*·\s*(?P<conf_label>很高|高|中|低)"
)
STATUS_RE = re.compile(r"^\s*(?P<status>\S+·[^\s]+)\s+近端\s*·\s*形态完成\s+(?P<completed>[\d\- :]+)")
NUM_RE = re.compile(r"^\s*(?P<key>现价|颈线/触发|目标|止损)\s+(?P<val>[\d,]+(?:\.\d+)?)\s*$")
STATS_RE = re.compile(r"(\d+)\s*可操作\s+(\d+)\s*识别到形态\s+(\d+)\s*偏多\s+(\d+)\s*偏空")
ASOF_RE = re.compile(r"截至\s*([\d\- :]+)")


def sh(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def parse_pdf(pdf: Path):
    txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                         check=True, capture_output=True, text=True).stdout
    lines = txt.splitlines()

    meta = {"asof": "", "stats": None, "none_list": [], "notes": []}
    m = ASOF_RE.search(txt)
    if m:
        meta["asof"] = m.group(1).strip()
    m = STATS_RE.search(txt.replace("\n", " "))
    if m:
        meta["stats"] = [int(x) for x in m.groups()]
    for ln in lines:
        if "无明确形态" in ln:
            meta["none_list"] = [x.strip() for x in ln.split("：", 1)[1].split("、") if x.strip()]
    # 尾注：方法 / 指数编制 / 数据源（原文照录）
    tail = txt.split("方法：", 1)
    if len(tail) == 2:
        meta["notes"] = ["方法：" + " ".join(tail[1].split())]

    cards, cur = [], None
    for ln in lines:
        m = CARD_RE.match(ln)
        if m:
            cur = m.groupdict()
            cur["conf"] = float(cur["conf"])
            cur["vals"] = {}
            cards.append(cur)
            continue
        if cur is not None:
            m = STATUS_RE.match(ln)
            if m:
                cur["status"] = m.group("status")
                cur["completed"] = m.group("completed").strip()
                continue
            m = NUM_RE.match(ln)
            if m:
                cur["vals"][m.group("key")] = float(m.group("val").replace(",", ""))

    for c in cards:
        v = c["vals"]
        price, neck = v.get("现价"), v.get("颈线/触发")
        target, stop = v.get("目标"), v.get("止损")
        c["trig_pct"] = round((neck - price) / price * 100, 2) if price and neck else None
        c["target_pct"] = round((target - neck) / neck * 100, 2) if neck and target else None
        if neck and target and stop and neck != stop:
            c["rr"] = round(abs(target - neck) / abs(neck - stop), 2)
        else:
            c["rr"] = None
    return meta, cards


def extract_charts(pdf: Path, n: int):
    """PDF 内嵌图按出现顺序 = 卡片顺序；偶数编号为图、奇数为透明遮罩。"""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdfimages", "-png", str(pdf), str(Path(tmp) / "c")], check=True)
        pngs = sorted(Path(tmp).glob("c-*.png"))
        charts = [p for i, p in enumerate(pngs) if i % 2 == 0][:n]
        return [base64.b64encode(p.read_bytes()).decode("ascii") for p in charts]


TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>期货形态 · 交互终端 __DATE__</title>
<style>
  :root{--bg:#f6f2e7;--panel:#fdfbf5;--card:#fff;--ink:#23312b;--mut:#8a8676;--line:#e5dfcb;
        --long:#b23a2f;--short:#17604b;--gold:#b98b2f;--dark:#0f4638}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
       background:var(--bg);color:var(--ink);padding-bottom:60px}
  .wrap{max-width:1060px;margin:0 auto;padding:0 20px}
  .mast{display:flex;align-items:baseline;gap:14px;padding:22px 0 12px;border-bottom:2px solid var(--ink)}
  .brand{font-family:Georgia,serif;letter-spacing:3px;font-size:13px;color:var(--mut)}
  h1{font-family:Georgia,"Noto Serif CJK SC",serif;font-size:26px;color:var(--dark)}
  .asof{margin-left:auto;font-size:12px;color:var(--mut)}
  .statbar{display:flex;gap:10px;flex-wrap:wrap;padding:14px 0}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 16px;text-align:center}
  .stat b{display:block;font-size:22px;font-family:Georgia,serif}
  .stat span{font-size:11px;color:var(--mut)}
  .stat.long b{color:var(--long)} .stat.short b{color:var(--short)}
  .nonebar{font-size:12.5px;color:var(--mut);padding:2px 0 12px}
  .nonebar em{font-style:normal;background:#eee8d5;border-radius:10px;padding:2px 9px;margin:0 3px;display:inline-block;margin-bottom:4px}
  .controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:10px 0 18px;border-top:1px solid var(--line)}
  .pill{border:1px solid var(--line);background:var(--card);border-radius:18px;padding:6px 14px;
        font-size:13px;cursor:pointer;color:var(--ink)}
  .pill[data-on="1"]{background:var(--dark);border-color:var(--dark);color:#fff}
  .controls input{border:1px solid var(--line);border-radius:18px;padding:7px 14px;font-size:13px;
                  background:var(--card);outline:none;width:170px}
  .controls select{border:1px solid var(--line);border-radius:18px;padding:6px 10px;font-size:13px;background:var(--card)}
  .controls .lab{font-size:12px;color:var(--mut);margin-left:6px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  @media(max-width:860px){.grid{grid-template-columns:1fr}}
  .cardx{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;
         box-shadow:0 1px 4px rgba(35,49,43,.06)}
  .chead{display:flex;align-items:center;gap:10px;padding:13px 16px 9px}
  .cname{font-size:19px;font-weight:700}
  .idxchip{font-size:10.5px;color:var(--mut);border:1px solid var(--line);border-radius:9px;padding:1px 7px}
  .badge{font-size:12px;border-radius:9px;padding:2px 10px;color:#fff}
  .badge.long{background:var(--long)} .badge.short{background:var(--short)}
  .status{font-size:11.5px;color:var(--gold);margin-left:auto;white-space:nowrap}
  .confrow{display:flex;align-items:center;gap:8px;padding:0 16px 9px}
  .confbar{flex:1;height:6px;background:#efe9d8;border-radius:3px;overflow:hidden}
  .confbar i{display:block;height:100%;border-radius:3px}
  .conftxt{font-size:12px;color:var(--mut);white-space:nowrap}
  .chart{display:block;width:100%;cursor:zoom-in;background:#fff;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
  .nums{display:grid;grid-template-columns:repeat(4,1fr);text-align:center;padding:10px 8px 6px}
  .nums b{display:block;font-size:15px;font-family:Georgia,serif}
  .nums span{font-size:10.5px;color:var(--mut)}
  .derived{display:flex;justify-content:space-around;padding:7px 10px 12px;font-size:12px;color:var(--mut)}
  .derived b{color:var(--ink)}
  .derived .rr b{color:var(--gold)}
  .foot{margin-top:26px;border-top:1px solid var(--line);padding-top:12px;font-size:12px;color:var(--mut);line-height:1.7}
  .foot summary{cursor:pointer;font-size:13px;color:var(--ink);font-weight:600;padding:4px 0}
  .empty{padding:40px;text-align:center;color:var(--mut)}
  #lightbox{position:fixed;inset:0;background:rgba(20,26,23,.86);display:none;align-items:center;
            justify-content:center;cursor:zoom-out;z-index:50;padding:30px}
  #lightbox img{max-width:min(1100px,96vw);width:100%;background:#fff;border-radius:10px;padding:14px}
  #lightbox .cap{position:absolute;bottom:26px;left:0;right:0;text-align:center;color:#e8e2cf;font-size:14px}
</style>
</head>
<body>
<div class="wrap">
  <div class="mast">
    <div class="brand">WINDRISE</div>
    <h1>期货形态 · 交互终端</h1>
    <div class="asof">小时K · 枢轴几何识别 · 截至 __ASOF__</div>
  </div>
  <div class="statbar" id="statbar"></div>
  <div class="nonebar" id="nonebar"></div>
  <div class="controls">
    <input id="q" type="text" placeholder="搜品种 / 形态，如 锡、矩形">
    <button class="pill fbias" data-v="">全部</button>
    <button class="pill fbias" data-v="偏多">偏多</button>
    <button class="pill fbias" data-v="偏空">偏空</button>
    <span class="lab">排序</span>
    <select id="sort">
      <option value="conf">可信度</option>
      <option value="rr">盈亏比</option>
      <option value="trig">距触发(近→远)</option>
      <option value="target">目标空间</option>
    </select>
  </div>
  <div class="grid" id="grid"></div>
  <details class="foot"><summary>方法论 / 指数编制 / 数据源（原文）</summary><div id="notes"></div></details>
</div>
<div id="lightbox"><img alt=""><div class="cap"></div></div>
<script>
const D = __DATA__;
let fbias = "", q = "", sortKey = "conf";
const $ = s => document.querySelector(s);

const fmt = n => n == null ? "—" : n.toLocaleString("en-US");
const pct = n => n == null ? "—" : (n > 0 ? "+" : "") + n.toFixed(2) + "%";

function statBar() {
  const [op, found, nlong, nshort] = D.meta.stats || [0,0,0,0];
  $("#statbar").innerHTML =
    `<div class="stat"><b>${op}</b><span>可操作</span></div>` +
    `<div class="stat"><b>${found}</b><span>识别到形态</span></div>` +
    `<div class="stat long"><b>${nlong}</b><span>偏多</span></div>` +
    `<div class="stat short"><b>${nshort}</b><span>偏空</span></div>`;
  $("#nonebar").innerHTML = D.meta.none_list.length
    ? "无明确形态：" + D.meta.none_list.map(x => `<em>${x}</em>`).join("") : "";
  $("#notes").textContent = D.meta.notes.join("\n");
}

function view() {
  let arr = D.cards.filter(c =>
    (!fbias || c.bias === fbias) &&
    (!q || (c.name + c.pattern + c.status).toLowerCase().includes(q.toLowerCase())));
  const keyf = {
    conf: c => -c.conf,
    rr: c => -(c.rr ?? -1),
    trig: c => Math.abs(c.trig_pct ?? 999),
    target: c => -Math.abs(c.target_pct ?? 0),
  }[sortKey];
  return arr.sort((a, b) => keyf(a) - keyf(b));
}

function render() {
  const arr = view();
  $("#grid").innerHTML = arr.length ? arr.map((c, i) => {
    const cls = c.bias === "偏多" ? "long" : "short";
    const color = c.bias === "偏多" ? "var(--long)" : "var(--short)";
    return `<div class="cardx">
      <div class="chead">
        <span class="cname">${c.name}</span>
        ${c.is_index ? '<span class="idxchip">等权指数·base100</span>' : ""}
        <span class="badge ${cls}">${c.pattern} · ${c.bias}</span>
        <span class="status">${c.status}</span>
      </div>
      <div class="confrow">
        <div class="confbar"><i style="width:${c.conf*100}%;background:${color}"></i></div>
        <span class="conftxt">可信度 ${c.conf.toFixed(2)} · ${c.conf_label}</span>
      </div>
      <img class="chart" src="data:image/png;base64,${c.img}" data-cap="${c.name} · ${c.pattern} · ${c.bias}（形态完成 ${c.completed}）" alt="">
      <div class="nums">
        <div><b>${fmt(c.vals["现价"])}</b><span>现价</span></div>
        <div><b style="color:var(--gold)">${fmt(c.vals["颈线/触发"])}</b><span>颈线/触发</span></div>
        <div><b style="color:${color}">${fmt(c.vals["目标"])}</b><span>目标</span></div>
        <div><b>${fmt(c.vals["止损"])}</b><span>止损</span></div>
      </div>
      <div class="derived">
        <span>距触发 <b>${pct(c.trig_pct)}</b></span>
        <span>目标空间 <b>${pct(c.target_pct)}</b></span>
        <span class="rr">盈亏比 <b>${c.rr ?? "—"}</b></span>
      </div>
    </div>`;
  }).join("") : '<div class="empty">没有匹配的形态</div>';

  document.querySelectorAll(".chart").forEach(img => img.onclick = () => {
    $("#lightbox img").src = img.src;
    $("#lightbox .cap").textContent = img.dataset.cap;
    $("#lightbox").style.display = "flex";
  });
}

document.querySelectorAll(".fbias").forEach(b => b.onclick = () => {
  fbias = b.dataset.v;
  document.querySelectorAll(".fbias").forEach(x => x.setAttribute("data-on", x === b ? "1" : ""));
  render();
});
$("#q").addEventListener("input", e => { q = e.target.value.trim(); render(); });
$("#sort").addEventListener("change", e => { sortKey = e.target.value; render(); });
$("#lightbox").onclick = () => $("#lightbox").style.display = "none";
document.querySelector('.fbias[data-v=""]').setAttribute("data-on", "1");

statBar(); render();
</script>
</body>
</html>
"""


def find_latest_pdf():
    cands = sorted(REPORT_DIR.glob("2*/期货形态_*.pdf"))
    if not cands:
        raise SystemExit("日报/ 下没找到 期货形态_*.pdf")
    return cands[-1]


def main():
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else find_latest_pdf()
    if not pdf.is_absolute():
        pdf = ROOT / pdf
    date = re.search(r"(\d{8})", pdf.name).group(1)

    meta, cards = parse_pdf(pdf)
    charts = extract_charts(pdf, len(cards))
    if len(charts) != len(cards):
        raise SystemExit(f"图与卡数量不符：{len(charts)} 图 / {len(cards)} 卡，请检查 PDF")
    for c, img in zip(cards, charts):
        c["img"] = img
        c["is_index"] = "指数" in c["name"]

    html = (TEMPLATE
            .replace("__DATA__", json.dumps({"meta": meta, "cards": cards}, ensure_ascii=False))
            .replace("__ASOF__", meta["asof"])
            .replace("__DATE__", f"{date[:4]}-{date[4:6]}-{date[6:]}"))
    out = pdf.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    print(f"完成：{len(cards)} 个形态卡（{'、'.join(c['name'] for c in cards)}）")
    print(f"输出：{out}（{out.stat().st_size//1024}KB）")


if __name__ == "__main__":
    main()
