#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货资金潮汐日报 → 交互网页(可交互图表版)

数据源改为 tide_report.py 导出的 期货资金潮汐_YYYYMMDD_data.json(纯数值),
前端用自绘 SVG 渲染**可交互图表**:鼠标悬停显示十字线+数值气泡、点图放大、
逐品种/板块曲线点开即看。不再解析静态 PDF/HTML 里的位图。

用法:
    python3 make_tide_web.py                                       # 自动找最新 _data.json
    python3 make_tide_web.py 日报/20260706/期货资金潮汐_20260706_data.json
输出:同目录 期货资金潮汐_YYYYMMDD_交互.html
"""
import json
import re
import sys
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
ROOT = SITE_DIR.parent
REPORT_DIR = ROOT / "日报"


def find_latest():
    cands = sorted(REPORT_DIR.glob("2*/期货资金潮汐_*_data.json"))
    if not cands:
        raise SystemExit("日报/ 下没找到 期货资金潮汐_*_data.json(先在服务器跑 tide_report.py 生成)")
    return cands[-1]


TEMPLATE = r"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>期货资金潮汐 · 交互终端 __DATE__</title>
<style>
  :root{--bg:#f6f2e7;--panel:#fdfbf5;--card:#fff;--ink:#23312b;--mut:#8a8676;--line:#e5dfcb;
        --long:#b23a2f;--short:#17604b;--gold:#b98b2f;--dark:#0f4638;--soft:#efe9d8}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
       background:var(--bg);color:var(--ink);padding-bottom:60px}
  .wrap{max-width:1080px;margin:0 auto;padding:0 20px}
  .mast{display:flex;align-items:baseline;gap:14px;padding:22px 0 12px;border-bottom:2px solid var(--ink)}
  .brand{font-family:Georgia,serif;letter-spacing:3px;font-size:13px;color:var(--mut)}
  h1{font-family:Georgia,"Noto Serif CJK SC",serif;font-size:26px;color:var(--dark)}
  .asof{margin-left:auto;font-size:12px;color:var(--mut)}
  .langsw{display:inline-flex;align-items:center;gap:4px;border:1px solid var(--line);border-radius:999px;background:var(--card);padding:3px;margin-left:10px}
  .langsw button{border:0;background:transparent;color:var(--mut);font-size:12px;font-weight:700;padding:5px 10px;border-radius:999px;cursor:pointer}
  .langsw button[data-on="1"]{background:var(--dark);color:#fff}
  h2.sec-h{font-family:Georgia,"Noto Serif CJK SC",serif;font-size:16px;color:var(--dark);margin:26px 0 12px;display:flex;align-items:center;gap:9px;flex-wrap:wrap}
  h2.sec-h::before{content:"";width:7px;height:19px;background:var(--gold);border-radius:3px}
  h2.sec-h small{font-size:11.5px;color:var(--mut);font-weight:400}
  .hero{display:flex;gap:18px;align-items:stretch;padding:16px 0 6px;flex-wrap:wrap}
  .netcard{background:var(--dark);color:#efe9d5;border-radius:14px;padding:16px 22px;min-width:230px}
  .netcard .lb{font-size:11px;opacity:.75;letter-spacing:1px}
  .netcard b{font-size:40px;font-family:Georgia,serif;display:block;line-height:1.15}
  .netcard .sub{font-size:12px;opacity:.85;margin-top:4px}
  .kpis{flex:1;display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:8px;min-width:320px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;text-align:center}
  .kpi b{display:block;font-size:16px;font-family:Georgia,serif}
  .kpi span{font-size:10.5px;color:var(--mut)}
  /* charts */
  .chartbox{position:relative;background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 12px 4px;cursor:crosshair}
  .chartbox.zoom{cursor:zoom-in}
  .chartcap{font-size:11px;color:var(--mut);padding:2px 2px 6px;display:flex;justify-content:space-between}
  .tip{position:absolute;pointer-events:none;background:rgba(15,70,56,.95);color:#fff;font-size:11.5px;
       padding:5px 9px;border-radius:7px;white-space:nowrap;z-index:5;line-height:1.5;transform:translateY(-2px)}
  .tip b{font-family:Georgia,serif}
  svg.lc{display:block}
  .pano{display:flex;flex-wrap:wrap;gap:22px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 20px}
  .pano .legend{display:flex;flex-direction:column;gap:6px;font-size:12.5px}
  .pano .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px;vertical-align:middle}
  .brief{background:linear-gradient(135deg,#fffdf6,#f4eede);border:1px solid var(--line);border-radius:14px;padding:6px 22px}
  .brief li{font-size:13.5px;line-height:1.7;margin:9px 0 9px 6px}
  .cohbars{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
  .cbrow{display:flex;align-items:center;gap:10px;margin:9px 0;font-size:13px}
  .cbrow .cn{width:44px;font-weight:700;flex:none}
  .cbrow .ctrack{flex:1;height:22px;position:relative;background:linear-gradient(90deg,#f3ede0,#f3ede0);border-radius:6px}
  .cbrow .cbar{position:absolute;top:0;height:22px;border-radius:6px}
  .cbrow .cmid{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--line)}
  .cbrow .cv{width:74px;text-align:right;font-family:Georgia,serif;font-weight:700;flex:none}
  .cbrow .carrow{display:inline-block;width:14px;font-style:normal;color:var(--mut);transition:transform .15s}
  .cbrow.chead{cursor:pointer;border-radius:8px;padding:2px 4px}
  .cbrow.chead:hover{background:#faf6ea}
  .cbrow.sub .cn2{width:104px;font-size:12px;font-weight:600;flex:none}
  .cmem{display:none;border-left:2px solid var(--line);margin:0 0 10px 10px;padding-left:10px}
  .mbtn{border:1px solid var(--line);background:var(--card);border-radius:9px;font-size:11px;padding:2px 9px;cursor:pointer;color:var(--mut);flex:none}
  .mbtn:hover{border-color:var(--dark);color:var(--dark)}
  .heat{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
  .htile{border-radius:12px;padding:13px 14px;color:#fff;cursor:zoom-in;transition:transform .1s}
  .htile:hover{transform:translateY(-2px)}
  .htile .hn{font-size:14px;font-weight:700}.htile .hv{font-size:20px;font-family:Georgia,serif;margin-top:3px}
  .htile .hd{font-size:10.5px;opacity:.88}
  .boards{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:12px}
  .board{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 13px}
  .board .bh{font-weight:700;font-size:13.5px;margin-bottom:8px;display:flex;justify-content:space-between}
  .board .bh small{color:var(--mut);font-weight:400;font-size:11px}
  .brow{display:flex;align-items:center;gap:7px;margin:6px 0;font-size:12.5px}
  .brow .bn{width:52px;font-weight:600;flex:none}
  .brow .bb{flex:1;height:20px;background:var(--soft);border-radius:6px;position:relative;overflow:hidden}
  .brow .bb i{display:block;height:100%;border-radius:6px}
  .brow .ba{position:absolute;right:7px;top:2px;font-size:11px;font-weight:700;color:#fff;font-family:Georgia,serif;text-shadow:0 1px 2px rgba(0,0,0,.3)}
  .brow .br{width:40px;text-align:right;font-size:11px;flex:none}
  .controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:8px 0 14px}
  .pill{border:1px solid var(--line);background:var(--card);border-radius:18px;padding:6px 13px;font-size:12.5px;cursor:pointer}
  .pill[data-on="1"]{background:var(--dark);border-color:var(--dark);color:#fff}
  .controls input{border:1px solid var(--line);border-radius:18px;padding:7px 14px;font-size:13px;background:var(--card);outline:none;width:150px}
  .controls select{border:1px solid var(--line);border-radius:18px;padding:6px 10px;font-size:12.5px;background:var(--card)}
  .lab{font-size:11.5px;color:var(--mut);margin-left:4px}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  thead th{font-size:11px;color:var(--mut);font-weight:600;text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);background:var(--panel);cursor:pointer}
  tbody td{padding:8px 10px;font-size:13px;border-bottom:1px solid #f0ebdb;vertical-align:middle}
  tbody tr.main{cursor:pointer}tbody tr.main:hover td{background:#faf6ea}
  .nm2{font-weight:700;font-size:14px}
  .tag{font-size:11px;border-radius:8px;padding:1px 8px;color:#fff;white-space:nowrap}
  .tag.jd{background:var(--long)}.tag.jk{background:var(--short)}.tag.less{opacity:.58}
  .amt{font-family:Georgia,serif;font-size:14px}
  .rel-hot{color:var(--gold);font-weight:700}.muted{color:var(--mut)}
  .confcell{display:flex;align-items:center;gap:6px;min-width:96px}
  .confbar{flex:1;height:5px;background:var(--soft);border-radius:3px;max-width:52px}
  .confbar i{display:block;height:100%;border-radius:3px}
  .detail td{background:#fbf8ef!important}
  .dgrid{display:flex;gap:22px;flex-wrap:wrap;align-items:center;padding:4px 2px 8px}
  .dgrid .di span{color:var(--mut)}.dgrid .di b{font-family:Georgia,serif}
  .cols2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
  .cardbox{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 15px}
  .cardbox .ch{font-weight:700;font-size:13.5px;margin-bottom:8px}
  .prow{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:12.5px}
  .prow .pn{width:52px;font-weight:600;flex:none}
  .chip2{display:inline-block;font-size:12px;padding:4px 10px;border-radius:9px;margin:3px 5px 3px 0;font-weight:600}
  .reson{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:9px}
  .rcard{border:1px solid var(--line);border-radius:10px;padding:9px 11px;background:var(--card)}
  .rcard .rn{font-weight:700;font-size:13px;display:flex;justify-content:space-between;align-items:center}
  .rtag{color:#fff;font-size:10.5px;padding:1px 8px;border-radius:7px}
  .rcard .rs{font-size:11px;color:var(--mut);margin-top:4px}
  .btgroups{display:flex;flex-direction:column;gap:14px}
  .btgroup{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
  .bthead{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:10px}
  .btname{font-family:Georgia,"Noto Serif CJK SC",serif;font-size:18px;font-weight:700;color:var(--dark)}
  .btbadge{font-size:11px;font-weight:700;border-radius:999px;padding:3px 9px;background:var(--soft);color:var(--dark)}
  .btbadge.rev{background:#f5dfd9;color:var(--long)}
  .btmetrics{margin-left:auto;display:flex;gap:16px;flex-wrap:wrap}
  .btmetric{font-size:11px;color:var(--mut);text-align:right}.btmetric b{display:block;font:700 17px Georgia,serif;color:var(--ink)}
  .btread{font-size:12.5px;line-height:1.65;color:var(--ink);margin:2px 0 11px;padding:8px 11px;background:#fff;border-left:4px solid var(--gold);border-radius:7px}
  .btcharts{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:10px}
  .btchart{background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px 10px}
  .btcname{display:flex;justify-content:space-between;align-items:center;font-size:12px;font-weight:700;margin-bottom:5px}
  .btcname small{font-weight:400;color:var(--mut)}
  .btlegend{display:flex;gap:13px;color:var(--mut);font-size:10.5px;margin-top:4px}.btlegend i{display:inline-block;width:13px;height:2px;vertical-align:middle;margin-right:4px}
  .btnote{font-size:10.5px;color:var(--mut);margin-top:10px;line-height:1.55}
  .foot{margin-top:24px;border-top:1px solid var(--line);padding-top:10px;font-size:11.5px;color:var(--mut)}
  .empty{padding:30px;text-align:center;color:var(--mut)}
  html[lang="en"] .brow .bn{width:108px;font-size:11px;line-height:1.15}
  html[lang="en"] .brow .ba{right:6px;top:3px;font-size:10px}
  html[lang="en"] .brow .br{width:54px;font-size:10.5px}
  html[lang="en"] .board .bh{font-size:12px}
  html[lang="en"] thead th{font-size:10px}
  html[lang="en"] tbody td{font-size:12.5px}
  html[lang="en"] .amt{font-size:12.5px}
  #modal{position:fixed;inset:0;background:rgba(20,26,23,.78);display:none;align-items:center;justify-content:center;z-index:50;padding:24px}
  #modal .mbox{background:#fff;border-radius:14px;padding:18px 20px;max-width:900px;width:100%}
  #modal .mh{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
  #modal .mx{cursor:pointer;color:var(--mut);font-size:20px}
</style></head><body>
<div class="wrap">
  <div class="mast"><div class="brand">WINDRISE</div><h1 id="title"></h1><div class="asof" id="asof"></div><div class="langsw"><button type="button" data-lang="zh">中</button><button type="button" data-lang="en">EN</button></div></div>

  <div class="hero">
    <div class="netcard"><div class="lb" id="netlb"></div><b id="netv"></b><div class="sub" id="netsub"></div></div>
    <div class="kpis" id="kpis"></div>
  </div>

  <h2 class="sec-h" id="sec-tide"></h2>
  <div class="chartbox zoom" id="tidebox" onclick="enlarge('tide')"><div id="tidechart"></div></div>

  <h2 class="sec-h" id="sec-pano"></h2>
  <div class="pano" id="pano"></div>

  <h2 class="sec-h" id="sec-brief"></h2>
  <div class="brief"><ul id="brief"></ul></div>

  <h2 class="sec-h" id="sec-cohorts"></h2>
  <div class="cohbars" id="cohbars"></div>

  <h2 class="sec-h" id="sec-backtest"></h2>
  <div class="btgroups" id="backtests"></div>

  <h2 class="sec-h" id="sec-heat"></h2>
  <div class="heat" id="heat"></div>

  <h2 class="sec-h" id="sec-boards"></h2>
  <div class="boards" id="boards"></div>

  <h2 class="sec-h" id="sec-table"></h2>
  <div class="controls">
    <input id="q" type="text">
    <button class="pill fact" data-v=""></button><button class="pill fact" data-v="加多"></button>
    <button class="pill fact" data-v="减多"></button><button class="pill fact" data-v="加空"></button>
    <button class="pill fact" data-v="减空"></button>
    <span class="lab" id="lab-dir"></span><button class="pill fdir" data-v=""></button>
    <button class="pill fdir" data-v="利多"></button><button class="pill fdir" data-v="利空"></button>
    <span class="lab" id="lab-sort"></span><select id="sort">
      <option value="amt"></option><option value="conf"></option>
      <option value="ratio"></option><option value="streak"></option></select>
  </div>
  <table><thead><tr><th data-k="name">品种</th><th data-k="sector">板块</th><th data-k="act">动作</th>
    <th data-k="amt">名义金额</th><th data-k="ratio">相对</th><th data-k="hb">环比</th>
    <th data-k="conf">共振</th><th data-k="streak">持续</th><th>近60日</th></tr></thead>
    <tbody id="tb"></tbody></table>

  <h2 class="sec-h" id="sec-persist"></h2>
  <div class="cols2" id="persradar"></div>

  <h2 class="sec-h" id="sec-quad"></h2>
  <div class="chartbox" id="quadbox" style="cursor:default"></div>

  <h2 class="sec-h" id="sec-reson"></h2>
  <div id="reson"></div>

  <div class="foot" id="foot"></div>
</div>
<div id="modal"><div class="mbox"><div class="mh"><b id="mtitle"></b><span class="mx" onclick="closeModal()">✕</span></div><div id="mbody"></div></div></div>
<script>
const D = __DATA__;
const $ = s => document.querySelector(s);
const RED="#b23a2f",GRN="#17604b",GOLD="#b98b2f",DARK="#0f4638";
let fact="",fdir="",q="",sortKey="amt",opened=null;
let lang=(new URLSearchParams(location.search).get('lang')||localStorage.getItem('windrise_lang')||'zh');
const UI={
  zh:{
    title:'期货资金潮汐 · 交互终端',asof:'__DATE__ · 盘后主力席位资金视图',netlb:'机构资金潮汐净值 · 名义净持仓(亿)',
    tide:'机构资金潮汐净值 · 40日走势',tideSub:'鼠标移到线上看每日数值 · 点图放大',
    pano:'多空动作全景',panoSub:'加多/减多/加空/减空分布 · 情绪偏向',
    brief:'今日速览',briefSub:'基于当日主力席位数据自动生成',
    cohorts:'各类资金今日净流向',cohortsSub:'机构/外资/杭州/中财/散户 · 名义(亿) · 点行展开成员席位 · 点曲线看40日',
    heat:'板块资金热力',heatSub:'机构名义净持仓 · 红多绿空 · 点块看40日曲线 / 点击筛选',
    boards:'四类动作榜',boardsSub:'各动作按名义金额(CNY 100m)排序 · 相对幅度≥50%(金色)=激进',
    table:'资金强度排行榜',tableSub:'可筛选/排序/点行看该品种60日机构净持仓曲线',
    persist:'资金持续性榜 · 背离雷达',persistSub:'连续同向天数 / 资金与价格逆向',
    quad:'价格 × 持仓象限',quadSub:'横=当日价格% 纵=机构资金流向强度 · 悬停看品种',
    reson:'资金动能共振榜 · 按板块',resonSub:'机构方向与10日趋势同向 · 可信度据样本外回测校准',
    search:'搜品种，如 碳酸锂',all:'全部',dir:'共振',sort:'排序',amt:'名义金额 (CNY 100m)',conf:'共振可信度',ratio:'相对幅度',streak:'持续天数',
    name:'品种',sector:'板块',act:'动作',mom:'环比',last60:'近60日',hoverDaily:'悬停看每日',clickCurve:'点看曲线',curve:'曲线',
    noData:'无数据',none:'无',noMatch:'没有匹配的品种',emptyReson:'今日无高一致性共振品种',
    netMove:'今日变动',range40:'40日区间',longCnt:'加多品种',trimLongCnt:'减多品种',shortCnt:'加空品种',trimShortCnt:'减空品种',
    senti:'情绪偏向',inPlay:'在场品种',amtLong:'加多总额',amtShort:'加空总额',
    extremeShort:'← 极空',extremeLong:'极多 →',netLong:'净多',netShort:'净空',todayAction:'今日动作',todayPx:'当日价格',todayChg:'当日涨跌',
    resonance:'共振',instLong:'逆势吸筹 · 加多而价跌',instShort:'逆势沽空 · 加空而价涨',persistRank:'资金持续性榜 · 机构连续同向',divRadar:'资金背离雷达',
    currentNet:'当前净持仓',priceFlowUp:'量价齐升·强多',priceDownAcc:'逆势吸筹',distribute:'冲高派发',exit:'杀跌离场',priceAxis:'价格涨跌 % →',
    price:'价',strength:'资金强度',openMembers:'点行展开成员席位',members:'成员席位',dataSource:'数据源',nominal:'名义=持仓×合约乘数×收盘价',desc:'描述性研究,不构成投资建议',
    todayFlowIn:'净流入',todayFlowOut:'净流出',sectorLayer:'板块层面',mostShort:'资金最空',mostLong:'最多',topLong:'加多力度居前',topShort:'加空力度居前',
    divSignal:'背离信号',bullList:'逆势吸筹',bearList:'逆势沽空',tierDot:'可信度',currentShow:'当前显示',monitoring:'监测',accounts:'账号',
    backtest:'三类席位板块回测',backtestSub:'机构 / 杭州 / 外资 · 信号与未来价格相关度及胜率 · 仅展示各组最佳板块',
    bestSector:'最佳板块',forward:'顺向',reverse:'反向',corr:'相关度',winRate:'胜率',horizon:'观察周期',samples:'样本',tradingDays:'个交易日',
    seatNet:'席位净持仓',priceTrend:'价格',latestSignal:'最新信号',currentBias:'当前解读',noActiveSignal:'未达触发阈值',bullishWatch:'偏多观察',bearishWatch:'偏空观察',evidenceWeak:'弱',evidenceMedium:'中等',evidenceStrong:'较强',evidence:'证据强度',
    backtestNote:'口径：板块席位名义净流向经过去60日标准化，与未来1/3/5日板块等权收益比较；|z|≥0.5才计入胜率。结果未计交易成本，重叠周期可能放大统计显著性。',
    aggressive:'激进',items:'个',days:'日'
  },
  en:{
    title:'Futures Tide of Funds · Interactive Terminal',asof:'__DATE__ · Post-close view of major seat positioning',netlb:'Institutional Tide NAV · Nominal Net Position (CNY 100m)',
    tide:'Institutional Tide NAV · 40-Day Trend',tideSub:'Hover for daily values · Click to enlarge',
    pano:'Long/Short Action Panorama',panoSub:'Add Long / Trim Long / Add Short / Trim Short · Sentiment bias',
    brief:'Today at a Glance',briefSub:'Auto-generated from today’s major-seat data',
    cohorts:'Net Flow by Participant Type Today',cohortsSub:'Institutions / Foreign / Hangzhou / Zhongcai / Retail · Nominal (CNY 100m) · Expand member seats · Open 40-day curve',
    heat:'Sector Heatmap of Funds',heatSub:'Institutional nominal net positions · Red=long Green=short · Click tiles for 40-day curves',
    boards:'Four Action Leaderboards',boardsSub:'Ranked by nominal size (CNY 100m) · Relative move ≥ 50% (gold) = aggressive',
    table:'Fund Strength Ranking',tableSub:'Filter / sort / click a row for the 60-day institutional position curve',
    persist:'Persistence Ranking · Divergence Radar',persistSub:'Consecutive same-direction days / fund-price divergence',
    quad:'Price × Positioning Quadrants',quadSub:'X = daily price % · Y = institutional flow strength · Hover for contract',
    reson:'Momentum Resonance by Sector',resonSub:'Institutional direction aligned with 10-day trend · confidence calibrated on out-of-sample tests',
    search:'Search contract, e.g. Lithium Carbonate',all:'All',dir:'Resonance',sort:'Sort',amt:'Nominal Size (CNY 100m)',conf:'Resonance Confidence',ratio:'Relative Move',streak:'Streak Days',
    name:'Contract',sector:'Sector',act:'Action',mom:'DoD',last60:'Last 60D',hoverDaily:'Hover for daily values',clickCurve:'Open curve',curve:'Curve',
    noData:'No data',none:'None',noMatch:'No matching contracts',emptyReson:'No high-consensus resonance contract today',
    netMove:'Today change',range40:'40-day range',longCnt:'Added-long contracts',trimLongCnt:'Trimmed-long contracts',shortCnt:'Added-short contracts',trimShortCnt:'Trimmed-short contracts',
    senti:'Sentiment bias',inPlay:'Contracts in play',amtLong:'Total add-long',amtShort:'Total add-short',
    extremeShort:'← Extreme short',extremeLong:'Extreme long →',netLong:'Net long',netShort:'Net short',todayAction:'Today change',todayPx:'Close',todayChg:'Daily change',
    resonance:'Resonance',instLong:'Counter-trend accumulation · add long while price falls',instShort:'Counter-trend shorting · add short while price rises',persistRank:'Persistence Ranking · institutions in one direction',divRadar:'Fund Divergence Radar',
    currentNet:'Current net position',priceFlowUp:'Price and flow rising together',priceDownAcc:'Counter-trend accumulation',distribute:'Strength into distribution',exit:'Panic exit',priceAxis:'Price change % →',
    price:'Price',strength:'Flow strength',openMembers:'Expand member seats',members:'Member seats',dataSource:'Source',nominal:'Nominal = position × contract multiplier × close',desc:'Descriptive research only, not investment advice',
    todayFlowIn:'net inflow',todayFlowOut:'net outflow',sectorLayer:'By sector',mostShort:'most net-short',mostLong:'most net-long',topLong:'Top add-long strength',topShort:'Top add-short strength',
    divSignal:'Divergence signal',bullList:'Counter-trend accumulation',bearList:'Counter-trend shorting',tierDot:'Confidence',currentShow:'Showing',monitoring:'monitoring',accounts:'accounts',
    backtest:'Seat Signals by Sector · Backtest',backtestSub:'Institutions / Hangzhou / Foreign · correlation and hit rate versus subsequent returns · best sector only',
    bestSector:'Best sector',forward:'Directional',reverse:'Contrarian',corr:'Correlation',winRate:'Hit rate',horizon:'Horizon',samples:'Samples',tradingDays:'trading days',
    seatNet:'Seat net position',priceTrend:'Price',latestSignal:'Latest signal',currentBias:'Current read',noActiveSignal:'Below trigger threshold',bullishWatch:'Bullish watch',bearishWatch:'Bearish watch',evidenceWeak:'Weak',evidenceMedium:'Moderate',evidenceStrong:'Stronger',evidence:'Evidence',
    backtestNote:'Method: sector nominal seat flow is standardized on the prior 60 days and compared with equal-weight sector returns over the next 1/3/5 days; hit rate includes |z| ≥ 0.5 signals only. Trading costs are excluded and overlapping horizons may overstate significance.',
    aggressive:'Aggressive',items:'items',days:'days'
  }
};
const TERM_EN={"铜":"Copper","铝":"Aluminum","锌":"Zinc","铅":"Lead","镍":"Nickel","锡":"Tin","黄金":"Gold","白银":"Silver","氧化铝":"Alumina","热卷":"Hot-Rolled Coil","焦煤":"Coking Coal","燃油":"Fuel Oil","苯乙烯":"Styrene","PVC":"PVC","尿素":"Urea","豆二":"Soybean No.2","棕榈油":"Palm Oil","棉花":"Cotton","鸡蛋":"Eggs","红枣":"Red Dates","不锈钢":"Stainless Steel","工业硅":"Industrial Silicon","碳酸锂":"Lithium Carbonate","螺纹钢":"Rebar","铁矿石":"Iron Ore","焦炭":"Coke","硅铁":"Ferrosilicon","锰硅":"Silicomanganese","原油":"Crude Oil","沥青":"Bitumen","液化气":"LPG","PTA":"PTA","甲醇":"Methanol","乙二醇":"MEG","LLDPE":"LLDPE","PP":"Polypropylene","纯碱":"Soda Ash","玻璃":"Glass","短纤":"Polyester Staple Fiber","20号胶":"TSR 20","橡胶":"Rubber","纸浆":"Pulp","豆一":"Soybean No.1","豆粕":"Soybean Meal","豆油":"Soybean Oil","菜粕":"Rapeseed Meal","菜油":"Rapeseed Oil","白糖":"Sugar","玉米":"Corn","淀粉":"Corn Starch","生猪":"Live Hogs","苹果":"Apples","花生":"Peanuts","有色":"Non-Ferrous","黑色":"Ferrous","化工":"Chemicals","能源":"Energy","农产品":"Agri","贵金属":"Precious Metals","机构":"Institutions","外资":"Foreign","杭州":"Hangzhou","中财":"Zhongcai","散户":"Retail","中信期货":"CITIC Futures","国泰君安":"Guotai Junan","东证期货":"Orient Futures","中财期货":"Zhongcai Futures","永安期货":"Yongan Futures","浙商期货":"Zheshang Futures","南华期货":"Nanhua Futures","徽商期货":"Huaan Futures","平安期货":"Ping An Futures","宝城期货":"Baocheng Futures","大地期货":"Dadi Futures","乾坤期货":"Qiankun Futures","物产中大":"Wuchan Zhongda","东方财富期货":"Eastmoney Futures","摩根大通":"J.P. Morgan"};
const ACT_EN={"加多":"Add Long","减多":"Trim Long","加空":"Add Short","减空":"Trim Short","利多":"Bullish","利空":"Bearish","连加":"Added","连减":"Reduced","很高":"Very High","高":"High","中":"Medium","低":"Low","很低":"Very Low"};
const SRC_EN={"奇货可查龙虎榜逐日主力席位净持仓":"QHQC daily major-seat net positioning","akshare 主力合约价格":"AkShare front-contract prices","机构=中信+国君+东证":"Institutions = CITIC + Guotai Junan + Orient"};
const t=k=>(UI[lang]&&UI[lang][k])||UI.zh[k]||k;
const term=v=>lang==='en'?(TERM_EN[v]||v):v;
const actText=v=>lang==='en'?(ACT_EN[v]||v):v;
const tierText=v=>lang==='en'?(ACT_EN[v]||v):v;
function secHtml(a,b){return a+' <small>'+b+'</small>'}
function sourceText(v){if(lang!=='en')return v;let s=v||'';Object.keys(SRC_EN).forEach(k=>{s=s.replaceAll(k,SRC_EN[k])});return s}
function fmt100m(a){
  return Math.abs(a||0).toFixed(2).replace(/\.?0+$/,'');
}
function amtLabel(r){
  return fmt100m(r.amt||0);
}
function syncUi(){
  localStorage.setItem('windrise_lang',lang);
  document.documentElement.lang=lang==='en'?'en':'zh-CN';
  document.title=t('title')+' __DATE__';
  $('#title').textContent=t('title'); $('#asof').textContent=t('asof'); $('#netlb').textContent=t('netlb');
  $('#sec-tide').innerHTML=secHtml(t('tide'),t('tideSub')); $('#sec-pano').innerHTML=secHtml(t('pano'),t('panoSub'));
  $('#sec-brief').innerHTML=secHtml(t('brief'),t('briefSub')); $('#sec-cohorts').innerHTML=secHtml(t('cohorts'),t('cohortsSub'));
  $('#sec-backtest').innerHTML=secHtml(t('backtest'),t('backtestSub'));
  $('#sec-heat').innerHTML=secHtml(t('heat'),t('heatSub')); $('#sec-boards').innerHTML=secHtml(t('boards'),t('boardsSub'));
  $('#sec-table').innerHTML=secHtml(t('table'),t('tableSub')); $('#sec-persist').innerHTML=secHtml(t('persist'),t('persistSub'));
  $('#sec-quad').innerHTML=secHtml(t('quad'),t('quadSub')); $('#sec-reson').innerHTML=secHtml(t('reson'),t('resonSub'));
  $('#q').placeholder=t('search'); $('#lab-dir').textContent=t('dir'); $('#lab-sort').textContent=t('sort');
  document.querySelectorAll('.fact').forEach(b=>b.textContent=b.dataset.v?actText(b.dataset.v):t('all'));
  document.querySelectorAll('.fdir').forEach(b=>b.textContent=b.dataset.v?actText(b.dataset.v):t('all'));
  [['amt','amt'],['conf','conf'],['ratio','ratio'],['streak','streak']].forEach((x,i)=>$('#sort').options[i].textContent=t(x[1]));
  const heads=document.querySelectorAll('thead th');
  [t('name'),t('sector'),t('act'),t('amt'),t('ratio'),t('mom'),t('resonance'),t('streak'),t('last60')].forEach((x,i)=>heads[i].textContent=x);
  document.querySelectorAll('.langsw button').forEach(b=>b.setAttribute('data-on',b.dataset.lang===lang?'1':''));
}

/* ── 通用可交互折线图(悬停十字线+数值气泡, 零轴双色渐变面积) ── */
function lineChart(host, y, dates, opt){
  opt=opt||{}; const H=opt.h||130, W=1000, n=y.length;
  if(!n){host.innerHTML='<div class="muted" style="padding:20px">'+t('noData')+'</div>';return;}
  const ymin=Math.min(0,...y), ymax=Math.max(0,...y), pad=((ymax-ymin)||1)*0.14, lo=ymin-pad, hi=ymax+pad;
  const X=i=> n<2?W/2:(i/(n-1))*W, Y=v=> H-(v-lo)/(hi-lo)*H, zY=Y(0);
  const line=y.map((v,i)=>(i?'L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1)).join(' ');
  const area='M'+X(0).toFixed(1)+','+zY.toFixed(1)+' '+y.map((v,i)=>'L'+X(i).toFixed(1)+','+Y(v).toFixed(1)).join(' ')+' L'+X(n-1).toFixed(1)+','+zY.toFixed(1)+'Z';
  const u='c'+Math.random().toString(36).slice(2,8);
  const fmt=opt.fmt||(v=>(''+v));
  host.innerHTML=
   '<svg class="lc" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" style="width:100%;height:'+H+'px">'+
     '<defs><clipPath id="'+u+'t"><rect x="0" y="0" width="'+W+'" height="'+zY.toFixed(1)+'"/></clipPath>'+
     '<clipPath id="'+u+'b"><rect x="0" y="'+zY.toFixed(1)+'" width="'+W+'" height="'+(H-zY).toFixed(1)+'"/></clipPath>'+
     '<linearGradient id="'+u+'gr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+RED+'" stop-opacity=".5"/><stop offset="1" stop-color="'+RED+'" stop-opacity=".04"/></linearGradient>'+
     '<linearGradient id="'+u+'gg" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="'+GRN+'" stop-opacity=".5"/><stop offset="1" stop-color="'+GRN+'" stop-opacity=".04"/></linearGradient></defs>'+
     '<path d="'+area+'" fill="url(#'+u+'gr)" clip-path="url(#'+u+'t)"/>'+
     '<path d="'+area+'" fill="url(#'+u+'gg)" clip-path="url(#'+u+'b)"/>'+
     '<line x1="0" y1="'+zY.toFixed(1)+'" x2="'+W+'" y2="'+zY.toFixed(1)+'" stroke="'+GOLD+'" stroke-width="1" stroke-dasharray="6 4" opacity=".55" vector-effect="non-scaling-stroke"/>'+
     '<path d="'+line+'" fill="none" stroke="'+DARK+'" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>'+
     '<g class="cross" style="display:none"><line class="cx" y1="0" y2="'+H+'" stroke="#8a8676" stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/><circle class="cd" r="4.5" fill="'+DARK+'" stroke="#fff" stroke-width="1.6"/></g>'+
     '<rect class="ov" x="0" y="0" width="'+W+'" height="'+H+'" fill="transparent"/></svg>'+
   '<div class="tip" style="display:none"></div>';
  const svg=host.querySelector('svg'),cross=host.querySelector('.cross'),cx=host.querySelector('.cx'),cd=host.querySelector('.cd'),tip=host.querySelector('.tip');
  function move(e){
    const r=svg.getBoundingClientRect(); if(!r.width)return;
    const cxp=(e.touches?e.touches[0].clientX:e.clientX);
    const i=Math.max(0,Math.min(n-1,Math.round((cxp-r.left)/r.width*(n-1))));
    const px=X(i),py=Y(y[i]);
    cross.style.display=''; cx.setAttribute('x1',px);cx.setAttribute('x2',px);cd.setAttribute('cx',px);cd.setAttribute('cy',py);
    tip.style.display='block';
    tip.innerHTML='<b>'+(dates&&dates[i]?dates[i]:('#'+(i+1)))+'</b><br>'+fmt(y[i]);
    const hx=(px/W)*r.width, hy=(py/H)*r.height, tw=tip.offsetWidth||90;
    tip.style.left=Math.min(r.width-tw,Math.max(0,hx-tw/2))+'px';
    tip.style.top=Math.max(0,hy-42)+'px';
  }
  svg.addEventListener('mousemove',move); svg.addEventListener('touchmove',move,{passive:true});
  const hide=()=>{cross.style.display='none';tip.style.display='none';};
  svg.addEventListener('mouseleave',hide);
}

function seatPriceChart(host,item){
  const net=item.net||[], rawclose=item.close||[], dates=item.dates||[];let carry=rawclose.find(v=>v!=null)||0;
  const close=rawclose.map(v=>{if(v!=null)carry=v;return carry;}),n=Math.min(net.length,close.length);
  if(!n){host.innerHTML='<div class="muted">'+t('noData')+'</div>';return;}
  const W=520,H=108,pad=5;
  const scale=a=>{const ok=a.filter(v=>v!=null&&Number.isFinite(+v)),lo=Math.min(...ok),hi=Math.max(...ok),span=(hi-lo)||1;return v=>H-pad-(v-lo)/span*(H-pad*2)};
  const yn=scale(net),yp=scale(close),X=i=>n<2?W/2:i/(n-1)*W;
  const path=(a,Y)=>a.map((v,i)=>(i?'L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1)).join(' ');
  host.innerHTML='<div style="position:relative"><svg class="lc" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" style="width:100%;height:'+H+'px">'+
    '<path d="'+path(close,yp)+'" fill="none" stroke="'+GOLD+'" stroke-width="1.7" opacity=".85" vector-effect="non-scaling-stroke"/>'+
    '<path d="'+path(net,yn)+'" fill="none" stroke="'+DARK+'" stroke-width="2.2" vector-effect="non-scaling-stroke"/>'+
    '<g class="cross" style="display:none"><line class="cx" y1="0" y2="'+H+'" stroke="#8a8676" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/></g><rect class="ov" width="'+W+'" height="'+H+'" fill="transparent"/></svg><div class="tip" style="display:none"></div></div>';
  const svg=host.querySelector('svg'),cross=host.querySelector('.cross'),cx=host.querySelector('.cx'),tip=host.querySelector('.tip');
  svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect(),i=Math.max(0,Math.min(n-1,Math.round((e.clientX-r.left)/r.width*(n-1)))),x=X(i);cross.style.display='';cx.setAttribute('x1',x);cx.setAttribute('x2',x);tip.style.display='block';tip.innerHTML='<b>'+dates[i]+'</b><br>'+t('seatNet')+' '+Number(net[i]).toLocaleString()+' · '+t('priceTrend')+' '+Number(close[i]).toLocaleString();tip.style.left=Math.min(r.width-(tip.offsetWidth||150),Math.max(0,x/W*r.width-60))+'px';tip.style.top='8px';});
  svg.addEventListener('mouseleave',()=>{cross.style.display='none';tip.style.display='none';});
}

/* ── 象限散点(悬停看品种) ── */
function scatter(host){
  const pts=D.rows.filter(r=>r.pc!=null);
  const W=680,H=430;
  const xl=Math.max(2,...pts.map(p=>Math.abs(p.pc)))*1.12, yl=Math.max(2.5,...pts.map(p=>Math.abs(p.z||0)))*1.12;
  const X=v=>(v+xl)/(2*xl)*W, Y=v=>H-(v+yl)/(2*yl)*H;
  const lab=(x,y,t,c)=>'<text x="'+x+'" y="'+y+'" fill="'+c+'" font-size="12" font-weight="700" text-anchor="middle" opacity=".8">'+t+'</text>';
  let s='<svg class="lc" viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">'+
    '<line x1="'+X(0)+'" y1="0" x2="'+X(0)+'" y2="'+H+'" stroke="'+'#e5dfcb'+'" stroke-width="1"/>'+
    '<line x1="0" y1="'+Y(0)+'" x2="'+W+'" y2="'+Y(0)+'" stroke="#e5dfcb" stroke-width="1"/>'+
    lab(W*0.8,20,t('priceFlowUp'),RED)+lab(W*0.16,20,t('priceDownAcc'),'#2d5f8a')+
    lab(W*0.8,H-8,t('distribute'),GOLD)+lab(W*0.16,H-8,t('exit'),GRN);
  pts.forEach((p,i)=>{const c=(p.z||0)>=0?RED:GRN;
    s+='<circle class="dot" data-i="'+i+'" cx="'+X(p.pc).toFixed(1)+'" cy="'+Y(p.z||0).toFixed(1)+'" r="6" fill="'+c+'" fill-opacity=".7" stroke="#fff" stroke-width="1"/>';});
  s+='<text x="'+ (W-6) +'" y="'+(Y(0)-6)+'" text-anchor="end" font-size="11" fill="#8a8676">'+t('priceAxis')+'</text></svg><div class="tip" style="display:none"></div>';
  host.innerHTML=s;
  const tip=host.querySelector('.tip');
  host.querySelectorAll('.dot').forEach(d=>{
    d.addEventListener('mouseenter',()=>{const p=pts[+d.dataset.i]; d.setAttribute('r',9);
      tip.style.display='block';
      tip.innerHTML='<b>'+term(p.name)+'</b>　'+actText(p.act||'')+'<br>'+t('price')+' '+(p.pc>=0?'+':'')+p.pc+'% · '+t('strength')+' '+(p.z>=0?'+':'')+p.z;
      const r=host.getBoundingClientRect(),dr=d.getBoundingClientRect();
      tip.style.left=Math.min(r.width-140,(dr.left-r.left)+8)+'px'; tip.style.top=((dr.top-r.top)-40)+'px';});
    d.addEventListener('mouseleave',()=>{d.setAttribute('r',6);tip.style.display='none';});
  });
}

/* ── 图表放大弹窗 ── */
function enlarge(which){
  if(which==='tide'){ openModal(t('tide'),''); lineChart($('#mbody'),D.tide,D.dates40,{h:340,fmt:v=>v.toFixed(1)+' '+(lang==='en'?'CNY 100m':'亿')}); }
}
function sectorModal(name){
  const s=D.sectors.find(x=>x.name===name); if(!s)return;
  openModal(term(name)+' · '+t('tide'),'');
  lineChart($('#mbody'),s.series,D.dates40,{h:320,fmt:v=>v.toFixed(1)+' '+(lang==='en'?'CNY 100m':'亿')});
}
function openModal(t){ $('#mtitle').textContent=t; $('#modal').style.display='flex'; }
function closeModal(){ $('#modal').style.display='none'; }
$('#modal').addEventListener('click',e=>{if(e.target.id==='modal')closeModal();});

/* ── 头部 / KPI ── */
function header(){
  syncUi();
  $('#netv').textContent=(D.net>0?'+':'')+D.net;
  $('#netv').style.color=D.net>=0?'#f0a89c':'#9fd8b4';
  $('#netsub').innerHTML=t('netMove')+' <b>'+(D.chg>0?'+':'')+D.chg+(lang==='en'?' CNY 100m':'亿')+'</b> · '+t('range40')+' '+D.range40[0]+' ~ '+D.range40[1]+' '+(lang==='en'?'CNY 100m':'亿');
  const K=D.kpi, tile=(v,l)=>'<div class="kpi"><b>'+v+'</b><span>'+l+'</span></div>';
  $('#kpis').innerHTML=
    tile('<span style="color:'+RED+'">'+K['加多']+'</span>',t('longCnt'))+tile(K['减多'],t('trimLongCnt'))+
    tile('<span style="color:'+GRN+'">'+K['加空']+'</span>',t('shortCnt'))+tile(K['减空'],t('trimShortCnt'))+
    tile('<span style="color:'+(D.senti>=0?RED:GRN)+'">'+(D.senti>0?'+':'')+D.senti+'%</span>',t('senti'))+
    tile(D.in_play,t('inPlay'))+tile(D.amt_add_long+(lang==='en'?' CNY 100m':'亿'),t('amtLong'))+tile(D.amt_add_short+(lang==='en'?' CNY 100m':'亿'),t('amtShort'));
  $('#foot').textContent=t('dataSource')+': '+sourceText(D.source)+' · '+t('nominal')+' · '+t('desc')+' · WINDRISE';
}

/* ── 多空全景 环形+仪表 ── */
function pano(){
  const K=D.kpi, jd=K['加多']||0,jdm=K['减多']||0,jk=K['加空']||0,jkm=K['减空']||0,senti=D.senti;
  const segs=[[jd,RED],[jdm,'#d98b6b'],[jkm,'#5fa97e'],[jk,GRN]], tot=jd+jdm+jk+jkm||1, C=2*Math.PI*54; let off=0;
  const arcs=segs.map(([v,c])=>{const ln=v/tot*C, el='<circle cx="70" cy="70" r="54" fill="none" stroke="'+c+'" stroke-width="20" stroke-dasharray="'+ln+' '+(C-ln)+'" stroke-dashoffset="'+(-off)+'" transform="rotate(-90 70 70)"/>';off+=ln;return el;}).join('');
  const frac=Math.max(0,Math.min(1,(senti+100)/200)), ang=Math.PI*(1-frac), gx=70+56*Math.cos(ang),gy=70-56*Math.sin(ang), scol=senti>=0?RED:GRN, semi=Math.PI*58;
  $('#pano').innerHTML=
    '<div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">'+
    '<div style="position:relative;width:140px;height:140px"><svg width="140" height="140" viewBox="0 0 140 140">'+arcs+'</svg>'+
    '<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center"><div style="font-size:25px;font-weight:800;font-family:Georgia,serif;color:'+scol+'">'+(senti>0?'+':'')+senti+'%</div><div style="font-size:11px;color:var(--mut)">'+t('senti')+'</div></div></div>'+
    '<svg width="150" height="92" viewBox="0 0 140 92">'+
      '<path d="M12 70 A58 58 0 0 1 128 70" fill="none" stroke="'+GRN+'" stroke-width="9" stroke-dasharray="'+(semi/2).toFixed(1)+' 999"/>'+
      '<path d="M12 70 A58 58 0 0 1 128 70" fill="none" stroke="'+RED+'" stroke-width="9" stroke-dasharray="'+(semi/2).toFixed(1)+' 999" stroke-dashoffset="'+(-semi/2).toFixed(1)+'"/>'+
      '<line x1="70" y1="70" x2="'+gx.toFixed(1)+'" y2="'+gy.toFixed(1)+'" stroke="var(--ink)" stroke-width="3.5" stroke-linecap="round"/><circle cx="70" cy="70" r="5" fill="var(--ink)"/>'+
      '<text x="10" y="88" font-size="9" fill="'+GRN+'">'+t('extremeShort')+'</text><text x="96" y="88" font-size="9" fill="'+RED+'">'+t('extremeLong')+'</text></svg>'+
    '<div class="legend"><div><i style="background:'+RED+'"></i>'+actText('加多')+' <b>'+jd+'</b>　<i style="background:#d98b6b;margin-left:8px"></i>'+actText('减多')+' <b>'+jdm+'</b></div>'+
    '<div><i style="background:'+GRN+'"></i>'+actText('加空')+' <b>'+jk+'</b>　<i style="background:#5fa97e;margin-left:8px"></i>'+actText('减空')+' <b>'+jkm+'</b></div>'+
    '<div style="margin-top:6px;color:var(--mut);font-size:12px">'+t('inPlay')+' '+D.in_play+' · '+t('amtLong')+' '+D.amt_add_long+(lang==='en'?' CNY 100m':'亿')+' · '+t('amtShort')+' '+D.amt_add_short+(lang==='en'?' CNY 100m':'亿')+'</div></div></div>';
}

function brief(){
  const sec=D.sectors.map(s=>[s.name,s.series[s.series.length-1]]).sort((a,b)=>a[1]-b[1]);
  const topA=x=>D.rows.filter(r=>r.act===x).sort((a,b)=>b.amt-a.amt).slice(0,3).map(r=>term(r.name)+'('+amtLabel(r)+')');
  const li=[];
  if(lang==='en'){
    li.push('Institutional tide NAV is <b>'+D.net+' CNY 100m</b>, with a '+(D.chg<0?t('todayFlowOut'):t('todayFlowIn'))+' of <b>'+Math.abs(D.chg)+' CNY 100m</b> today and '+t('senti')+' at <b style="color:'+(D.senti>=0?RED:GRN)+'">'+(D.senti>0?'+':'')+D.senti+'%</b>.');
    if(sec.length)li.push(t('sectorLayer')+': <b style="color:'+GRN+'">'+term(sec[0][0])+'('+sec[0][1]+' CNY 100m)</b> is '+t('mostShort')+', while <b style="color:'+RED+'">'+term(sec[sec.length-1][0])+'('+sec[sec.length-1][1]+' CNY 100m)</b> is '+t('mostLong')+'.');
  }else{
    li.push('机构资金潮汐净值 <b>'+D.net+'亿</b>,今日'+(D.chg<0?t('todayFlowOut'):t('todayFlowIn'))+' <b>'+Math.abs(D.chg)+'亿</b>,情绪偏向 <b style="color:'+(D.senti>=0?RED:GRN)+'">'+(D.senti>0?'+':'')+D.senti+'%</b>。');
    if(sec.length)li.push('板块层面 <b style="color:'+GRN+'">'+term(sec[0][0])+'('+sec[0][1]+'亿)</b> '+t('mostShort')+'、<b style="color:'+RED+'">'+term(sec[sec.length-1][0])+'('+sec[sec.length-1][1]+'亿)</b> '+t('mostLong')+'。');
  }
  const ta=topA('加多'),ts=topA('加空');
  if(ta.length)li.push(t('topLong')+': '+ta.join(lang==='en'?', ':'、')+(lang==='en'?'.':'。'));
  if(ts.length)li.push(t('topShort')+': '+ts.join(lang==='en'?', ':'、')+(lang==='en'?'.':'。'));
  const bull=D.rows.filter(r=>r.act==='加多'&&r.pc!=null&&r.pc<-0.2).map(r=>r.name);
  const bear=D.rows.filter(r=>r.act==='加空'&&r.pc!=null&&r.pc>0.2).map(r=>r.name);
  if(bull.length||bear.length)li.push(t('divSignal')+': '+t('bullList')+' '+((bull.slice(0,3).map(term).join(lang==='en'?', ':'、'))||t('none'))+'; '+t('bearList')+' '+((bear.slice(0,3).map(term).join(lang==='en'?', ':'、'))||t('none'))+(lang==='en'?'.':'。'));
  $('#brief').innerHTML=li.map(x=>'<li>'+x+'</li>').join('');
}

function cohbars(){
  const mx=Math.max(1,...D.cohorts.map(c=>Math.abs(c.flow)));
  const bar=(v,w,col)=>'<div class="ctrack"><div class="cmid"></div><div class="cbar" style="background:'+col+';'+(v>=0?('left:50%;width:'+w+'%'):('right:50%;width:'+w+'%'))+'"></div></div>';
  $('#cohbars').innerHTML=D.cohorts.map((c,ci)=>{
    const v=c.flow,w=Math.abs(v)/mx*46,col=v>=0?RED:GRN,mem=c.members||[];
    let h='<div class="cbrow chead" data-ci="'+ci+'">'+
      '<span class="cn"><i class="carrow" id="ca'+ci+'">'+(mem.length?'▸':'')+'</i>'+term(c.name)+'</span>'+bar(v,w,col)+
      '<span class="cv" style="color:'+col+'">'+(v>=0?'+':'')+v.toFixed(1)+(lang==='en'?' CNY 100m':'亿')+'</span>'+
      (c.series&&c.series.length?'<button class="mbtn" data-t="c" data-ci="'+ci+'">'+t('curve')+'</button>':'')+'</div>';
    if(mem.length){
      const mmx=Math.max(0.01,...mem.map(m=>Math.abs(m.flow)));
      h+='<div class="cmem" id="cm'+ci+'">'+mem.map((m,mi)=>{
        const mv=m.flow,mw=Math.abs(mv)/mmx*46,mc=mv>=0?RED:GRN;
        return '<div class="cbrow sub"><span class="cn2">'+term(m.name)+'</span>'+bar(mv,mw,mc)+
          '<span class="cv" style="color:'+mc+'">'+(mv>=0?'+':'')+mv.toFixed(1)+(lang==='en'?' CNY 100m':'亿')+'</span>'+
          (m.series&&m.series.length?'<button class="mbtn" data-t="m" data-ci="'+ci+'" data-mi="'+mi+'">'+t('curve')+'</button>':'')+'</div>';
      }).join('')+'</div>';
    }
    return h;
  }).join('');
  document.querySelectorAll('#cohbars .chead').forEach(el=>el.onclick=e=>{
    if(e.target.classList.contains('mbtn'))return;
    const ci=el.dataset.ci,box=document.getElementById('cm'+ci);if(!box)return;
    const on=(box.style.display===''||box.style.display==='none');
    box.style.display=on?'block':'none';
    const ar=document.getElementById('ca'+ci);if(ar)ar.style.transform=on?'rotate(90deg)':'';
  });
  document.querySelectorAll('#cohbars .mbtn').forEach(b=>b.onclick=e=>{
    e.stopPropagation();
    const c=D.cohorts[+b.dataset.ci], o=b.dataset.t==='c'?c:c.members[+b.dataset.mi];
    openModal(term(o.name)+' · '+t('tide'));
    lineChart($('#mbody'),o.series,D.dates40,{h:320,fmt:v=>v.toFixed(1)+' '+(lang==='en'?'CNY 100m':'亿')});
  });
}

function backtests(){
  const root=$('#backtests'), groups=(D.backtests&&D.backtests.groups)||[];
  if(!groups.length){root.innerHTML='<div class="muted">'+t('noData')+'</div>';return;}
  const pct=v=>(v*100).toFixed(1)+'%', signed=v=>(v>=0?'+':'')+(v*100).toFixed(1)+'%';
  root.innerHTML=groups.map((g,gi)=>{const b=g.best,rev=b.mode==='反向',mode=rev?t('reverse'):t('forward');
    const strength=(Math.abs(b.ic)>=.15&&b.win_rate>=.58)?t('evidenceStrong'):(Math.abs(b.ic)>=.08||b.win_rate>=.55)?t('evidenceMedium'):t('evidenceWeak');
    const active=Math.abs(b.latest_z||0)>=((D.backtests.method&&D.backtests.method.signal_threshold)||.5),bull=active&&((b.latest_z>0)!==rev),bias=!active?t('noActiveSignal'):(bull?t('bullishWatch'):t('bearishWatch'));
    let reading=lang==='en'
      ? term(g.cohort)+' performs best in '+term(b.sector)+' on a '+b.horizon+'-day '+mode.toLowerCase()+' reading. Historical hit rate is <b>'+pct(b.win_rate)+'</b> with correlation <b>'+signed(b.ic)+'</b>; evidence is <b>'+strength.toLowerCase()+'</b>.'
      : term(g.cohort)+'在'+term(b.sector)+'板块的'+b.horizon+'日'+mode+'解读相对最好，历史胜率 <b>'+pct(b.win_rate)+'</b>、相关度 <b>'+signed(b.ic)+'</b>；当前证据强度为<b>'+strength+'</b>。';
    reading+=' '+t('currentBias')+': <b style="color:'+(active?(bull?RED:GRN):'var(--mut)')+'">'+bias+'</b> (z '+(b.latest_z>=0?'+':'')+b.latest_z+').';
    const charts=(b.contracts||[]).map((c,ci)=>'<div class="btchart"><div class="btcname"><span>'+term(c.name)+'</span><small>'+t('latestSignal')+' z '+(c.latest_z==null?'—':((c.latest_z>=0?'+':'')+c.latest_z))+'</small></div><div id="bt_'+gi+'_'+ci+'"></div><div class="btlegend"><span><i style="background:'+DARK+'"></i>'+t('seatNet')+'</span><span><i style="background:'+GOLD+'"></i>'+t('priceTrend')+'</span></div></div>').join('');
    return '<section class="btgroup"><div class="bthead"><span class="btname">'+term(g.cohort)+'</span><span class="btbadge">'+t('bestSector')+' · '+term(b.sector)+'</span><span class="btbadge '+(rev?'rev':'')+'">'+mode+'</span><span class="btbadge">'+t('evidence')+' · '+strength+'</span><div class="btmetrics">'+
      '<span class="btmetric">'+t('corr')+'<b>'+signed(b.ic)+'</b></span><span class="btmetric">'+t('winRate')+'<b>'+pct(b.win_rate)+'</b></span><span class="btmetric">'+t('horizon')+'<b>'+b.horizon+'D</b></span><span class="btmetric">'+t('samples')+'<b>'+b.samples+'</b></span></div></div><div class="btread">'+reading+'</div><div class="btcharts">'+charts+'</div></section>';
  }).join('')+'<div class="btnote">'+t('backtestNote')+'</div>';
  groups.forEach((g,gi)=>(g.best.contracts||[]).forEach((c,ci)=>seatPriceChart(document.getElementById('bt_'+gi+'_'+ci),c)));
}

function heat(){
  const vals=D.sectors.map(s=>s.series[s.series.length-1]), mx=Math.max(1,...vals.map(Math.abs));
  $('#heat').innerHTML=D.sectors.map((s,i)=>{const v=vals[i],day=s.series.length>1?v-s.series[s.series.length-2]:0;
    const a=(0.20+0.80*Math.abs(v)/mx).toFixed(2), bg=v>=0?'rgba(178,58,47,'+a+')':'rgba(23,96,75,'+a+')';
    return '<div class="htile" data-v="'+s.name+'" style="background:'+bg+'" onclick="sectorModal(\''+s.name+'\')">'+
      '<div class="hn">'+term(s.name)+'</div><div class="hv">'+(v>=0?'+':'')+v.toFixed(0)+(lang==='en'?' CNY 100m':'亿')+'</div><div class="hd">'+(lang==='en'?'Day ':'日 ')+(day>=0?'+':'')+day.toFixed(1)+' · '+t('clickCurve')+'</div></div>';}).join('');
}

function boards(){
  const cfg=[['加多',RED],['减多','#c9744f'],['加空',GRN],['减空','#5fa97e']];
  $('#boards').innerHTML=cfg.map(([act,col])=>{
    const g=D.rows.filter(r=>r.act===act).sort((a,b)=>b.amt-a.amt).slice(0,7), mx=Math.max(0.001,...g.map(r=>r.amt)),cnt=D.rows.filter(r=>r.act===act).length;
    const rs=g.map(r=>{const w=Math.max(9,r.amt/mx*100),hot=r.ratio>=50;
      return '<div class="brow"><span class="bn">'+term(r.name)+'</span><span class="bb"><i style="width:'+w+'%;background:'+col+'"></i><span class="ba">'+amtLabel(r)+'</span></span><span class="br" style="'+(hot?'color:'+GOLD+';font-weight:700':'color:var(--mut)')+'">'+r.ratio+'%</span></div>';
    }).join('')||'<div class="muted" style="padding:8px 2px">'+t('none')+'</div>';
    return '<div class="board"><div class="bh" style="color:'+col+'">'+actText(act)+'<small>'+cnt+' '+t('items')+'</small></div>'+rs+'</div>';
  }).join('');
}

/* ── 强度表 ── */
const actTag=(raw,label)=>!raw?'':'<span class="tag '+(raw.indexOf('多')>=0?'jd':'jk')+(raw[0]==='减'?' less':'')+'">'+(label||raw)+'</span>';
function view(){
  let arr=D.rows.filter(r=>(!fact||r.act===fact)&&(!fdir||r.dir===fdir)&&(!q||r.name.indexOf(q)>=0||term(r.name).toLowerCase().indexOf(q.toLowerCase())>=0||term(r.sector||'').toLowerCase().indexOf(q.toLowerCase())>=0));
  const kf={amt:r=>-r.amt,conf:r=>-(r.conf==null?-1:r.conf),ratio:r=>-r.ratio,streak:r=>-Math.abs(r.streak||0)}[sortKey];
  return arr.sort((a,b)=>kf(a)-kf(b));
}
function sparkMini(y){ // 小型只读迷你走势(表格用)
  const n=y.length; if(!n)return''; const lo=Math.min(...y),hi=Math.max(...y),W=120,H=26;
  const X=i=>n<2?W/2:i/(n-1)*W, Y=v=>H-(v-lo)/((hi-lo)||1)*H;
  const col=y[y.length-1]>=0?RED:GRN;
  return '<svg viewBox="0 0 '+W+' '+H+'" style="width:120px;height:26px"><polyline points="'+y.map((v,i)=>X(i).toFixed(0)+','+Y(v).toFixed(1)).join(' ')+'" fill="none" stroke="'+col+'" stroke-width="1.4"/></svg>';
}
function render(){
  const arr=view();
  $('#tb').innerHTML=arr.length?arr.map(r=>{
    const hot=r.ratio>=50, conf=r.conf==null?'<span class="muted">—</span>':
      '<div class="confcell"><span style="color:'+(r.dir==='利多'?GRN:RED)+';font-weight:700;font-size:12px">'+actText(r.dir)+' '+r.conf+'</span><div class="confbar"><i style="width:'+r.conf+'%;background:'+(r.dir==='利多'?GRN:RED)+'"></i></div></div>';
    const hb=r.hb==null?'—':((r.hb>=0?'+':'')+r.hb+'%'), hbc=r.hb==null?'var(--mut)':(r.hb>=0?RED:GRN);
    const strk=r.streak?(lang==='en'?((r.streak>0?'Added ':'Reduced ')+Math.abs(r.streak)+'d'):((r.streak>0?'连加':'连减')+Math.abs(r.streak)+'日')):'—';
    return '<tr class="main" data-n="'+r.name+'"><td class="nm2">'+term(r.name)+'</td><td class="muted">'+(r.sector?term(r.sector):'—')+'</td>'+
      '<td>'+actTag(r.act,actText(r.act))+'</td><td class="amt">'+amtLabel(r)+'</td><td class="'+(hot?'rel-hot':'muted')+'">'+r.ratio+'%</td>'+
      '<td style="color:'+hbc+';font-size:12px">'+hb+'</td><td>'+conf+'</td><td class="muted" style="font-size:12px">'+strk+'</td>'+
      '<td>'+sparkMini(r.series)+'</td></tr>'+(opened===r.name?detail(r):'');
  }).join(''):'<tr><td colspan="9" class="empty">'+t('noMatch')+'</td></tr>';
  document.querySelectorAll('#tb tr.main').forEach(tr=>tr.onclick=()=>{opened=opened===tr.dataset.n?null:tr.dataset.n;render();
    if(opened===tr.dataset.n){const r=D.rows.find(x=>x.name===opened);const host=document.getElementById('dch_'+cssid(opened));if(host)lineChart(host,r.series,D.dates60.slice(D.dates60.length-r.series.length),{h:150,fmt:v=>Math.round(v).toLocaleString()+' '+(lang==='en'?'lots':'手')});}});
}
function cssid(s){return s.replace(/[^a-zA-Z0-9]/g,c=>c.charCodeAt(0));}
function detail(r){
  const items=[[t('currentNet'),(r.net>=0?t('netLong')+' ':t('netShort')+' ')+Math.abs(r.net).toLocaleString()+' '+(lang==='en'?'lots':'手')],[t('todayAction'),(r.dnet>=0?'+':'')+r.dnet.toLocaleString()+' '+(lang==='en'?'lots':'手')],
    [t('todayPx'),r.px!=null?r.px:'—'],[t('todayChg'),r.pc!=null?((r.pc>=0?'+':'')+r.pc+'%'):'—'],
    [t('resonance'),r.conf!=null?(actText(r.dir)+' '+r.conf+' · '+tierText(r.tier)):'—']];
  return '<tr class="detail"><td colspan="9"><div class="dgrid">'+items.map(x=>'<span class="di"><span>'+x[0]+'</span>　<b>'+x[1]+'</b></span>').join('')+'</div>'+
    '<div class="chartbox" style="cursor:crosshair" id="dch_'+cssid(r.name)+'"></div><div class="chartcap"><span>'+term(r.name)+' · '+(lang==='en'?'Institutional nominal net position over last 60 days (lots)':'近60日机构名义净持仓(手)')+'</span><span>'+t('hoverDaily')+'</span></div></td></tr>';
}

function persradar(){
  const pers=D.rows.filter(r=>r.streak).sort((a,b)=>Math.abs(b.streak)-Math.abs(a.streak)).slice(0,10), pmx=Math.max(1,...pers.map(r=>Math.abs(r.streak)));
  const prows=pers.map(r=>{const up=r.streak>0,col=up?RED:GRN,w=Math.max(10,Math.abs(r.streak)/pmx*100);
    return '<div class="prow"><span class="pn">'+term(r.name)+'</span><span style="flex:1;height:16px;background:var(--soft);border-radius:5px;overflow:hidden"><i style="display:block;height:100%;width:'+w+'%;background:'+col+';border-radius:5px"></i></span>'+
      '<span style="width:86px;text-align:right;color:'+col+';font-weight:600;flex:none">'+(lang==='en'?((up?'Added ':'Reduced ')+Math.abs(r.streak)+'d'):((up?'连加':'连减')+Math.abs(r.streak)+'日'))+'</span><span class="muted" style="width:96px;text-align:right;flex:none;font-size:12px">'+(r.net>=0?t('netLong'):t('netShort'))+' '+Math.abs(r.net).toLocaleString()+'</span></div>';
  }).join('')||'<div class="muted">—</div>';
  const bull=D.rows.filter(r=>r.act==='加多'&&r.pc!=null&&r.pc<-0.2).sort((a,b)=>a.pc-b.pc);
  const bear=D.rows.filter(r=>r.act==='加空'&&r.pc!=null&&r.pc>0.2).sort((a,b)=>b.pc-a.pc);
  const chips=(arr,col,bg)=>arr.slice(0,6).map(r=>'<span class="chip2" style="color:'+col+';background:'+bg+'">'+term(r.name)+' '+(r.pc>=0?'+':'')+r.pc+'%</span>').join('')||'<span class="muted">—</span>';
  $('#persradar').innerHTML=
    '<div class="cardbox"><div class="ch">'+t('persistRank')+'</div>'+prows+'</div>'+
    '<div class="cardbox"><div class="ch">'+t('divRadar')+'</div><div style="font-size:12px;color:'+RED+';font-weight:700;margin:6px 0 4px">'+t('instLong')+'</div>'+chips(bull,RED,'#f7e6e1')+
    '<div style="font-size:12px;color:'+GRN+';font-weight:700;margin:12px 0 4px">'+t('instShort')+'</div>'+chips(bear,GRN,'#e2f0e8')+'</div>';
}

function reson(){
  const BO=['有色','黑色','化工','能源','农产品','贵金属'],byS={};
  D.rows.filter(r=>r.dir&&r.conf!=null).forEach(r=>{(byS[r.sector]=byS[r.sector]||[]).push(r);});
  let html='';
  BO.forEach(s=>{const g=(byS[s]||[]).sort((a,b)=>b.conf-a.conf);if(!g.length)return;
    const cards=g.map(r=>{const col=r.dir==='利多'?GRN:RED, gold=(r.tier==='很高'||r.tier==='高');
      return '<div class="rcard" style="border-left:5px solid '+col+'"><div class="rn">'+term(r.name)+'<span class="rtag" style="background:'+col+'">'+actText(r.dir)+'</span></div><div class="rs">'+t('tierDot')+' <b style="color:'+(gold?GOLD:'var(--mut)')+'">'+r.conf+' · '+tierText(r.tier)+'</b> · '+actText(r.act)+' '+t('price')+(r.pc!=null?((r.pc>=0?'+':'')+r.pc+'%'):'')+'</div></div>';}).join('');
    html+='<div style="margin-bottom:12px"><div style="font-weight:700;color:var(--dark);border-left:5px solid var(--gold);padding-left:9px;margin:8px 0 7px">'+term(s)+' <span class="muted">'+g.length+'</span></div><div class="reson">'+cards+'</div></div>';});
  $('#reson').innerHTML=html||'<div class="muted">'+t('emptyReson')+'</div>';
}

/* filters */
document.querySelectorAll('.fact').forEach(b=>b.onclick=()=>{fact=b.dataset.v;document.querySelectorAll('.fact').forEach(x=>x.setAttribute('data-on',x===b?'1':''));render();});
document.querySelectorAll('.fdir').forEach(b=>b.onclick=()=>{fdir=b.dataset.v;document.querySelectorAll('.fdir').forEach(x=>x.setAttribute('data-on',x===b?'1':''));render();});
$('#q').addEventListener('input',e=>{q=e.target.value.trim();render();});
$('#sort').addEventListener('change',e=>{sortKey=e.target.value;render();});
document.querySelectorAll('thead th[data-k]').forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(['amt','conf','ratio','streak'].includes(k)){sortKey=k;$('#sort').value=k;render();}});
document.querySelector('.fact[data-v=""]').setAttribute('data-on','1');
document.querySelector('.fdir[data-v=""]').setAttribute('data-on','1');
document.querySelectorAll('.langsw button').forEach(b=>b.onclick=()=>{lang=b.dataset.lang;renderAll();});

function renderAll(){
  header();
  lineChart($('#tidechart'),D.tide,D.dates40,{h:150,fmt:v=>v.toFixed(1)+' '+(lang==='en'?'CNY 100m':'亿')});
  pano();brief();cohbars();backtests();heat();boards();render();persradar();scatter($('#quadbox'));reson();
}
renderAll();
</script></body></html>
"""


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else find_latest()
    if not src.is_absolute():
        src = ROOT / src
    date = re.search(r"(\d{8})", src.name).group(1)
    data = json.loads(src.read_text(encoding="utf-8"))
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False)) \
                   .replace("__DATE__", data.get("date") or f"{date[:4]}-{date[4:6]}-{date[6:]}")
    out = src.parent / f"期货资金潮汐_{date}_交互.html"
    out.write_text(html, encoding="utf-8")
    print(f"完成:{len(data['rows'])}品种 · tide {len(data['tide'])}点 · 板块 {len(data['sectors'])} · {out.name}({out.stat().st_size//1024}KB)")


if __name__ == "__main__":
    main()
