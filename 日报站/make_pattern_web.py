#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
期货形态日报 → 交互网页生成器(v2, 2026-07-07 起读 JSON)

数据源改为本地形态引擎的 automation/local/output/hourly_pattern_report.json
(不再用 pdftotext/pdfimages 解析 PDF——服务器重装后渲染器已换, 且 JSON 无损;
旧解析版备份在 make_pattern_web.py.bak_pdf解析版)。
生成自包含交互网页: 方向/状态筛选、可信度排序、点K线图放大。

用法:
    python3 make_pattern_web.py                    # 读默认 json, 按 asof 日期落到 日报/<日期>/
    python3 make_pattern_web.py <json路径>
输出: 日报/<YYYYMMDD>/期货形态_<YYYYMMDD>.html
"""
import json
import re
import sys
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
ROOT = SITE_DIR.parent
DEFAULT_JSON = ROOT / "automation/local/output/hourly_pattern_report.json"

TEMPLATE = r"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>期货形态 · 交互终端 __DATE__</title>
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
  .langsw{display:inline-flex;align-items:center;gap:4px;border:1px solid var(--line);border-radius:999px;background:var(--card);padding:3px}
  .langsw button{border:0;background:transparent;color:var(--mut);font-size:12px;font-weight:700;padding:5px 10px;border-radius:999px;cursor:pointer}
  .langsw button[data-on="1"]{background:var(--dark);color:#fff}
  .intro{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:14px 0;font-size:13px;color:#6e6656;line-height:1.7}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin:12px 0}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 10px;text-align:center}
  .kpi b{display:block;font-size:19px;font-family:Georgia,serif}
  .kpi span{font-size:11px;color:var(--mut)}
  .controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:8px 0 14px}
  .pill{border:1px solid var(--line);background:var(--card);border-radius:18px;padding:6px 13px;font-size:12.5px;cursor:pointer}
  .pill[data-on="1"]{background:var(--dark);border-color:var(--dark);color:#fff}
  .lab{font-size:11.5px;color:var(--mut);margin-left:4px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:13px 15px}
  .ch{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
  .nm{font-size:16px;font-weight:800}
  .idx{font-size:10px;background:var(--soft);border-radius:5px;padding:1px 7px;color:#6e6656;font-weight:600}
  .pat{font-weight:700;font-size:13px}
  .conf{font-size:12px;color:var(--gold);font-weight:700;white-space:nowrap}
  .st{font-size:11.5px;color:var(--mut);margin:3px 0 7px}
  .card img{width:100%;border:1px solid var(--line);border-radius:9px;background:#fff;cursor:zoom-in}
  table.lv{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:7px}
  table.lv td{padding:2px 4px}
  table.lv td.k{color:var(--mut);font-size:11px;width:25%}
  .nonebox{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin-top:16px}
  .chipn{display:inline-block;font-size:12.5px;border:1px solid var(--line);border-radius:9px;padding:3px 11px;margin:3px 5px 3px 0;color:var(--mut)}
  .foot{margin-top:24px;border-top:1px solid var(--line);padding-top:10px;font-size:11.5px;color:var(--mut);line-height:1.7}
  .empty{padding:36px;text-align:center;color:var(--mut)}
  #lightbox{position:fixed;inset:0;background:rgba(20,26,23,.86);display:none;align-items:center;justify-content:center;cursor:zoom-out;z-index:50;padding:30px}
  #lightbox img{max-width:min(1000px,96vw);width:100%;background:#fff;border-radius:10px;padding:12px}
</style></head><body>
<div class="wrap">
  <div class="mast"><div class="brand">WINDRISE</div><h1 id="title"></h1><div class="asof" id="asof"></div><div class="langsw"><button type="button" data-lang="zh">中</button><button type="button" data-lang="en">EN</button></div></div>
  <div class="intro" id="intro"></div>
  <div class="kpis" id="kpis"></div>
  <div class="controls">
    <span class="lab" id="labDir"></span>
    <button class="pill fb" data-v="" data-i18n="all"></button><button class="pill fb" data-v="bullish" data-i18n="bullish"></button>
    <button class="pill fb" data-v="bearish" data-i18n="bearish"></button>
    <span class="lab" id="labState"></span>
    <button class="pill fs" data-v="" data-i18n="all"></button><button class="pill fs" data-v="act" data-i18n="actionable"></button>
    <button class="pill fs" data-v="done" data-i18n="played"></button>
    <span class="lab" id="labSort"></span>
    <button class="pill fo" data-v="conf" data-i18n="confidence"></button><button class="pill fo" data-v="fresh" data-i18n="freshness"></button>
  </div>
  <div class="grid" id="grid"></div>
  <div class="nonebox"><b style="font-size:13px" id="noneTitle"></b>　<span id="nones"></span></div>
  <div class="foot" id="foot"></div>
</div>
<div id="lightbox"><img alt=""></div>
<script>
const D = __DATA__;
const $=s=>document.querySelector(s);
let fb="",fs="",fo="conf";
let lang=(new URLSearchParams(location.search).get('lang')||localStorage.getItem('windrise_lang')||'zh');
const RED="#b23a2f",GRN="#17604b",GOLD="#b98b2f";
const UI={
  zh:{pageTitle:'期货形态 · 交互终端',intro:'对 15 个重点品种取<b>小时K</b>, 枢轴几何法识别 <b>三角 / 矩形 / 楔形 / 旗形</b>(已删头肩顶/双顶底), 仅保留<b>高置信度</b>近端主形态, 给出方向、颈线触发位、目标、止损。另按<b>等权法编制 商品综合指数 / 工业品指数</b>(base100)一并识别并置顶。点K线图可放大。',asof:'截至 __DATE__',dir:'方向',state:'状态',sort:'排序',all:'全部',bullish:'偏多',bearish:'偏空',actionable:'可操作',played:'已兑现',confidence:'可信度',freshness:'最近完成',noneTitle:'无明确形态',actionableKpi:'可操作',detected:'识别到形态',bullishKpi:'偏多',bearishKpi:'偏空',noneKpi:'无明确形态',skipped:'取数跳过',noMatch:'没有匹配的形态',indexTag:'等权指数·base100',confidencePrefix:'可信度 ',stateCompleted:'形态完成 ',price:'现价',trigger:'颈线/触发',target:'目标',stop:'止损',dataSource:'数据源',foot:'指数编制: 成分主力连续小时K 各自以首根收盘=100 归一后等权平均(OHLC同法), 量能=成分均值 · 引擎: 枢轴几何法(ATR-zigzag+上下轨拟合) · 描述性研究, 不构成投资建议 · WINDRISE',skip:'跳过',noneFallback:'无'},
  en:{pageTitle:'Futures Pattern Monitor · Interactive Terminal',intro:'Hourly candles for 15 focus contracts are scanned with a pivot-geometry engine to detect <b>triangles / rectangles / wedges / flags</b> (head-and-shoulders and double tops/bottoms removed). Only the nearest <b>high-confidence</b> primary pattern is kept, with bias, trigger, target and stop. An <b>equal-weight Commodity Composite / Industrials Index</b> (base100) is built alongside the single-contract scan. Click any chart to enlarge.',asof:'As of __DATE__',dir:'Bias',state:'Status',sort:'Sort',all:'All',bullish:'Bullish',bearish:'Bearish',actionable:'Actionable',played:'Played Out',confidence:'Confidence',freshness:'Recency',noneTitle:'No Clear Pattern',actionableKpi:'Actionable',detected:'Detected Patterns',bullishKpi:'Bullish',bearishKpi:'Bearish',noneKpi:'No Pattern',skipped:'Skipped',noMatch:'No matching patterns',indexTag:'Equal-Weighted Index · base100',confidencePrefix:'Confidence ',stateCompleted:'Pattern completed ',price:'Last',trigger:'Trigger',target:'Target',stop:'Stop',dataSource:'Source',foot:'Index construction: each component main continuous hourly contract is normalized to the first close = 100, then equal-weighted (same for OHLC), with volume averaged across constituents · Engine: pivot geometry (ATR zigzag + channel fitting) · Descriptive research only, not investment advice · WINDRISE',skip:'Skipped',noneFallback:'None'}
};
const TERM_EN={"黄金":"Gold","白银":"Silver","铜":"Copper","铝":"Aluminum","锌":"Zinc","铅":"Lead","镍":"Nickel","锡":"Tin","多晶硅":"Polysilicon","甲醇":"Methanol","原油":"Crude Oil","碳酸锂":"Lithium Carbonate","棕榈油":"Palm Oil","商品综合指数":"Commodity Composite Index","工业品指数":"Industrials Index","螺纹钢":"Rebar","热卷":"Hot-Rolled Coil","铁矿石":"Iron Ore","焦煤":"Coking Coal","焦炭":"Coke","玻璃":"Glass","纯碱":"Soda Ash","烧碱":"Caustic Soda","尿素":"Urea","沥青":"Bitumen","燃油":"Fuel Oil","液化气":"LPG","PX":"PX","PTA":"PTA","乙二醇":"MEG","苯乙烯":"Styrene","PVC":"PVC","PP":"Polypropylene","塑料":"LLDPE","20号胶":"TSR 20","天然橡胶":"Natural Rubber","纸浆":"Pulp","豆一":"Soybean No.1","豆二":"Soybean No.2","豆粕":"Soybean Meal","豆油":"Soybean Oil","菜粕":"Rapeseed Meal","菜油":"Rapeseed Oil","玉米":"Corn","淀粉":"Corn Starch","苹果":"Apple","红枣":"Red Dates","花生":"Peanuts","棉花":"Cotton","白糖":"Sugar","生猪":"Live Hogs","鸡蛋":"Eggs","工业硅":"Industrial Silicon","不锈钢":"Stainless Steel","短纤":"Polyester Staple Fiber","硅铁":"Ferrosilicon","锰硅":"Silicomanganese","氧化铝":"Alumina"};
const PATTERN_EN={"对称三角":"Symmetrical Triangle","下降三角":"Descending Triangle","上升三角":"Ascending Triangle","空头三角旗":"Bearish Pennant","多头三角旗":"Bullish Pennant","矩形":"Rectangle","上升楔形":"Rising Wedge","下降楔形":"Falling Wedge","楔形":"Wedge","旗形":"Flag"};
function gg(x){if(x==null)return"—";return Math.abs(x)>=100?Math.round(x).toLocaleString():x.toFixed(2);}
function tx(k){return (UI[lang]||UI.zh)[k]||k}
function term(v){return lang==='en'?(TERM_EN[v]||v):v}
function biasLabel(b){return lang==='en'?(b==='bullish'?tx('bullish'):b==='bearish'?tx('bearish'):'Neutral'):(b==='bullish'?'偏多':b==='bearish'?'偏空':'中性')}
function patternLabel(v){return lang==='en'?(PATTERN_EN[v]||v):v}
function tierLabel(v){if(lang==='zh')return v;return {"很高":"Very High","高":"High","中":"Medium","低":"Low","很低":"Very Low"}[v]||v}
function stateLabel(v){if(lang==='zh')return v;return (v||"").replace("形成中·待突破","Forming · waiting for breakout").replace("形成中·待破位","Forming · waiting for breakdown").replace("已破颈线·目标未到(可跟)","Neckline broken · target pending").replace("已突破·目标未到(可跟)","Breakout confirmed · target pending").replace("已兑现","Played out")}
function freshLabel(v){if(lang==='zh')return v;if(v==='近端')return 'Recent';var m=(v||'').match(/偏历史\((\d+)根前\)/);return m?('Historical ('+m[1]+' bars ago)'):v}
function syncUi(){
  localStorage.setItem('windrise_lang',lang);
  document.documentElement.lang=lang==='en'?'en':'zh-CN';
  document.title=tx('pageTitle')+' '+D.asof;
  $('#title').textContent=tx('pageTitle');
  $('#asof').textContent=tx('asof').replace('__DATE__',D.asof);
  $('#intro').innerHTML=tx('intro');
  $('#labDir').textContent=tx('dir');
  $('#labState').textContent=tx('state');
  $('#labSort').textContent=tx('sort');
  $('#noneTitle').textContent=tx('noneTitle');
  document.querySelectorAll('[data-i18n]').forEach(function(el){el.textContent=tx(el.dataset.i18n)});
  document.querySelectorAll('.langsw button').forEach(function(b){b.setAttribute('data-on',b.dataset.lang===lang?'1':'')});
}
function kpis(){
  const rs=D.results, act=rs.filter(r=>!r.exhausted&&r.bias!=="neutral").length;
  const bull=rs.filter(r=>r.bias==="bullish").length, bear=rs.filter(r=>r.bias==="bearish").length;
  const tile=(v,l,c)=>'<div class="kpi"><b style="color:'+(c||"var(--ink)")+'">'+v+'</b><span>'+l+'</span></div>';
  $('#kpis').innerHTML=tile(act,tx('actionableKpi'))+tile(rs.length,tx('detected'))+tile(bull,tx('bullishKpi'),RED)+tile(bear,tx('bearishKpi'),GRN)+tile(D.none.length,tx('noneKpi'))+tile(D.errs.length,tx('skipped'),D.errs.length?RED:undefined);
}
function view(){
  let a=D.results.filter(r=>(!fb||r.bias===fb)&&(!fs||(fs==="act"?(!r.exhausted&&r.bias!=="neutral"):r.exhausted)));
  if(fo==="conf")a=a.slice().sort((x,y)=>((y.is_index?1:0)-(x.is_index?1:0))||y.confidence-x.confidence);
  else a=a.slice().sort((x,y)=>x.bars_since-y.bars_since);
  return a;
}
function render(){
  const a=view();
  $('#grid').innerHTML=a.length?a.map(function(r){
    const col=r.bias==="bullish"?RED:r.bias==="bearish"?GRN:GOLD;
    return '<div class="card">'+
      '<div class="ch"><span class="nm">'+term(r.name)+(r.is_index?' <span class="idx">'+tx('indexTag')+'</span>':'')+'</span>'+
      '<span class="conf">'+tx('confidencePrefix')+r.confidence.toFixed(2)+' · '+tierLabel(r.tier)+'</span></div>'+
      '<div><span class="pat" style="color:'+col+'">'+patternLabel(r.pattern_cn)+' · '+biasLabel(r.bias)+'</span></div>'+
      '<div class="st">'+stateLabel(r.state)+'　'+freshLabel(r.fresh)+' · '+tx('stateCompleted')+(r.end_ts||'').slice(0,16)+'</div>'+
      '<img src="data:image/png;base64,'+r.img+'" onclick="lb(this.src)">'+
      '<table class="lv"><tr><td class="k">'+tx('price')+'</td><td><b>'+gg(r.last_close)+'</b></td>'+
      '<td class="k">'+tx('trigger')+'</td><td><b style="color:#e08e0b">'+gg(r.trigger)+'</b></td></tr>'+
      '<tr><td class="k">'+tx('target')+'</td><td><b style="color:'+GRN+'">'+gg(r.target)+'</b></td>'+
      '<td class="k">'+tx('stop')+'</td><td><b style="color:'+RED+'">'+gg(r.stop)+'</b></td></tr></table></div>';
  }).join(''):'<div class="empty">'+tx('noMatch')+'</div>';
}
function lb(src){$('#lightbox img').src=src;$('#lightbox').style.display='flex';}
$('#lightbox').onclick=()=>$('#lightbox').style.display='none';
document.querySelectorAll('.fb').forEach(function(b){b.onclick=function(){fb=b.dataset.v;document.querySelectorAll('.fb').forEach(function(x){x.setAttribute('data-on',x===b?'1':'')});render();}});
document.querySelectorAll('.fs').forEach(function(b){b.onclick=function(){fs=b.dataset.v;document.querySelectorAll('.fs').forEach(function(x){x.setAttribute('data-on',x===b?'1':'')});render();}});
document.querySelectorAll('.fo').forEach(function(b){b.onclick=function(){fo=b.dataset.v;document.querySelectorAll('.fo').forEach(function(x){x.setAttribute('data-on',x===b?'1':'' )});render();}});
document.querySelector('.fb[data-v=""]').setAttribute('data-on','1');
document.querySelector('.fs[data-v=""]').setAttribute('data-on','1');
document.querySelector('.fo[data-v="conf"]').setAttribute('data-on','1');
function renderShell(){
  syncUi();
  $('#nones').innerHTML=D.none.map(function(n){return '<span class="chipn">'+term(n)+'</span>'}).join('')||('<span class="chipn">'+tx('noneFallback')+'</span>');
  $('#foot').textContent=tx('dataSource')+': 15 contracts = Sina Finance (akshare main continuous hourly bars) / index base = '+(lang==='en'?term(D.idx_src):D.idx_src)+' · '+tx('foot')+(D.errs.length?('　'+tx('skip')+': '+D.errs.map(function(e){return term(e[0])}).join(lang==='en'?', ':'、')):'');
}
document.querySelectorAll('.langsw button').forEach(function(b){b.onclick=function(){lang=b.dataset.lang;renderAll();}});
function renderAll(){renderShell();kpis();render();}
renderAll();
</script></body></html>
"""


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JSON
    if not src.is_absolute():
        src = ROOT / src
    data = json.loads(src.read_text(encoding="utf-8"))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", data.get("asof", ""))
    ymd = "".join(m.groups()) if m else "00000000"
    outdir = ROOT / "日报" / ymd
    outdir.mkdir(parents=True, exist_ok=True)
    html = (TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
                    .replace("__DATE__", data.get("asof", "")))
    out = outdir / f"期货形态_{ymd}.html"
    out.write_text(html, encoding="utf-8")
    print(f"完成: {len(data['results'])}形态/{len(data['none'])}无 → {out}({out.stat().st_size//1024}KB)")


if __name__ == "__main__":
    main()
