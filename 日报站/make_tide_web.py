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
  .foot{margin-top:24px;border-top:1px solid var(--line);padding-top:10px;font-size:11.5px;color:var(--mut)}
  .empty{padding:30px;text-align:center;color:var(--mut)}
  #modal{position:fixed;inset:0;background:rgba(20,26,23,.78);display:none;align-items:center;justify-content:center;z-index:50;padding:24px}
  #modal .mbox{background:#fff;border-radius:14px;padding:18px 20px;max-width:900px;width:100%}
  #modal .mh{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
  #modal .mx{cursor:pointer;color:var(--mut);font-size:20px}
</style></head><body>
<div class="wrap">
  <div class="mast"><div class="brand">WINDRISE</div><h1>期货资金潮汐 · 交互终端</h1><div class="asof">__DATE__ · 盘后主力席位资金视图</div></div>

  <div class="hero">
    <div class="netcard"><div class="lb">机构资金潮汐净值 · 名义净持仓(亿)</div><b id="netv"></b><div class="sub" id="netsub"></div></div>
    <div class="kpis" id="kpis"></div>
  </div>

  <h2 class="sec-h">机构资金潮汐净值 · 40日走势 <small>鼠标移到线上看每日数值 · 点图放大</small></h2>
  <div class="chartbox zoom" id="tidebox" onclick="enlarge('tide')"><div id="tidechart"></div></div>

  <h2 class="sec-h">多空动作全景 <small>加多/减多/加空/减空分布 · 情绪偏向</small></h2>
  <div class="pano" id="pano"></div>

  <h2 class="sec-h">今日速览 <small>基于当日主力席位数据自动生成</small></h2>
  <div class="brief"><ul id="brief"></ul></div>

  <h2 class="sec-h">各类资金今日净流向 <small>机构/外资/杭州/中财 · 名义(亿) · 悬停看数</small></h2>
  <div class="cohbars" id="cohbars"></div>

  <h2 class="sec-h">板块资金热力 <small>机构名义净持仓 · 红多绿空 · 点块看40日曲线 / 点击筛选</small></h2>
  <div class="heat" id="heat"></div>

  <h2 class="sec-h">四类动作榜 <small>各动作按名义金额排 · 相对幅度≥50%(金色)=激进</small></h2>
  <div class="boards" id="boards"></div>

  <h2 class="sec-h">资金强度排行榜 <small>可筛选/排序/点行看该品种60日机构净持仓曲线</small></h2>
  <div class="controls">
    <input id="q" type="text" placeholder="搜品种，如 碳酸锂">
    <button class="pill fact" data-v="">全部</button><button class="pill fact" data-v="加多">加多</button>
    <button class="pill fact" data-v="减多">减多</button><button class="pill fact" data-v="加空">加空</button>
    <button class="pill fact" data-v="减空">减空</button>
    <span class="lab">共振</span><button class="pill fdir" data-v="">全部</button>
    <button class="pill fdir" data-v="利多">利多</button><button class="pill fdir" data-v="利空">利空</button>
    <span class="lab">排序</span><select id="sort">
      <option value="amt">名义金额</option><option value="conf">共振可信度</option>
      <option value="ratio">相对幅度</option><option value="streak">持续天数</option></select>
  </div>
  <table><thead><tr><th data-k="name">品种</th><th data-k="sector">板块</th><th data-k="act">动作</th>
    <th data-k="amt">名义金额</th><th data-k="ratio">相对</th><th data-k="hb">环比</th>
    <th data-k="conf">共振</th><th data-k="streak">持续</th><th>近60日</th></tr></thead>
    <tbody id="tb"></tbody></table>

  <h2 class="sec-h">资金持续性榜 · 背离雷达 <small>连续同向天数 / 资金与价格逆向</small></h2>
  <div class="cols2" id="persradar"></div>

  <h2 class="sec-h">价格 × 持仓象限 <small>横=当日价格% 纵=机构资金流向强度 · 悬停看品种</small></h2>
  <div class="chartbox" id="quadbox" style="cursor:default"></div>

  <h2 class="sec-h">资金动能共振榜 · 按板块 <small>机构方向与10日趋势同向 · 可信度据样本外回测校准</small></h2>
  <div id="reson"></div>

  <div class="foot" id="foot"></div>
