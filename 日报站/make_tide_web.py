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
    m = re.search(r"名义净持仓\(亿\)\|([+-]?[\d.]+)\|\s*亿[^|]*\|([+-]?[\d.]+亿)", flow)
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
    # class=chart 依次为: 各类资金净流向 / 净买卖双榜 / 价格×持仓象限
    cohort_img = chart_imgs[0] if len(chart_imgs) > 0 else ""
    dual_img = chart_imgs[1] if len(chart_imgs) > 1 else ""
    quad_img = chart_imgs[2] if len(chart_imgs) > 2 else (chart_imgs[-1] if chart_imgs else "")

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
    return meta, rows, sectors, meta_tide_img, quad_img, cohort_img, dual_img


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
  .tidechart{width:100%;max-width:440px;display:block;border:1px solid var(--line);border-radius:12px;background:#fff;margin:8px 0 4px;cursor:zoom-in}
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
  /* ── 富面板 ── */
  h2.sec-h{font-family:Georgia,"Noto Serif CJK SC",serif;font-size:16px;color:var(--dark);margin:26px 0 12px;
           display:flex;align-items:center;gap:9px}
  h2.sec-h::before{content:"";width:7px;height:19px;background:var(--gold);border-radius:3px}
  h2.sec-h small{font-size:11.5px;color:var(--mut);font-weight:400}
  .pano{display:flex;flex-wrap:wrap;gap:22px;align-items:center;background:var(--panel);
        border:1px solid var(--line);border-radius:14px;padding:16px 20px}
  .pano .legend{display:flex;flex-direction:column;gap:6px;font-size:12.5px}
  .pano .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px;vertical-align:middle}
  .boards{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:12px}
  .board{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 13px}
  .board .bh{font-weight:700;font-size:13.5px;margin-bottom:8px;display:flex;justify-content:space-between}
  .board .bh small{color:var(--mut);font-weight:400;font-size:11px}
  .brow{display:flex;align-items:center;gap:7px;margin:6px 0;font-size:12.5px}
  .brow .bn{width:52px;font-weight:600;flex:none}
  .brow .bb{flex:1;height:20px;background:#efe9d8;border-radius:6px;position:relative;overflow:hidden}
  .brow .bb i{display:block;height:100%;border-radius:6px}
  .brow .ba{position:absolute;right:7px;top:2px;font-size:11px;font-weight:700;color:#fff;font-family:Georgia,serif;
            text-shadow:0 1px 2px rgba(0,0,0,.3)}
  .brow .br{width:40px;text-align:right;font-size:11px;flex:none}
  .heat{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:9px}
  .htile{border-radius:12px;padding:13px 12px;color:#fff;cursor:pointer;transition:transform .1s}
  .htile:hover{transform:translateY(-2px)}
  .htile .hn{font-size:14px;font-weight:700} .htile .hv{font-size:20px;font-family:Georgia,serif;margin-top:3px}
  .htile .hd{font-size:10.5px;opacity:.85}
  .cols2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
  .cardbox{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 15px}
  .cardbox .ch{font-weight:700;font-size:13.5px;margin-bottom:8px}
  .prow{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:12.5px}
  .prow .pn{width:52px;font-weight:600;flex:none}.prow .pd{flex:1;color:var(--mut)}
  .chip2{display:inline-block;font-size:12px;padding:4px 10px;border-radius:9px;margin:3px 5px 3px 0;font-weight:600}
  .reson{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:9px}
  .rcard{border:1px solid var(--line);border-radius:10px;padding:9px 11px;background:var(--card)}
  .rcard .rn{font-weight:700;font-size:13px;display:flex;justify-content:space-between;align-items:center}
  .rtag{color:#fff;font-size:10.5px;padding:1px 8px;border-radius:7px}
  .rcard .rs{font-size:11px;color:var(--mut);margin-top:4px}
  .brief{background:linear-gradient(135deg,#fffdf6,#f4eede);border:1px solid var(--line);border-radius:14px;padding:6px 22px}
  .brief li{font-size:13.5px;line-height:1.7;margin:9px 0 9px 6px}
  .imgrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
  .imgrow img{width:100%;border:1px solid var(--line);border-radius:12px;background:#fff;cursor:zoom-in}
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

  <h2 class="sec-h">多空动作全景 <small>加多 / 减多 / 加空 / 减空 分布 · 情绪偏向</small></h2>
  <div class="pano" id="pano"></div>

  <h2 class="sec-h">今日速览 <small>基于当日主力席位数据自动生成</small></h2>
  <div class="brief"><ul id="brief"></ul></div>

  <h2 class="sec-h">各类资金净流向 · 净买卖双榜 <small>机构/外资/杭州/中财 + 加多加空名义 TOP</small></h2>
  <div class="imgrow" id="flowcharts"></div>

  <h2 class="sec-h">板块资金热力 <small>各板块机构名义净持仓 · 红多绿空 · 点击筛选</small></h2>
  <div class="heat" id="secbar"></div>

  <h2 class="sec-h">四类动作榜 <small>各动作按名义金额排 · 相对幅度≥50%(金色)=激进加减仓</small></h2>
  <div class="boards" id="boards"></div>

  <h2 class="sec-h">资金强度排行榜 <small>全品种可筛选/排序/点开明细</small></h2>
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

  <h2 class="sec-h">资金持续性榜 · 背离雷达 <small>连续同向天数 / 资金与价格逆向</small></h2>
  <div class="cols2" id="persradar"></div>

  <h2 class="sec-h">资金动能共振榜 · 按板块 <small>机构方向与10日趋势同向 · 可信度据样本外回测校准</small></h2>
  <div id="reson"></div>

  <details class="quadbox"><summary>价格 × 持仓象限（原图）</summary>
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

const num = s => parseFloat((s ?? "0").toString().replace(/[^0-9.\-]/g, "")) || 0;

function secbar() {
  const vals = D.sectors.map(s => num(s.net)), mx = Math.max(1, ...vals.map(Math.abs));
  $("#secbar").innerHTML = D.sectors.map((s, i) => {
    const v = vals[i], a = (0.20 + 0.80 * Math.abs(v) / mx).toFixed(2);
    const bg = v >= 0 ? `rgba(178,58,47,${a})` : `rgba(23,96,75,${a})`;
    return `<div class="htile" data-v="${s.name}" style="background:${bg}">
      <div class="hn">${s.name}</div><div class="hv">${s.net}</div><div class="hd">日 ${s.day}</div></div>`;
  }).join("");
  document.querySelectorAll(".htile").forEach(el => el.onclick = () => {
    fsec = fsec === el.dataset.v ? "" : el.dataset.v;
    document.querySelectorAll(".htile").forEach(x => x.style.outline = x.dataset.v === fsec ? "3px solid var(--gold)" : "");
    render();
  });
}

function pano() {
  const K = D.meta.kpi, c = k => (K[k] && K[k][0]) || 0;
  const jd = c("加多品种"), jdm = c("减多品种"), jk = c("加空品种"), jkm = c("减空品种");
  const senti = num(K["情绪偏向"]);
  const segs = [[jd, "#b23a2f"], [jdm, "#d98b6b"], [jkm, "#5fa97e"], [jk, "#17604b"]];
  const tot = segs.reduce((s, x) => s + x[0], 0) || 1, C = 2 * Math.PI * 54; let off = 0;
  const arcs = segs.map(([v, col]) => { const ln = v / tot * C;
    const el = `<circle cx="70" cy="70" r="54" fill="none" stroke="${col}" stroke-width="20" stroke-dasharray="${ln} ${C - ln}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)"/>`;
    off += ln; return el; }).join("");
  const frac = Math.max(0, Math.min(1, (senti + 100) / 200)), ang = Math.PI * (1 - frac);
  const gx = 70 + 56 * Math.cos(ang), gy = 70 - 56 * Math.sin(ang), scol = senti >= 0 ? "#b23a2f" : "#17604b";
  const semi = Math.PI * 58;
  $("#pano").innerHTML = `
    <div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">
      <div style="position:relative;width:140px;height:140px">
        <svg width="140" height="140" viewBox="0 0 140 140">${arcs}</svg>
        <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center">
          <div style="font-size:25px;font-weight:800;font-family:Georgia,serif;color:${scol}">${K["情绪偏向"] || ""}</div>
          <div style="font-size:11px;color:var(--mut)">情绪偏向</div></div>
      </div>
      <svg width="150" height="92" viewBox="0 0 140 92">
        <path d="M12 70 A58 58 0 0 1 128 70" fill="none" stroke="#17604b" stroke-width="9" stroke-dasharray="${(semi / 2).toFixed(1)} 999"/>
        <path d="M12 70 A58 58 0 0 1 128 70" fill="none" stroke="#b23a2f" stroke-width="9" stroke-dasharray="${(semi / 2).toFixed(1)} 999" stroke-dashoffset="${(-semi / 2).toFixed(1)}"/>
        <line x1="70" y1="70" x2="${gx.toFixed(1)}" y2="${gy.toFixed(1)}" stroke="var(--ink)" stroke-width="3.5" stroke-linecap="round"/>
        <circle cx="70" cy="70" r="5" fill="var(--ink)"/>
        <text x="10" y="88" font-size="9" fill="#17604b">← 极空</text><text x="96" y="88" font-size="9" fill="#b23a2f">极多 →</text>
      </svg>
    </div>
    <div class="legend">
      <div><i style="background:#b23a2f"></i>加多 <b>${jd}</b>　<i style="background:#d98b6b;margin-left:8px"></i>减多 <b>${jdm}</b></div>
      <div><i style="background:#17604b"></i>加空 <b>${jk}</b>　<i style="background:#5fa97e;margin-left:8px"></i>减空 <b>${jkm}</b></div>
      <div style="margin-top:6px;color:var(--mut);font-size:12px">在场 ${K["在场品种"] || ""} 品种 · 加多总额 ${K["加多名义总额"] || "—"} · 加空总额 ${K["加空名义总额"] || "—"} · 净额 ${K["加多−加空 净额"] || "—"}</div>
    </div>`;
}

function boards() {
  const cfg = [["加多", "var(--long)"], ["减多", "#c9744f"], ["加空", "var(--short)"], ["减空", "#5fa97e"]];
  $("#boards").innerHTML = cfg.map(([act, col]) => {
    const g = D.rows.filter(r => r.act === act && r.amt != null).sort((a, b) => (b.amt || 0) - (a.amt || 0)).slice(0, 7);
    const mx = Math.max(1, ...g.map(r => r.amt || 0)), cnt = D.rows.filter(r => r.act === act).length;
    const rs = g.map(r => { const w = Math.max(9, (r.amt || 0) / mx * 100), hot = (r.rel ?? 0) >= 50;
      return `<div class="brow"><span class="bn">${r.name}</span>
        <span class="bb"><i style="width:${w}%;background:${col}"></i><span class="ba">${r.amt_txt || r.amt + "亿"}</span></span>
        <span class="br" style="${hot ? "color:var(--gold);font-weight:700" : "color:var(--mut)"}">${r.rel == null ? "" : r.rel + "%"}</span></div>`;
    }).join("") || '<div class="muted" style="padding:8px 2px">无</div>';
    return `<div class="board"><div class="bh" style="color:${col}">${act}<small>${cnt}个</small></div>${rs}</div>`;
  }).join("");
}

function persradar() {
  const pers = D.rows.filter(r => r.streak_n).sort((a, b) => Math.abs(b.streak_n) - Math.abs(a.streak_n)).slice(0, 10);
  const pmx = Math.max(1, ...pers.map(r => Math.abs(r.streak_n)));
  const prows = pers.map(r => { const up = r.streak_n > 0, col = up ? "var(--long)" : "var(--short)", w = Math.max(10, Math.abs(r.streak_n) / pmx * 100);
    return `<div class="prow"><span class="pn">${r.name}</span>
      <span style="flex:1;height:16px;background:#efe9d8;border-radius:5px;overflow:hidden"><i style="display:block;height:100%;width:${w}%;background:${col};border-radius:5px"></i></span>
      <span style="width:92px;text-align:right;color:${col};font-weight:600;flex:none">${r.streak || ""}</span>
      <span class="pd" style="flex:none;width:88px;text-align:right">${r.netpos || ""}</span></div>`;
  }).join("") || '<div class="muted">—</div>';
  const bull = D.rows.filter(r => r.diverg && r.diverg.includes("吸筹"));
  const bear = D.rows.filter(r => r.diverg && r.diverg.includes("沽空"));
  const chips = (arr, col, bg) => arr.map(r => `<span class="chip2" style="color:${col};background:${bg}">${r.name} ${r.div_px || ""}</span>`).join("") || '<span class="muted">—</span>';
  $("#persradar").innerHTML = `
    <div class="cardbox"><div class="ch">资金持续性榜 · 机构连续同向</div>${prows}</div>
    <div class="cardbox"><div class="ch">资金背离雷达</div>
      <div style="font-size:12px;color:var(--long);font-weight:700;margin:6px 0 4px">逆势吸筹 · 加多而价跌</div>${chips(bull, "var(--long)", "#f7e6e1")}
      <div style="font-size:12px;color:var(--short);font-weight:700;margin:12px 0 4px">逆势沽空 · 加空而价涨</div>${chips(bear, "var(--short)", "#e2f0e8")}
    </div>`;
}

function reson() {
  const BO = ["有色", "黑色", "化工", "能源", "农产品", "贵金属"], byS = {};
  D.rows.filter(r => r.dir && r.conf != null).forEach(r => { (byS[r.sector] = byS[r.sector] || []).push(r); });
  let html = "";
  BO.forEach(s => { const g = (byS[s] || []).sort((a, b) => b.conf - a.conf); if (!g.length) return;
    const cards = g.map(r => { const col = r.dir === "利多" ? "var(--long)" : "var(--short)";
      const gold = (r.conf_label === "很高" || r.conf_label === "高");
      return `<div class="rcard" style="border-left:5px solid ${col}"><div class="rn">${r.name}<span class="rtag" style="background:${col}">${r.dir}</span></div>
        <div class="rs">可信度 <b style="color:${gold ? "var(--gold)" : "var(--mut)"}">${r.conf}·${r.conf_label}</b> · ${r.act || ""} 价${r.px || ""}</div></div>`;
    }).join("");
    html += `<div style="margin-bottom:12px"><div style="font-weight:700;color:var(--dark);border-left:5px solid var(--gold);padding-left:9px;margin:8px 0 7px">${s} <span class="muted">${g.length}</span></div><div class="reson">${cards}</div></div>`;
  });
  $("#reson").innerHTML = html || '<div class="muted">今日无高一致性共振品种</div>';
}

function flowcharts() {
  const imgs = [D.cohort_img, D.dual_img].filter(Boolean), box = $("#flowcharts");
  box.innerHTML = "";
  imgs.forEach(s => { const im = document.createElement("img"); im.src = s; im.onclick = () => lightbox(s); box.appendChild(im); });
  if (!imgs.length) { box.style.display = "none"; box.previousElementSibling.style.display = "none"; }
}

function brief() {
  const m = D.meta, K = m.kpi;
  const topA = x => D.rows.filter(r => r.act === x && r.amt != null).sort((a, b) => (b.amt || 0) - (a.amt || 0)).slice(0, 3).map(r => r.name + "(" + (r.amt_txt || r.amt + "亿") + ")");
  const sec = D.sectors.map(s => [s.name, num(s.net)]).sort((a, b) => a[1] - b[1]);
  const li = [];
  li.push(`机构资金潮汐净值 <b>${m.net}亿</b>,今日变动 <b>${m.chg}</b>,情绪偏向 <b>${K["情绪偏向"] || ""}</b>(加多率−加空率)。`);
  if (sec.length) li.push(`板块层面 <b style="color:var(--short)">${sec[0][0]}(${sec[0][1]}亿)</b> 资金最空、<b style="color:var(--long)">${sec[sec.length - 1][0]}(${sec[sec.length - 1][1]}亿)</b> 最多。`);
  const ta = topA("加多"), ts = topA("加空");
  if (ta.length) li.push(`加多力度居前:${ta.join("、")}。`);
  if (ts.length) li.push(`加空力度居前:${ts.join("、")}。`);
  const bull = D.rows.filter(r => r.diverg && r.diverg.includes("吸筹")).map(r => r.name);
  const bear = D.rows.filter(r => r.diverg && r.diverg.includes("沽空")).map(r => r.name);
  if (bull.length || bear.length) li.push(`背离信号:逆势吸筹 ${bull.slice(0, 3).join("、") || "无"};逆势沽空 ${bear.slice(0, 3).join("、") || "无"}。`);
  $("#brief").innerHTML = li.map(x => `<li>${x}</li>`).join("");
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

header(); pano(); brief(); flowcharts(); secbar(); boards(); render(); persradar(); reson();
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

    meta, rows, sectors, tide_img, quad_img, cohort_img, dual_img = parse(src)
    data = {"meta": meta, "rows": rows, "sectors": sectors,
            "tide_img": tide_img, "quad_img": quad_img,
            "cohort_img": cohort_img, "dual_img": dual_img}
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
