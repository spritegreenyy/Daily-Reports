#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日报站生成器
扫描 ../日报/ 下所有 8 位日期文件夹，识别每天的报告文件，
生成一个自包含的 index.html 面板（左侧日期列表 + 顶部报告标签页 + 内嵌查看器）。

用法：python3 build_site.py
每天把新日报放进 日报/YYYYMMDD/ 后重跑一次即可（或双击 更新日报站.command）。
"""

import json
import re
import datetime
from pathlib import Path
from urllib.parse import quote

SITE_DIR = Path(__file__).resolve().parent
ROOT = SITE_DIR.parent
REPORT_DIR = ROOT / "日报"
OUT_FILE = SITE_DIR / "index.html"

DATE_RE = re.compile(r"^\d{8}$")
VARIANT_TOKENS = {"自包含", "长图", "副本", "最新", "交互"}

# 已知报告类型的展示顺序与短名（不在列表里的类型自动排在后面，用原名）
KNOWN_TYPES = [
    ("期货形态", "期货形态"),
    ("A股形态", "A股形态"),
    ("期货资金潮汐", "资金潮汐"),
    ("大宗信号_四类资金净持仓流向", "大宗信号·四类资金"),
    ("KOL观点", "KOL观点"),
]
KNOWN_ORDER = {k: i for i, (k, _) in enumerate(KNOWN_TYPES)}
KNOWN_NAME = dict(KNOWN_TYPES)

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def parse_filename(fname: str):
    """返回 (type_key, variant, kind)；无法识别日期的文件返回 None。"""
    stem, dot, ext = fname.rpartition(".")
    if not dot:
        return None
    ext = ext.lower()
    if ext == "html":
        kind = "html"
    elif ext in ("png", "jpg", "jpeg", "webp"):
        kind = "img"
    elif ext == "pdf":
        kind = "pdf"
    else:
        return None

    tokens = stem.split("_")
    type_tokens, variants, has_date = [], [], False
    for t in tokens:
        if re.fullmatch(r"\d{8}", t):
            has_date = True
        elif t in VARIANT_TOKENS:
            variants.append(t)
        else:
            type_tokens.append(t)
    if not has_date or not type_tokens:
        return None
    return "_".join(type_tokens), "_".join(variants), kind


def file_priority(variant: str, kind: str) -> int:
    """决定同一类型下多个文件的默认展示优先级（大者优先）。"""
    if kind == "html":
        if "交互" in variant:
            return 110
        return 100 if "自包含" in variant else 90
    if kind == "img":
        return 80
    return 70  # pdf


def file_label(variant: str, kind: str) -> str:
    if kind == "html":
        return "交互版" if "交互" in variant else "网页版"
    if kind == "img":
        return "长图"
    return "PDF"


def scan():
    dates = []
    for d in sorted(REPORT_DIR.iterdir(), reverse=True):
        if not d.is_dir() or not DATE_RE.match(d.name):
            continue
        groups = {}
        for f in sorted(d.iterdir()):
            if f.name.startswith("."):
                continue
            if f.name.endswith("_data.json"):  # 交互图表的中间数值文件, 不作为报告展示
                continue
            parsed = parse_filename(f.name)
            if not parsed:
                continue
            type_key, variant, kind = parsed
            href = "../日报/" + quote(d.name) + "/" + quote(f.name)
            groups.setdefault(type_key, []).append({
                "label": file_label(variant, kind),
                "kind": kind,
                "href": href,
                "prio": file_priority(variant, kind),
            })
        if not groups:
            continue

        types = []
        for key in sorted(groups, key=lambda k: (KNOWN_ORDER.get(k, 99), k)):
            files = sorted(groups[key], key=lambda x: -x["prio"])
            for f in files:
                f.pop("prio")
            types.append({
                "key": key,
                "name": KNOWN_NAME.get(key, key),
                "files": files,
            })

        dt = datetime.date(int(d.name[:4]), int(d.name[4:6]), int(d.name[6:8]))
        dates.append({
            "date": d.name,
            "label": dt.strftime("%Y-%m-%d") + " " + WEEKDAY_CN[dt.weekday()],
            "types": types,
        })
    return dates


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WINDRISE · 日报台</title>
<style>
  :root {
    --bg: #f3efe4;
    --panel: #fbf9f2;
    --card: #ffffff;
    --ink: #23312b;
    --muted: #8a8676;
    --green: #17604b;
    --green-dark: #0f4638;
    --red: #b23a2f;
    --line: #e3ddc9;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background: var(--bg); color: var(--ink);
    display: flex; flex-direction: column;
  }
  header {
    display: flex; align-items: baseline; gap: 14px;
    padding: 14px 22px 12px; border-bottom: 1px solid var(--line);
    background: var(--panel);
  }
  header .brand { font-size: 18px; font-weight: 700; letter-spacing: 3px; color: var(--green-dark); }
  header .brand span { color: var(--red); }
  header .sub { font-size: 13px; color: var(--muted); }
  header .navlink {
    font-size: 13px; color: var(--green); text-decoration: none;
    border: 1px solid var(--line); border-radius: 20px; padding: 4px 12px; background: var(--card);
  }
  header .navlink:hover { border-color: var(--green); }
  header .gen { margin-left: auto; font-size: 12px; color: var(--muted); }
  .langsw {
    display: inline-flex; align-items: center; gap: 4px;
    border: 1px solid var(--line); border-radius: 999px; background: var(--card);
    padding: 3px; margin-left: 6px;
  }
  .langsw button {
    border: 0; background: transparent; color: var(--muted);
    font-size: 12px; font-weight: 700; padding: 5px 10px; border-radius: 999px; cursor: pointer;
  }
  .langsw button[data-on="1"] { background: var(--green-dark); color: #fff; }

  .layout { flex: 1; display: flex; min-height: 0; }

  aside {
    width: 215px; flex: none; border-right: 1px solid var(--line);
    background: var(--panel); display: flex; flex-direction: column;
  }
  .search { padding: 12px; border-bottom: 1px solid var(--line); }
  .search input {
    width: 100%; padding: 8px 10px; font-size: 13px;
    border: 1px solid var(--line); border-radius: 8px; background: var(--card);
    outline: none; color: var(--ink);
  }
  .search input:focus { border-color: var(--green); }
  .datelist { flex: 1; overflow-y: auto; padding: 8px; }
  .dateitem {
    display: flex; justify-content: space-between; align-items: center;
    padding: 9px 12px; margin-bottom: 4px; border-radius: 8px;
    font-size: 13.5px; cursor: pointer; border: 1px solid transparent;
  }
  .dateitem:hover { background: #f0ead7; }
  .dateitem.active { background: var(--green); color: #fff; }
  .dateitem .n {
    font-size: 11px; color: var(--muted); background: #eee8d5;
    border-radius: 10px; padding: 1px 8px;
  }
  .dateitem.active .n { background: rgba(255,255,255,.22); color: #fff; }

  main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .toolbar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 12px 18px; border-bottom: 1px solid var(--line); background: var(--panel);
  }
  .navbtn {
    border: 1px solid var(--line); background: var(--card); color: var(--ink);
    border-radius: 8px; padding: 6px 12px; font-size: 13px; cursor: pointer;
  }
  .navbtn:hover { border-color: var(--green); color: var(--green); }
  .navbtn:disabled { opacity: .35; cursor: default; }
  .curdate { font-size: 15px; font-weight: 700; color: var(--green-dark); margin: 0 6px; }
  .tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-left: 10px; }
  .tab {
    border: 1px solid var(--line); background: var(--card);
    border-radius: 20px; padding: 6px 15px; font-size: 13px; cursor: pointer; color: var(--ink);
  }
  .tab:hover { border-color: var(--green); }
  .tab.active { background: var(--green); border-color: var(--green); color: #fff; }
  .filebtns { margin-left: auto; display: flex; gap: 6px; }
  .filebtn {
    border: 1px solid var(--line); background: var(--card);
    border-radius: 6px; padding: 5px 11px; font-size: 12px; cursor: pointer; color: var(--muted);
  }
  .filebtn.active { border-color: var(--red); color: var(--red); font-weight: 600; }

  .viewer { flex: 1; min-height: 0; background: #e9e4d3; position: relative; }
  .viewer iframe { width: 100%; height: 100%; border: 0; background: #fff; }
  .viewer .imgwrap { width: 100%; height: 100%; overflow: auto; text-align: center; padding: 14px 0; }
  .viewer .imgwrap img { max-width: 900px; width: 100%; display: block; margin: 0 auto; }
  .viewer .imgwrap img.page { margin-bottom: 14px; box-shadow: 0 1px 6px rgba(0,0,0,.25); background: #fff; }
  .empty {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    color: var(--muted); font-size: 14px;
  }
</style>
</head>
<body>
<header>
  <div class="brand" id="brand"></div>
  <div class="sub" id="sub"></div>__EXTRA_NAV__
  <div class="langsw"><button type="button" data-lang="zh">中</button><button type="button" data-lang="en">EN</button></div>
  <div class="gen" id="gen"></div>
</header>
<div class="layout">
  <aside>
    <div class="search"><input id="q" type="text"></div>
    <div class="datelist" id="datelist"></div>
  </aside>
  <main>
    <div class="toolbar">
      <button class="navbtn" id="prev"></button>
      <span class="curdate" id="curdate"></span>
      <button class="navbtn" id="next"></button>
      <div class="tabs" id="tabs"></div>
      <div class="filebtns" id="filebtns"></div>
    </div>
    <div class="viewer" id="viewer"><div class="empty" id="bootempty"></div></div>
  </main>
</div>
<script>
const DATA = __DATA__;
const dates = DATA.dates;                      // 新→旧
let di = 0, ti = 0, fi = 0, filter = "";
let lang = (new URLSearchParams(location.search).get("lang") || localStorage.getItem("windrise_lang") || "zh");

const $ = id => document.getElementById(id);
const UI = {
  zh: {
    brand: 'WINDRISE<span> ·</span> 日报台',
    sub: '形态 / 资金潮汐 / 大宗信号 / KOL观点',
    gen: '__NOTE__生成于 __GENERATED__ · 共 __NDATES__ 个交易日',
    search: '搜日期，如 0616 / 2026-06',
    prev: '← 前一天',
    next: '后一天 →',
    loading: '加载中…',
    noMatch: '没有匹配的日期',
    noReport: '当天没有这份报告',
    days: '份',
    kolLink: 'KOL终端 ↗',
    generated: '生成于',
    totalDays: '个交易日'
  },
  en: {
    brand: 'WINDRISE<span> ·</span> Report Desk',
    sub: 'Patterns / Tide of Funds / Commodity Signals / KOL Views',
    gen: '__NOTE__Generated at __GENERATED__ · __NDATES__ trading days',
    search: 'Search dates, e.g. 0616 / 2026-06',
    prev: '← Previous',
    next: 'Next →',
    loading: 'Loading…',
    noMatch: 'No matching dates',
    noReport: 'No report for this day',
    days: 'files',
    kolLink: 'KOL Terminal ↗',
    generated: 'Generated at',
    totalDays: 'trading days'
  }
};
const TYPE_EN = {"期货形态":"Patterns","A股形态":"A-Share Patterns","资金潮汐":"Tide of Funds","期货资金潮汐":"Tide of Funds","大宗信号·四类资金":"Commodity Signals","KOL观点":"KOL Views"};
const FILE_EN = {"网页版":"Web","交互版":"Interactive","长图":"Long Image","PDF":"PDF"};
const WEEKDAY_EN = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

function t(k){ return (UI[lang] && UI[lang][k]) || UI.zh[k] || k; }
function typeText(v){ return lang === "en" ? (TYPE_EN[v] || v) : v; }
function fileText(v){ return lang === "en" ? (FILE_EN[v] || v) : v; }
function fmtDateLabel(item){
  if (lang !== "en") return item.label;
  const y = item.date.slice(0,4), m = item.date.slice(4,6), d = item.date.slice(6,8);
  const dt = new Date(`${y}-${m}-${d}T00:00:00`);
  const wd = WEEKDAY_EN[(dt.getDay() + 6) % 7] || "";
  return `${y}-${m}-${d} ${wd}`;
}
function syncUi(){
  localStorage.setItem("windrise_lang", lang);
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  document.title = lang === "en" ? "WINDRISE · Report Desk" : "WINDRISE · 日报台";
  $("brand").innerHTML = t("brand");
  $("sub").textContent = t("sub");
  $("gen").textContent = t("gen");
  $("q").placeholder = t("search");
  $("prev").textContent = t("prev");
  $("next").textContent = t("next");
  if ($("bootempty")) $("bootempty").textContent = t("loading");
  const nav = document.querySelector("header .navlink");
  if (nav) nav.textContent = t("kolLink");
  document.querySelectorAll(".langsw button").forEach(b => b.setAttribute("data-on", b.dataset.lang === lang ? "1" : ""));
}

function visibleDates() {
  if (!filter) return dates.map((d, i) => i);
  const f = filter.replace(/[-\/\s]/g, "");
  return dates.map((d, i) => i).filter(i => dates[i].date.includes(f));
}

function renderDateList() {
  const idxs = visibleDates();
  $("datelist").innerHTML = idxs.map(i => `
    <div class="dateitem ${i === di ? "active" : ""}" onclick="pickDate(${i})">
      <span>${fmtDateLabel(dates[i])}</span><span class="n">${dates[i].types.length}${t("days")}</span>
    </div>`).join("") || '<div style="padding:12px;color:var(--muted);font-size:13px">'+t("noMatch")+'</div>';
}

function renderTabs() {
  const d = dates[di];
  $("curdate").textContent = fmtDateLabel(d);
  $("tabs").innerHTML = d.types.map((t, i) =>
    `<button class="tab ${i === ti ? "active" : ""}" onclick="pickType(${i})">${typeText(t.name)}</button>`).join("");
  $("prev").disabled = di >= dates.length - 1;
  $("next").disabled = di <= 0;
}

function renderFileBtns() {
  const files = dates[di].types[ti].files;
  $("filebtns").innerHTML = files.length > 1 ? files.map((f, i) =>
    `<button class="filebtn ${i === fi ? "active" : ""}" onclick="pickFile(${i})">${fileText(f.label)}</button>`).join("") : "";
}

// 普通模式下文件带 href（相对路径）；打包模式下带 b64（内嵌数据），
// 内嵌数据首次访问时转成 blob URL 并缓存。
function srcOf(f) {
  if (f.href) return f.href;
  if (!f._url) {
    const bin = atob(f.b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    f._url = URL.createObjectURL(new Blob([bytes], { type: f.mime }));
    f.b64 = null;
  }
  return f._url;
}

function renderViewer() {
  const f = dates[di].types[ti].files[fi];
  const v = $("viewer");
  if (!f) { v.innerHTML = '<div class="empty">'+t("noReport")+'</div>'; return; }
  if (f.kind === "pages") {
    // 打包版里 PDF 已在生成时逐页转成图片（Chrome 不渲染内嵌数据的 PDF）
    v.innerHTML = `<div class="imgwrap">` +
      f.pages.map(p => `<img class="page" src="data:image/jpeg;base64,${p}" alt="">`).join("") +
      `</div>`;
    return;
  }
  const src = srcOf(f);
  if (f.kind === "img") {
    v.innerHTML = `<div class="imgwrap"><img src="${src}" alt=""></div>`;
  } else {
    v.innerHTML = `<iframe src="${src}"></iframe>`;
  }
}

function renderAll() { syncUi(); renderDateList(); renderTabs(); renderFileBtns(); renderViewer(); }

window.pickDate = i => {
  const prevKey = dates[di].types[ti] && dates[di].types[ti].key;
  di = i;
  // 尽量停留在同类型报告上（例如一路翻看每天的资金潮汐）
  const j = dates[di].types.findIndex(t => t.key === prevKey);
  ti = j >= 0 ? j : 0; fi = 0;
  renderAll();
};
window.pickType = i => { ti = i; fi = 0; renderAll(); };
window.pickFile = i => { fi = i; renderFileBtns(); renderViewer(); };

$("prev").onclick = () => { if (di < dates.length - 1) pickDate(di + 1); };
$("next").onclick = () => { if (di > 0) pickDate(di - 1); };
$("q").addEventListener("input", e => { filter = e.target.value.trim(); renderDateList(); });
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "ArrowLeft") $("prev").click();
  if (e.key === "ArrowRight") $("next").click();
});
document.querySelectorAll(".langsw button").forEach(b => b.onclick = () => { lang = b.dataset.lang; renderAll(); });

renderAll();
</script>
</body>
</html>
"""