</div>
<div id="modal"><div class="mbox"><div class="mh"><b id="mtitle"></b><span class="mx" onclick="closeModal()">✕</span></div><div id="mbody"></div></div></div>
<script>
const D = __DATA__;
const $ = s => document.querySelector(s);
const RED="#b23a2f",GRN="#17604b",GOLD="#b98b2f",DARK="#0f4638";
let fact="",fdir="",q="",sortKey="amt",opened=null;

/* ── 通用可交互折线图(悬停十字线+数值气泡, 零轴双色渐变面积) ── */
function lineChart(host, y, dates, opt){
  opt=opt||{}; const H=opt.h||130, W=1000, n=y.length;
  if(!n){host.innerHTML='<div class="muted" style="padding:20px">无数据</div>';return;}
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
    lab(W*0.8,20,'量价齐升·强多',RED)+lab(W*0.16,20,'逆势吸筹','#2d5f8a')+
    lab(W*0.8,H-8,'冲高派发',GOLD)+lab(W*0.16,H-8,'杀跌离场',GRN);
  pts.forEach((p,i)=>{const c=(p.z||0)>=0?RED:GRN;
    s+='<circle class="dot" data-i="'+i+'" cx="'+X(p.pc).toFixed(1)+'" cy="'+Y(p.z||0).toFixed(1)+'" r="6" fill="'+c+'" fill-opacity=".7" stroke="#fff" stroke-width="1"/>';});
  s+='<text x="'+ (W-6) +'" y="'+(Y(0)-6)+'" text-anchor="end" font-size="11" fill="#8a8676">价格涨跌 % →</text></svg><div class="tip" style="display:none"></div>';
  host.innerHTML=s;
  const tip=host.querySelector('.tip');
  host.querySelectorAll('.dot').forEach(d=>{
    d.addEventListener('mouseenter',()=>{const p=pts[+d.dataset.i]; d.setAttribute('r',9);
      tip.style.display='block';
      tip.innerHTML='<b>'+p.name+'</b>　'+(p.act||'')+'<br>价 '+(p.pc>=0?'+':'')+p.pc+'% · 资金强度 '+(p.z>=0?'+':'')+p.z;
      const r=host.getBoundingClientRect(),dr=d.getBoundingClientRect();
      tip.style.left=Math.min(r.width-140,(dr.left-r.left)+8)+'px'; tip.style.top=((dr.top-r.top)-40)+'px';});
    d.addEventListener('mouseleave',()=>{d.setAttribute('r',6);tip.style.display='none';});
  });
}

/* ── 图表放大弹窗 ── */
function enlarge(which){
  if(which==='tide'){ openModal('机构资金潮汐净值 · 40日走势',''); lineChart($('#mbody'),D.tide,D.dates40,{h:340,fmt:v=>v.toFixed(1)+' 亿'}); }
}
function sectorModal(name){
  const s=D.sectors.find(x=>x.name===name); if(!s)return;
  openModal(name+' · 机构名义净持仓 40日走势','');
  lineChart($('#mbody'),s.series,D.dates40,{h:320,fmt:v=>v.toFixed(1)+' 亿'});
}
function openModal(t){ $('#mtitle').textContent=t; $('#modal').style.display='flex'; }
function closeModal(){ $('#modal').style.display='none'; }
$('#modal').addEventListener('click',e=>{if(e.target.id==='modal')closeModal();});

