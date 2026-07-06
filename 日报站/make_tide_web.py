#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货资金潮汐日报 → 交互网页生成器

解析每日静态版 期货资金潮汐_YYYYMMDD.html（qihuo_monitor 输出）里的全部真实数据：
头部净值/KPI、四类动作榜、资金强度榜、板块聚合、背离雷达、持续性榜、共振榜，
以及全部内嵌图（潮汐主图/象限图/品种迷你图），合并成品种级主数据集，
生成一个自包含交互网页：品种搜索、板块/动作/方向筛选、多键排序、点行展开明细。

用法：
    python3 make_tide_web.py                                        # 自动找最新的静态版 html
    python3 make_tide_web.py 日报/20260701/期货资金潮汐_20260701.html

输出：同目录 期货资金潮汐_YYYYMMDD_交互.html（日报台自动优先显示交互版）
"""

import json
import re
import sys
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
ROOT = SITE_DIR.parent
REPORT_DIR = ROOT / "日报"

BOARDS = ["有色", "黑色", "化工", "能源", "农产品", "贵金属"]


def strip_tags(x, img_mark=False):
    x = re.sub(r"<img[^>]*>", "[IMG]" if img_mark else "", x)
    x = re.sub(r"<[^>]+>", "|", x)
    x = re.sub(r"\s*\|+\s*", "|", x)
    return x.strip("|")


def to_num(s):
    """'27.25亿'→27.25, '45%'→45, '6,567'→6567, '-240%'→-240, '翻转'→None"""
    s = s.replace(",", "").replace("＋", "+").replace("−", "-")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def to_yi(s):
    """金额统一换算成亿：'27.25亿'→27.25，'5,763万'→0.5763"""
    v = to_num(s)
    if v is None:
        return None
    return round(v / 1e4, 4) if "万" in s else v


# 报告自身的板块分类（强度榜/共振榜里未覆盖到的品种用这份补齐，口径一致）
SECTOR_FALLBACK = {
    "黄金": "贵金属", "白银": "贵金属",
    "原油": "能源", "燃油": "能源", "液化气": "能源",
    "橡胶": "化工", "20号胶": "化工", "纸浆": "化工", "PTA": "化工",
    "豆二": "农产品", "豆一": "农产品", "苹果": "农产品", "红枣": "农产品",
    "花生": "农产品", "生猪": "农产品", "玉米": "农产品", "鸡蛋": "农产品",
    "菜油": "农产品", "热卷": "黑色", "焦煤": "黑色", "焦炭": "黑色",
}


def cells_of(tr_html):
    tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr_html, re.S)
    return [strip_tags(td) for td in tds]


def imgs_of(html):
    return re.findall(r"<img[^>]*?src=['\"](data:image/png;base64,[^'\"]+)['\"]", html)


def parse(src: Path):
    h = src.read_text(encoding="utf-8")
    flow = re.sub(r"<style.*?</style>", "", h, flags=re.S)
    flow = re.sub(r"<img[^>]*>", "", flow)
    flow = re.sub(r"<[^>]+>", "|", flow)
    flow = re.sub(r"\s*\|+\s*", "|", flow)
    flow = re.sub(r"\|+", "|", flow)

    meta = {}
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*·\s*盘后", flow)
    meta["date"] = m.group(1) if m else ""
    m = re.search(r"名义净持仓\(亿\)\|(-?[\d.]+)\|\s*亿[^|]*\|(-?[\d.]+亿)", flow)
    if m:
        meta["net"], meta["chg"] = float(m.group(1)), m.group(2)
    m = re.search(r"40日区间\|([^|]+)", flow)
    meta["range40"] = m.group(1).strip() if m else ""
    meta["kpi"] = {}
    for k in ["加多品种", "减多品种", "加空品种", "减空品种"]:
        m = re.search(k + r"\|(\d+)\|([^|]*)", flow)
        if m:
            meta["kpi"][k] = [int(m.group(1)), m.group(2)]
    m = re.search(r"情绪偏向\|(-?\d+%)", flow)
    meta["kpi"]["情绪偏向"] = m.group(1) if m else ""
    m = re.search(r"在场品种\|(\d+)", flow)
    meta["kpi"]["在场品种"] = m.group(1) if m else ""
    for k in ["加多名义总额", "加空名义总额", "加多−加空 净额", "总变动手数"]:
        m = re.search(re.escape(k) + r"\|([^|]+)", flow)
        if m:
            meta["kpi"][k] = m.group(1).strip()
    m = re.search(r"加仓 / 减仓\|(\d+)\s*\|/\s*(\d+)", flow)
    if m:
        meta["kpi"]["加仓/减仓"] = f"{m.group(1)} / {m.group(2)}"
    m = re.search(r"\|(数据源:[^|]+)\|", flow)
    meta["source"] = m.group(1).strip() if m else ""

    # ── 全部内嵌图：第0张=潮汐主图；class=chart 的两张=双榜图/象限图 ──
    all_imgs = imgs_of(h)
    chart_imgs = imgs_of("".join(re.findall(r"<img class=\"chart\"[^>]*>", h)))
    meta_tide_img = all_imgs[0] if all_imgs else ""
    quad_img = chart_imgs[1] if len(chart_imgs) > 1 else ""

    # ── 8 张表：4 动作榜 + 强度榜 + 背离×2 + 持续榜（按形状分类）──
    tables = re.findall(r"<table.*?</table>", h, re.S)
    action_tables, strength_rows, diverg_rows, streak_rows = [], [], [], []
    for t in tables:
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)
        body = [tr for tr in trs if "<td" in tr]
        if not body:
            continue
        c0 = cells_of(body[0])
        if len(c0) >= 7 and c0[0].isdigit():
            strength_rows += [(cells_of(tr), imgs_of(tr)) for tr in body]
        elif len(c0) == 4 and ("吸筹" in c0[1] or "沽空" in c0[1]):
            diverg_rows += [cells_of(tr) for tr in body]
        elif len(c0) == 4 and "连" in c0[1]:
            streak_rows += [(cells_of(tr), imgs_of(tr)) for tr in body]
        elif len(c0) == 4:
            action_tables.append([cells_of(tr) for tr in body])

    master = {}

    def row(name):
        return master.setdefault(name, {"name": name})

    act_names = ["加多", "减多", "加空", "减空"]
    for act, rows in zip(act_names, action_tables):
        for c in rows:
            r = row(c[0])
            r.update(act=act, amt=to_yi(c[1]), amt_txt=c[1], rel=to_num(c[2]), hands=to_num(c[3]))

    for c, im in strength_rows:
        r = row(c[1])
        r.update(sector=c[2], act=c[3], amt=to_yi(c[4]), amt_txt=c[4], rel=to_num(c[5]),
                 mom=None if "翻转" in c[6] else to_num(c[6]),
                 mom_txt=c[6], rank=int(c[0]), spark=(im[0] if im else None))

    for c in diverg_rows:
        r = row(c[0])
        r.update(diverg=c[1], div_hands=to_num(c[2]), div_px=c[3])

    for c, im in streak_rows:
        r = row(c[0])
        r.update(streak=c[1], netpos=c[3],
                 streak_n=(1 if "加" in c[1] else -1) * (to_num(c[1]) or 0))
        if im and not r.get("spark"):
            r["spark"] = im[0]

    # ── 共振榜（div 结构，走文本流）：板块|N|品种|利多/空|可信度·档|动作 手 ·|价% ──
    mzone = re.search(r"资金动能共振榜.*?(?=\|数据源)", flow, re.S)
    if mzone:
        z = mzone.group(0)
        cur_sector = None
        pat = re.compile(
            r"\|(有色|黑色|化工|能源|农产品|贵金属)\|(\d+)(?=\|)"
            r"|\|([^|]{1,8})\|(利多|利空)\|(\d+)·(很高|高|中|低|很低)\|(加多|减多|加空|减空)\s*([\d,]+)\s*·\|([+-]?[\d.]+%)")
        for m in pat.finditer(z):
            if m.group(1):
                cur_sector = m.group(1)
                continue
            name = m.group(3).strip()
            r = row(name)
            r.update(dir=m.group(4), conf=int(m.group(5)), conf_label=m.group(6), px=m.group(9))
            r.setdefault("act", m.group(7))
            r.setdefault("hands", to_num(m.group(8)))
            r.setdefault("sector", cur_sector)

    # ── 板块聚合条 ──
    sectors = []
    sec_zone = re.search(r"板块资金迷你走势(.*?)价格 × 持仓象限", h, re.S)
    sec_imgs = imgs_of(sec_zone.group(1)) if sec_zone else []
    for i, b in enumerate(BOARDS):
        m = re.search(re.escape(b) + r"\|净\|([+-]?[\d.]+亿)\|\s*·\s*日\|([+-]?[\d.]+)", flow)
        if m:
            sectors.append({"name": b, "net": m.group(1), "day": m.group(2),
                            "img": sec_imgs[i] if i < len(sec_imgs) else None})

    for r in master.values():
        if not r.get("sector") and r["name"] in SECTOR_FALLBACK:
            r["sector"] = SECTOR_FALLBACK[r["name"]]

    rows = sorted(master.values(), key=lambda r: -(r.get("amt") or 0))
    return meta, rows, sectors, meta_tide_img, quad_img


TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>期货资金潮汐 · 交互终端 __DATE__</title>
<style>
  :root{--bg:#f6f2e7;--panel:#fdfbf5;--card:#fff;--ink:#23312b;--mut:#8a8676;--line:#e5dfcb;
        --long:#b23a2f;--short:#17604b;--gold:#b98b2f;--dark:#0f4638}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
       background:var(--bg);color:var(--ink);padding-bottom:60px}
  .wrap{max-width:1080px;margin:0 auto;padding:0 20px}
  .mast{display:flex;align-items:baseline;gap:14px;padding:22px 0 12px;border-bottom:2px solid var(--ink)}
  .brand{font-family:Georgia,serif;letter-spacing:3px;font-size:13px;color:var(--mut)}
  h1{font-family:Georgia,"Noto Serif CJK SC",serif;font-size:26px;color:var(--dark)}
  .asof{margin-left:auto;font-size:12px;color:var(--mut)}
  .hero{display:flex;gap:18px;align-items:stretch;padding:16px 0 6px;flex-wrap:wrap}
  .netcard{background:var(--dark);color:#efe9d5;border-radius:14px;padding:16px 22px;min-width:230px}
  .netcard .lb{font-size:11px;opacity:.75;letter-spacing:1px}
  .netcard b{font-size:40px;font-family:Georgia,serif;display:block;line-height:1.15}
  .netcard .sub{font-size:12px;opacity:.85;margin-top:4px}
  .kpis{flex:1;display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:8px;min-width:320px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;text-align:center}
  .kpi b{display:block;font-size:16px;font-family:Georgia,serif}
  .kpi span{font-size:10.5px;color:var(--mut)}
  .tidechart{width:100%;border:1px solid var(--line);border-radius:12px;background:#fff;margin:8px 0 4px;cursor:zoom-in}
  .secbar{display:flex;gap:8px;flex-wrap:wrap;padding:10px 0}
  .sec{display:flex;flex-direction:column;gap:2px;border:1px solid var(--line);background:var(--card);
       border-radius:11px;padding:7px 13px;cursor:pointer;min-width:96px}
  .sec[data-on="1"]{border-color:var(--dark);background:var(--dark)}
  .sec[data-on="1"] *{color:#efe9d5!important}
  .sec .nm{font-size:12.5px;font-weight:700}
  .sec .v{font-size:13px;font-family:Georgia,serif}
  .sec .d{font-size:10.5px;color:var(--mut)}
  .controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:8px 0 14px;border-top:1px solid var(--line)}
  .pill{border:1px solid var(--line);background:var(--card);border-radius:18px;padding:6px 13px;font-size:12.5px;cursor:pointer}
  .pill[data-on="1"]{background:var(--dark);border-color:var(--dark);color:#fff}
  .controls input{border:1px solid var(--line);border-radius:18px;padding:7px 14px;font-size:13px;background:var(--card);outline:none;width:150px}
  .controls select{border:1px solid var(--line);border-radius:18px;padding:6px 10px;font-size:12.5px;background:var(--card)}
  .lab{font-size:11.5px;color:var(--mut);margin-left:4px}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  thead th{font-size:11px;color:var(--mut);font-weight:600;text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);background:var(--panel)}
  tbody td{padding:8px 10px;font-size:13px;border-bottom:1px solid #f0ebdb;vertical-align:middle}
  tbody tr{cursor:pointer}
  tbody tr:hover td{background:#faf6ea}
  .nm2{font-weight:700;font-size:14px}
  .tag{font-size:11px;border-radius:8px;padding:1px 8px;color:#fff;white-space:nowrap}
  .tag.jd{background:var(--long)} .tag.jk{background:var(--short)}
  .tag.jd.less,.tag.jk.less{opacity:.55}
  .amt{font-family:Georgia,serif;font-size:14px}
  .rel-hot{color:var(--gold);font-weight:700}
  .confcell{display:flex;align-items:center;gap:6px;min-width:110px}
  .confbar{flex:1;height:5px;background:#efe9d8;border-radius:3px;max-width:60px}
  .confbar i{display:block;height:100%;border-radius:3px}
  .spk{height:26px;display:block}
  .muted{color:var(--mut)}
  .detail td{background:#fbf8ef!important;font-size:12.5px;color:var(--ink)}
  .detail .dgrid{display:flex;gap:26px;flex-wrap:wrap;align-items:center;padding:4px 2px}
  .detail img{height:64px;background:#fff;border:1px solid var(--line);border-radius:8px}
  .divtag{font-size:11px;border:1px dashed var(--gold);color:var(--gold);border-radius:8px;padding:1px 7px}
  .quadbox{margin-top:22px}
  .quadbox summary{cursor:pointer;font-weight:600;font-size:14px;padding:6px 0;color:var(--dark)}
  .quadbox img{width:100%;max-width:760px;border:1px solid var(--line);border-radius:12px;background:#fff}
  .foot{margin-top:24px;border-top:1px solid var(--line);padding-top:10px;font-size:11.5px;color:var(--mut)}
  .empty{padding:36px;text-align:center;color:var(--mut)}
  #lightbox{position:fixed;inset:0;background:rgba(20,26,23,.86);display:none;align-items:center;justify-content:center;cursor:zoom-out;z-index:50;padding:30px}
  #lightbox img{max-width:min(1100px,96vw);width:100%;background:#fff;border-radius:10px;padding:12px}
</style>
</head>
<body>
<div class="wrap">
  <div class="mast">
    <div class="brand">WINDRISE</div>
    <h1>期货资金潮汐 · 交互终端</h1>
    <div class="asof">__DATE__ · 盘后主力席位资金视图</div>
  </div>

  <div class="hero">
    <div class="netcard">
      <div class="lb">机构资金潮汐净值 · 名义净持仓(亿)</div>
      <b id="netv"></b>
      <div class="sub" id="netsub"></div>
    </div>
    <div class="kpis" id="kpis"></div>
  </div>
  <img class="tidechart" id="tidechart" alt="">

  <div class="secbar" id="secbar"></div>

  <div class="controls">
    <input id="q" type="text" placeholder="搜品种，如 碳酸锂">
    <button class="pill fact" data-v="">全部动作</button>
    <button class="pill fact" data-v="加多">加多</button>
    <button class="pill fact" data-v="减多">减多</button>
    <button class="pill fact" data-v="加空">加空</button>
    <button class="pill fact" data-v="减空">减空</button>
    <span class="lab">共振</span>
    <button class="pill fdir" data-v="">全部</button>
    <button class="pill fdir" data-v="利多">利多</button>
    <button class="pill fdir" data-v="利空">利空</button>
    <span class="lab">排序</span>
    <select id="sort">
      <option value="amt">名义金额</option>
      <option value="conf">共振可信度</option>
      <option value="rel">相对幅度</option>
      <option value="mom">环比动能</option>
      <option value="streak">持续天数</option>
    </select>
  </div>

  <table>
    <thead><tr>
      <th>品种</th><th>板块</th><th>动作</th><th>名义金额</th><th>相对</th><th>环比</th>
      <th>共振</th><th>持续</th><th></th><th>近60日</th>
    </tr></thead>
    <tbody id="tb"></tbody>
  </table>

  <details class="quadbox"><summary>价格 × 持仓象限 / 资金背离雷达（原图）</summary>
    <img id="quad" alt="">
  </details>
  <div class="foot" id="foot"></div>
</div>
<div id="lightbox"><img alt=""></div>
<script>
const D = __DATA__;
let fsec = "", fact = "", fdir = "", q = "", sortKey = "amt", opened = null;
const $ = s => document.querySelector(s);
const esc = s => (s ?? "").toString();

function header() {
  $("#netv").textContent = D.meta.net > 0 ? "+" + D.meta.net : D.meta.net;
  $("#netsub").textContent = `今日变动 ${D.meta.chg} · 40日区间 ${D.meta.range40}`;
  const K = D.meta.kpi, order = ["加多品种","减多品种","加空品种","减空品种"];
  let hh = order.map(k => K[k] ? `<div class="kpi"><b>${K[k][0]}</b><span>${k}<br>${K[k][1]}</span></div>` : "").join("");
  hh += `<div class="kpi"><b>${K["情绪偏向"]}</b><span>情绪偏向</span></div>`;
  hh += `<div class="kpi"><b>${K["在场品种"]}</b><span>在场品种</span></div>`;
  hh += `<div class="kpi"><b>${K["加多名义总额"]||"—"}</b><span>加多总额</span></div>`;
  hh += `<div class="kpi"><b>${K["加空名义总额"]||"—"}</b><span>加空总额</span></div>`;
  hh += `<div class="kpi"><b>${K["加多−加空 净额"]||"—"}</b><span>加多−加空</span></div>`;
  $("#kpis").innerHTML = hh;
  if (D.tide_img) { $("#tidechart").src = D.tide_img; $("#tidechart").onclick = () => lightbox(D.tide_img); }
  else $("#tidechart").style.display = "none";
  if (D.quad_img) $("#quad").src = D.quad_img;
  $("#foot").textContent = D.meta.source;
}

function secbar() {
  $("#secbar").innerHTML = D.sectors.map(s =>
    `<div class="sec" data-v="${s.name}"><span class="nm">${s.name}</span>
      <span class="v" style="color:${s.net.startsWith("-") ? "var(--short)" : "var(--long)"}">${s.net}</span>
      <span class="d">日 ${s.day}</span></div>`).join("");
  document.querySelectorAll(".sec").forEach(el => el.onclick = () => {
    fsec = fsec === el.dataset.v ? "" : el.dataset.v;
    document.querySelectorAll(".sec").forEach(x => x.setAttribute("data-on", x.dataset.v === fsec ? "1" : ""));
    render();
  });
}

function view() {
  let arr = D.rows.filter(r =>
    (!fsec || r.sector === fsec) &&
    (!fact || r.act === fact) &&
    (!fdir || r.dir === fdir) &&
    (!q || r.name.toLowerCase().includes(q.toLowerCase())));
  const keyf = {
    amt: r => -(r.amt ?? -1),
    conf: r => -(r.conf ?? -1),
    rel: r => -(r.rel ?? -1),
    mom: r => -(Math.abs(r.mom ?? -1)),
    streak: r => -Math.abs(r.streak_n ?? 0),
  }[sortKey];
  return arr.sort((a, b) => keyf(a) - keyf(b));
}

const fmtAmt = r => r.amt_txt ?? (r.amt == null ? "—" : r.amt + "亿");
const actTag = a => !a ? "" :
  `<span class="tag ${a.includes("多") ? "jd" : "jk"}${a.startsWith("减") ? " less" : ""}">${a}</span>`;

function render() {
  const arr = view();
  $("#tb").innerHTML = arr.length ? arr.map(r => {
    const hot = (r.rel ?? 0) >= 50;
    const confHtml = r.conf == null ? '<span class="muted">—</span>' :
      `<div class="confcell"><span style="color:${r.dir === "利多" ? "var(--long)" : "var(--short)"};font-weight:700;font-size:12px">${r.dir} ${r.conf}</span>
       <div class="confbar"><i style="width:${r.conf}%;background:${r.dir === "利多" ? "var(--long)" : "var(--short)"}"></i></div></div>`;
    return `<tr data-n="${r.name}">
      <td class="nm2">${r.name}</td>
      <td class="muted">${esc(r.sector) || "—"}</td>
      <td>${actTag(r.act)}</td>
      <td class="amt">${fmtAmt(r)}</td>
      <td class="${hot ? "rel-hot" : "muted"}">${r.rel == null ? "—" : r.rel + "%"}</td>
      <td class="muted">${esc(r.mom_txt) || "—"}</td>
      <td>${confHtml}</td>
      <td class="muted">${esc(r.streak) || "—"}</td>
      <td>${r.diverg ? `<span class="divtag">${r.diverg}</span>` : ""}</td>
      <td>${r.spark ? `<img class="spk" src="${r.spark}">` : ""}</td>
    </tr>` + (opened === r.name ? detailRow(r) : "");
  }).join("") : '<tr><td colspan="10" class="empty">没有匹配的品种</td></tr>';
  document.querySelectorAll("#tb tr[data-n]").forEach(tr => tr.onclick = () => {
    opened = opened === tr.dataset.n ? null : tr.dataset.n;
    render();
  });
}

function detailRow(r) {
  const items = [
    ["动作手数", r.hands != null ? r.hands.toLocaleString() + " 手" : null],
    ["当日价格", r.px],
    ["当前净持仓", r.netpos],
    ["背离", r.diverg ? `${r.diverg} ${r.div_hands?.toLocaleString() ?? ""}手 / 价${r.div_px}` : null],
    ["共振档位", r.conf != null ? `${r.conf} · ${r.conf_label}` : null],
    ["强度排名", r.rank ? "#" + r.rank : null],
  ].filter(x => x[1]);
  return `<tr class="detail"><td colspan="10"><div class="dgrid">
    ${items.map(x => `<span><span class="muted">${x[0]}</span>　<b>${x[1]}</b></span>`).join("")}
    ${r.spark ? `<img src="${r.spark}" title="近60日机构净持仓">` : ""}
  </div></td></tr>`;
}

function lightbox(src) { $("#lightbox img").src = src; $("#lightbox").style.display = "flex"; }
$("#lightbox").onclick = () => $("#lightbox").style.display = "none";

document.querySelectorAll(".fact").forEach(b => b.onclick = () => {
  fact = b.dataset.v;
  document.querySelectorAll(".fact").forEach(x => x.setAttribute("data-on", x === b ? "1" : "")); render();
});
document.querySelectorAll(".fdir").forEach(b => b.onclick = () => {
  fdir = b.dataset.v;
  document.querySelectorAll(".fdir").forEach(x => x.setAttribute("data-on", x === b ? "1" : "")); render();
});
$("#q").addEventListener("input", e => { q = e.target.value.trim(); render(); });
$("#sort").addEventListener("change", e => { sortKey = e.target.value; render(); });
document.querySelector('.fact[data-v=""]').setAttribute("data-on", "1");
document.querySelector('.fdir[data-v=""]').setAttribute("data-on", "1");

header(); secbar(); render();
</script>
</body>
</html>
"""