def render_page(dates, note="", extra_nav=""):
    return (
        TEMPLATE
        .replace("__DATA__", json.dumps({"dates": dates}, ensure_ascii=False))
        .replace("__GENERATED__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        .replace("__NDATES__", str(len(dates)))
        .replace("__NOTE__", note)
        .replace("__EXTRA_NAV__", extra_nav)
    )


# 固定入口页：形态 / 资金潮汐。像 KOL终端 一样用不变的网址直达“最新一天”。
# 每次重建时，把这两个页面重定向到当天最新的对应报告（优先网页版/交互版，其次长图/PDF）。
ENTRY_PAGES = [
    ("形态", "期货形态", "期货形态"),
    ("资金潮汐", "期货资金潮汐", "期货资金潮汐"),
    ("kol", "KOL观点", "KOL观点"),   # 2026-07-08: 旧KOL终端停在7/3, 改为与其余入口一致的"跳最新"
]

REDIRECT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · 最新</title>
<link rel="canonical" href="__TARGET__">
<style>
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f3efe4; color: #23312b; margin: 0; height: 100vh;
    display: flex; align-items: center; justify-content: center; text-align: center; }
  a { color: #17604b; }
</style>
</head>
<body>
<p id="msg">正在跳转到最新一天的__TITLE__（__DATE__）…<br>若未自动跳转，请<a id="jump" href="__TARGET__">点此打开</a>。</p>
<script>
  (function () {
    var target = "__TARGET__";
    var params = new URLSearchParams(location.search);
    var lang = params.get("lang") || localStorage.getItem("windrise_lang");
    if (lang === "zh" || lang === "en") {
      target += (target.indexOf("?") >= 0 ? "&" : "?") + "lang=" + lang;
    }
    document.getElementById("jump").href = target;
    location.replace(target);
  })();
</script>
</body>
</html>
"""


def latest_type_file(dates, type_key):
    """从新到旧找到第一天含该类型报告，返回 (date, best_file)；best_file 已按优先级排序取首个。"""
    for d in dates:
        for t in d["types"]:
            if t["key"] == type_key and t["files"]:
                return d["date"], t["files"][0]
    return None, None


def write_entry_pages(dates):
    """生成 日报站/形态/index.html 与 日报站/资金潮汐/index.html 两个固定入口。"""
    for folder, type_key, title in ENTRY_PAGES:
        date, f = latest_type_file(dates, type_key)
        if not f:
            continue
        # f["href"] 相对于 日报站/（形如 ../日报/YYYYMMDD/xxx）；入口页在 日报站/<folder>/ 下，需再上一层
        target = "../" + f["href"]
        out_dir = SITE_DIR / folder
        out_dir.mkdir(exist_ok=True)
        page = (REDIRECT_TEMPLATE
                .replace("__TITLE__", title)
                .replace("__DATE__", date)
                .replace("__TARGET__", target))
        (out_dir / "index.html").write_text(page, encoding="utf-8")
        print(f"入口页：{folder}/ → {date} 最新（{f['label']}）")


def main():
    dates = scan()
    if not dates:
        raise SystemExit(f"在 {REPORT_DIR} 下没找到任何日期文件夹（形如 20260703）")
    extra_nav = ""
    if (SITE_DIR / "kol" / "index.html").exists():
        extra_nav = '\n  <a class="navlink" href="kol/index.html" target="_blank">KOL终端 ↗</a>'
    html_out = render_page(dates, note="", extra_nav=extra_nav)
    OUT_FILE.write_text(html_out, encoding="utf-8")
    write_entry_pages(dates)
    total = sum(len(d["types"]) for d in dates)
    print(f"完成：{len(dates)} 天、{total} 份报告 → {OUT_FILE}")
    print(f"最新一天：{dates[0]['label']}（{'、'.join(t['name'] for t in dates[0]['types'])}）")


if __name__ == "__main__":
    main()