/* ── 头部 / KPI ── */
function header(){
  $('#netv').textContent=(D.net>0?'+':'')+D.net;
  $('#netv').style.color=D.net>=0?'#f0a89c':'#9fd8b4';
  $('#netsub').innerHTML='今日变动 <b>'+(D.chg>0?'+':'')+D.chg+'亿</b> · 40日区间 '+D.range40[0]+' ~ '+D.range40[1]+' 亿';
  const K=D.kpi, tile=(v,l)=>'<div class="kpi"><b>'+v+'</b><span>'+l+'</span></div>';
  $('#kpis').innerHTML=
    tile('<span style="color:'+RED+'">'+K['加多']+'</span>','加多品种')+tile(K['减多'],'减多品种')+
    tile('<span style="color:'+GRN+'">'+K['加空']+'</span>','加空品种')+tile(K['减空'],'减空品种')+
    tile('<span style="color:'+(D.senti>=0?RED:GRN)+'">'+(D.senti>0?'+':'')+D.senti+'%</span>','情绪偏向')+
    tile(D.in_play,'在场品种')+tile(D.amt_add_long+'亿','加多总额')+tile(D.amt_add_short+'亿','加空总额');
  $('#foot').textContent='数据源: '+D.source+' · 名义=持仓×合约乘数×收盘价 · 描述性研究,不构成投资建议 · WINDRISE';
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
    '<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center"><div style="font-size:25px;font-weight:800;font-family:Georgia,serif;color:'+scol+'">'+(senti>0?'+':'')+senti+'%</div><div style="font-size:11px;color:var(--mut)">情绪偏向</div></div></div>'+
    '<svg width="150" height="92" viewBox="0 0 140 92">'+
      '<path d="M12 70 A58 58 0 0 1 128 70" fill="none" stroke="'+GRN+'" stroke-width="9" stroke-dasharray="'+(semi/2).toFixed(1)+' 999"/>'+
      '<path d="M12 70 A58 58 0 0 1 128 70" fill="none" stroke="'+RED+'" stroke-width="9" stroke-dasharray="'+(semi/2).toFixed(1)+' 999" stroke-dashoffset="'+(-semi/2).toFixed(1)+'"/>'+
      '<line x1="70" y1="70" x2="'+gx.toFixed(1)+'" y2="'+gy.toFixed(1)+'" stroke="var(--ink)" stroke-width="3.5" stroke-linecap="round"/><circle cx="70" cy="70" r="5" fill="var(--ink)"/>'+
      '<text x="10" y="88" font-size="9" fill="'+GRN+'">← 极空</text><text x="96" y="88" font-size="9" fill="'+RED+'">极多 →</text></svg>'+
    '<div class="legend"><div><i style="background:'+RED+'"></i>加多 <b>'+jd+'</b>　<i style="background:#d98b6b;margin-left:8px"></i>减多 <b>'+jdm+'</b></div>'+
    '<div><i style="background:'+GRN+'"></i>加空 <b>'+jk+'</b>　<i style="background:#5fa97e;margin-left:8px"></i>减空 <b>'+jkm+'</b></div>'+
    '<div style="margin-top:6px;color:var(--mut);font-size:12px">在场 '+D.in_play+' 品种 · 加多总额 '+D.amt_add_long+'亿 · 加空总额 '+D.amt_add_short+'亿</div></div></div>';
}

function brief(){
  const sec=D.sectors.map(s=>[s.name,s.series[s.series.length-1]]).sort((a,b)=>a[1]-b[1]);
  const topA=x=>D.rows.filter(r=>r.act===x).sort((a,b)=>b.amt-a.amt).slice(0,3).map(r=>r.name+'('+r.amt_txt+')');
  const li=[];
  li.push('机构资金潮汐净值 <b>'+D.net+'亿</b>,今日'+(D.chg<0?'净流出':'净流入')+' <b>'+Math.abs(D.chg)+'亿</b>,情绪偏向 <b style="color:'+(D.senti>=0?RED:GRN)+'">'+(D.senti>0?'+':'')+D.senti+'%</b>。');
  if(sec.length)li.push('板块层面 <b style="color:'+GRN+'">'+sec[0][0]+'('+sec[0][1]+'亿)</b> 资金最空、<b style="color:'+RED+'">'+sec[sec.length-1][0]+'('+sec[sec.length-1][1]+'亿)</b> 最多。');
  const ta=topA('加多'),ts=topA('加空');
  if(ta.length)li.push('加多力度居前:'+ta.join('、')+'。');
  if(ts.length)li.push('加空力度居前:'+ts.join('、')+'。');
  const bull=D.rows.filter(r=>r.act==='加多'&&r.pc!=null&&r.pc<-0.2).map(r=>r.name);
  const bear=D.rows.filter(r=>r.act==='加空'&&r.pc!=null&&r.pc>0.2).map(r=>r.name);
  if(bull.length||bear.length)li.push('背离信号:逆势吸筹 '+(bull.slice(0,3).join('、')||'无')+';逆势沽空 '+(bear.slice(0,3).join('、')||'无')+'。');
  $('#brief').innerHTML=li.map(x=>'<li>'+x+'</li>').join('');
}