def find_latest_html():
    cands = [p for p in sorted(REPORT_DIR.glob("2*/期货资金潮汐_*.html"))
             if "交互" not in p.name and "长图" not in p.name]
    if not cands:
        raise SystemExit("日报/ 下没找到静态版 期货资金潮汐_*.html")
    return cands[-1]


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else find_latest_html()
    if not src.is_absolute():
        src = ROOT / src
    date = re.search(r"(\d{8})", src.name).group(1)

    meta, rows, sectors, tide_img, quad_img = parse(src)
    data = {"meta": meta, "rows": rows, "sectors": sectors,
            "tide_img": tide_img, "quad_img": quad_img}
    html = (TEMPLATE
            .replace("__DATA__", json.dumps(data, ensure_ascii=False))
            .replace("__DATE__", meta.get("date") or f"{date[:4]}-{date[4:6]}-{date[6:]}"))
    out = src.parent / f"期货资金潮汐_{date}_交互.html"
    out.write_text(html, encoding="utf-8")

    n_conf = sum(1 for r in rows if r.get("conf") is not None)
    n_spark = sum(1 for r in rows if r.get("spark"))
    print(f"完成：{len(rows)} 个品种（含共振评分 {n_conf}、迷你图 {n_spark}）· 板块 {len(sectors)}")
    print(f"输出：{out}（{out.stat().st_size//1024}KB）")


if __name__ == "__main__":
    main()