function cohbars(){
  const mx=Math.max(1,...D.cohorts.map(c=>Math.abs(c.flow)));
  $('#cohbars').innerHTML=D.cohorts.map(c=>{const v=c.flow,w=Math.abs(v)/mx*46,col=v>=0?RED:GRN;
    return '<div class="cbrow"><span class="cn">'+c.name+'</span><div class="ctrack"><div class="cmid"></div>'+
      '<div class="cbar" style="background:'+col+';'+(v>=0?('left:50%;width:'+w+'%'):('right:50%;width:'+w+'%'))+'"></div></div>'+
      '<span class="cv" style="color:'+col+'">'+(v>=0?'+':'')+v.toFixed(1)+'亿</span></div>';}).join('');
}

function heat(){
  const vals=D.sectors.map(s=>s.series[s.series.length-1]), mx=Math.max(1,...vals.map(Math.abs));
  $('#heat').innerHTML=D.sectors.map((s,i)=>{const v=vals[i],day=s.series.length>1?v-s.series[s.series.length-2]:0;
    const a=(0.20+0.80*Math.abs(v)/mx).toFixed(2), bg=v>=0?'rgba(178,58,47,'+a+')':'rgba(23,96,75,'+a+')';
    return '<div class="htile" data-v="'+s.name+'" style="background:'+bg+'" onclick="sectorModal(\''+s.name+'\')">'+
      '<div class="hn">'+s.name+'</div><div class="hv">'+(v>=0?'+':'')+v.toFixed(0)+'亿</div><div class="hd">日 '+(day>=0?'+':'')+day.toFixed(1)+' · 点看曲线</div></div>';}).join('');
}

function boards(){
  const cfg=[['加多',RED],['减多','#c9744f'],['加空',GRN],['减空','#5fa97e']];
  $('#boards').innerHTML=cfg.map(([act,col])=>{
    const g=D.rows.filter(r=>r.act===act).sort((a,b)=>b.amt-a.amt).slice(0,7), mx=Math.max(0.001,...g.map(r=>r.amt)),cnt=D.rows.filter(r=>r.act===act).length;
    const rs=g.map(r=>{const w=Math.max(9,r.amt/mx*100),hot=r.ratio>=50;
      return '<div class="brow"><span class="bn">'+r.name+'</span><span class="bb"><i style="width:'+w+'%;background:'+col+'"></i><span class="ba">'+r.amt_txt+'</span></span><span class="br" style="'+(hot?'color:'+GOLD+';font-weight:700':'color:var(--mut)')+'">'+r.ratio+'%</span></div>';
    }).join('')||'<div class="muted" style="padding:8px 2px">无</div>';
    return '<div class="board"><div class="bh" style="color:'+col+'">'+act+'<small>'+cnt+'个</small></div>'+rs+'</div>';
  }).join('');
}

/* ── 强度表 ── */
const actTag=a=>!a?'':'<span class="tag '+(a.indexOf('多')>=0?'jd':'jk')+(a[0]==='减'?' less':'')+'">'+a+'</span>';
function view(){
  let arr=D.rows.filter(r=>(!fact||r.act===fact)&&(!fdir||r.dir===fdir)&&(!q||r.name.indexOf(q)>=0));
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
      '<div class="confcell"><span style="color:'+(r.dir==='利多'?GRN:RED)+';font-weight:700;font-size:12px">'+r.dir+' '+r.conf+'</span><div class="confbar"><i style="width:'+r.conf+'%;background:'+(r.dir==='利多'?GRN:RED)+'"></i></div></div>';
    const hb=r.hb==null?'—':((r.hb>=0?'+':'')+r.hb+'%'), hbc=r.hb==null?'var(--mut)':(r.hb>=0?RED:GRN);
    const strk=r.streak?((r.streak>0?'连加':'连减')+Math.abs(r.streak)+'日'):'—';
    return '<tr class="main" data-n="'+r.name+'"><td class="nm2">'+r.name+'</td><td class="muted">'+(r.sector||'—')+'</td>'+
      '<td>'+actTag(r.act)+'</td><td class="amt">'+r.amt_txt+'</td><td class="'+(hot?'rel-hot':'muted')+'">'+r.ratio+'%</td>'+
      '<td style="color:'+hbc+';font-size:12px">'+hb+'</td><td>'+conf+'</td><td class="muted" style="font-size:12px">'+strk+'</td>'+
      '<td>'+sparkMini(r.series)+'</td></tr>'+(opened===r.name?detail(r):'');
  }).join(''):'<tr><td colspan="9" class="empty">没有匹配的品种</td></tr>';
  document.querySelectorAll('#tb tr.main').forEach(tr=>tr.onclick=()=>{opened=opened===tr.dataset.n?null:tr.dataset.n;render();
    if(opened===tr.dataset.n){const r=D.rows.find(x=>x.name===opened);const host=document.getElementById('dch_'+cssid(opened));if(host)lineChart(host,r.series,D.dates60.slice(D.dates60.length-r.series.length),{h:150,fmt:v=>Math.round(v).toLocaleString()+' 手'});}});
}
function cssid(s){return s.replace(/[^a-zA-Z0-9]/g,c=>c.charCodeAt(0));}
function detail(r){
  const items=[['当前净持仓',(r.net>=0?'净多 ':'净空 ')+Math.abs(r.net).toLocaleString()+' 手'],['今日动作',(r.dnet>=0?'+':'')+r.dnet.toLocaleString()+' 手'],
    ['当日价格',r.px!=null?r.px:'—'],['当日涨跌',r.pc!=null?((r.pc>=0?'+':'')+r.pc+'%'):'—'],
    ['共振',r.conf!=null?(r.dir+' '+r.conf+'·'+r.tier):'—']];
  return '<tr class="detail"><td colspan="9"><div class="dgrid">'+items.map(x=>'<span class="di"><span>'+x[0]+'</span>　<b>'+x[1]+'</b></span>').join('')+'</div>'+
    '<div class="chartbox" style="cursor:crosshair" id="dch_'+cssid(r.name)+'"></div><div class="chartcap"><span>'+r.name+' · 近60日机构名义净持仓(手)</span><span>悬停看每日</span></div></td></tr>';
}

function persradar(){
  const pers=D.rows.filter(r=>r.streak).sort((a,b)=>Math.abs(b.streak)-Math.abs(a.streak)).slice(0,10), pmx=Math.max(1,...pers.map(r=>Math.abs(r.streak)));
  const prows=pers.map(r=>{const up=r.streak>0,col=up?RED:GRN,w=Math.max(10,Math.abs(r.streak)/pmx*100);
    return '<div class="prow"><span class="pn">'+r.name+'</span><span style="flex:1;height:16px;background:var(--soft);border-radius:5px;overflow:hidden"><i style="display:block;height:100%;width:'+w+'%;background:'+col+';border-radius:5px"></i></span>'+
      '<span style="width:86px;text-align:right;color:'+col+';font-weight:600;flex:none">'+(up?'连加':'连减')+Math.abs(r.streak)+'日</span><span class="muted" style="width:96px;text-align:right;flex:none;font-size:12px">'+(r.net>=0?'净多':'净空')+' '+Math.abs(r.net).toLocaleString()+'</span></div>';
  }).join('')||'<div class="muted">—</div>';
  const bull=D.rows.filter(r=>r.act==='加多'&&r.pc!=null&&r.pc<-0.2).sort((a,b)=>a.pc-b.pc);
  const bear=D.rows.filter(r=>r.act==='加空'&&r.pc!=null&&r.pc>0.2).sort((a,b)=>b.pc-a.pc);
  const chips=(arr,col,bg)=>arr.slice(0,6).map(r=>'<span class="chip2" style="color:'+col+';background:'+bg+'">'+r.name+' '+(r.pc>=0?'+':'')+r.pc+'%</span>').join('')||'<span class="muted">—</span>';
  $('#persradar').innerHTML=
    '<div class="cardbox"><div class="ch">资金持续性榜 · 机构连续同向</div>'+prows+'</div>'+
    '<div class="cardbox"><div class="ch">资金背离雷达</div><div style="font-size:12px;color:'+RED+';font-weight:700;margin:6px 0 4px">逆势吸筹 · 加多而价跌</div>'+chips(bull,RED,'#f7e6e1')+
    '<div style="font-size:12px;color:'+GRN+';font-weight:700;margin:12px 0 4px">逆势沽空 · 加空而价涨</div>'+chips(bear,GRN,'#e2f0e8')+'</div>';
}

function reson(){
  const BO=['有色','黑色','化工','能源','农产品','贵金属'],byS={};
  D.rows.filter(r=>r.dir&&r.conf!=null).forEach(r=>{(byS[r.sector]=byS[r.sector]||[]).push(r);});
  let html='';
  BO.forEach(s=>{const g=(byS[s]||[]).sort((a,b)=>b.conf-a.conf);if(!g.length)return;
    const cards=g.map(r=>{const col=r.dir==='利多'?GRN:RED, gold=(r.tier==='很高'||r.tier==='高');
      return '<div class="rcard" style="border-left:5px solid '+col+'"><div class="rn">'+r.name+'<span class="rtag" style="background:'+col+'">'+r.dir+'</span></div><div class="rs">可信度 <b style="color:'+(gold?GOLD:'var(--mut)')+'">'+r.conf+'·'+r.tier+'</b> · '+r.act+' 价'+(r.pc!=null?((r.pc>=0?'+':'')+r.pc+'%'):'')+'</div></div>';}).join('');
    html+='<div style="margin-bottom:12px"><div style="font-weight:700;color:var(--dark);border-left:5px solid var(--gold);padding-left:9px;margin:8px 0 7px">'+s+' <span class="muted">'+g.length+'</span></div><div class="reson">'+cards+'</div></div>';});
  $('#reson').innerHTML=html||'<div class="muted">今日无高一致性共振品种</div>';
}

/* filters */
document.querySelectorAll('.fact').forEach(b=>b.onclick=()=>{fact=b.dataset.v;document.querySelectorAll('.fact').forEach(x=>x.setAttribute('data-on',x===b?'1':''));render();});
document.querySelectorAll('.fdir').forEach(b=>b.onclick=()=>{fdir=b.dataset.v;document.querySelectorAll('.fdir').forEach(x=>x.setAttribute('data-on',x===b?'1':''));render();});
$('#q').addEventListener('input',e=>{q=e.target.value.trim();render();});
$('#sort').addEventListener('change',e=>{sortKey=e.target.value;render();});
document.querySelectorAll('thead th[data-k]').forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(['amt','conf','ratio','streak'].includes(k)){sortKey=k;$('#sort').value=k;render();}});
document.querySelector('.fact[data-v=""]').setAttribute('data-on','1');
document.querySelector('.fdir[data-v=""]').setAttribute('data-on','1');

header();
lineChart($('#tidechart'),D.tide,D.dates40,{h:150,fmt:v=>v.toFixed(1)+' 亿'});
pano();brief();cohbars();heat();boards();render();persradar();scatter($('#quadbox'));reson();
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
