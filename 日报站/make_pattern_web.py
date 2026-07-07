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
  <div class="mast"><div class="brand">WINDRISE</div><h1>期货形态 · 交互终端</h1><div class="asof">截至 __DATE__</div></div>
  <div class="intro">对 15 个重点品种取<b>小时K</b>, 枢轴几何法识别 <b>三角 / 矩形 / 楔形 / 旗形</b>(已删头肩顶/双顶底), 仅保留<b>高置信度</b>近端主形态,
  给出方向、颈线触发位、目标、止损。另按<b>等权法编制 商品综合指数 / 工业品指数</b>(base100)一并识别并置顶。点K线图可放大。</div>
  <div class="kpis" id="kpis"></div>
  <div class="controls">
    <span class="lab">方向</span>
    <button class="pill fb" data-v="">全部</button><button class="pill fb" data-v="bullish">偏多</button>
    <button class="pill fb" data-v="bearish">偏空</button>
    <span class="lab">状态</span>
    <button class="pill fs" data-v="">全部</button><button class="pill fs" data-v="act">可操作</button>
    <button class="pill fs" data-v="done">已兑现</button>
    <span class="lab">排序</span>
    <button class="pill fo" data-v="conf">可信度</button><button class="pill fo" data-v="fresh">最近完成</button>
  </div>
  <div class="grid" id="grid"></div>
  <div class="nonebox"><b style="font-size:13px">无明确形态</b>　<span id="nones"></span></div>
  <div class="foot" id="foot"></div>
</div>
<div id="lightbox"><img alt=""></div>
<script>
const D = __DATA__;
const $=s=>document.querySelector(s);
let fb="",fs="",fo="conf";
const RED="#b23a2f",GRN="#17604b",GOLD="#b98b2f";
function gg(x){if(x==null)return"—";return Math.abs(x)>=100?Math.round(x).toLocaleString():x.toFixed(2);}
function kpis(){
  const rs=D.results, act=rs.filter(r=>!r.exhausted&&r.bias!=="neutral").length;
  const bull=rs.filter(r=>r.bias==="bullish").length, bear=rs.filter(r=>r.bias==="bearish").length;
  const tile=(v,l,c)=>'<div class="kpi"><b style="color:'+(c||"var(--ink)")+'">'+v+'</b><span>'+l+'</span></div>';
  $('#kpis').innerHTML=tile(act,'可操作')+tile(rs.length,'识别到形态')+tile(bull,'偏多',RED)+tile(bear,'偏空',GRN)
    +tile(D.none.length,'无明确形态')+tile(D.errs.length,'取数跳过',D.errs.length?RED:undefined);
}
function view(){
  let a=D.results.filter(r=>(!fb||r.bias===fb)&&(!fs||(fs==="act"?(!r.exhausted&&r.bias!=="neutral"):r.exhausted)));
  if(fo==="conf")a=a.slice().sort((x,y)=>((y.is_index?1:0)-(x.is_index?1:0))||y.confidence-x.confidence);
  else a=a.slice().sort((x,y)=>x.bars_since-y.bars_since);
  return a;
}
function render(){
  const a=view();
  $('#grid').innerHTML=a.length?a.map(r=>{
    const col=r.bias==="bullish"?RED:r.bias==="bearish"?GRN:GOLD;
    return '<div class="card">'+
      '<div class="ch"><span class="nm">'+r.name+(r.is_index?' <span class="idx">等权指数·base100</span>':'')+'</span>'+
      '<span class="conf">可信度 '+r.confidence.toFixed(2)+' · '+r.tier+'</span></div>'+
      '<div><span class="pat" style="color:'+col+'">'+r.pattern_cn+' · '+r.bias_cn+'</span></div>'+
      '<div class="st">'+r.state+'　'+r.fresh+' · 形态完成 '+(r.end_ts||'').slice(0,16)+'</div>'+
      '<img src="data:image/png;base64,'+r.img+'" onclick="lb(this.src)">'+
      '<table class="lv"><tr><td class="k">现价</td><td><b>'+gg(r.last_close)+'</b></td>'+
      '<td class="k">颈线/触发</td><td><b style="color:#e08e0b">'+gg(r.trigger)+'</b></td></tr>'+
      '<tr><td class="k">目标</td><td><b style="color:'+GRN+'">'+gg(r.target)+'</b></td>'+
      '<td class="k">止损</td><td><b style="color:'+RED+'">'+gg(r.stop)+'</b></td></tr></table></div>';
  }).join(''):'<div class="empty">没有匹配的形态</div>';
}
function lb(src){$('#lightbox img').src=src;$('#lightbox').style.display='flex';}
$('#lightbox').onclick=()=>$('#lightbox').style.display='none';
document.querySelectorAll('.fb').forEach(b=>b.onclick=()=>{fb=b.dataset.v;document.querySelectorAll('.fb').forEach(x=>x.setAttribute('data-on',x===b?'1':''));render();});
document.querySelectorAll('.fs').forEach(b=>b.onclick=()=>{fs=b.dataset.v;document.querySelectorAll('.fs').forEach(x=>x.setAttribute('data-on',x===b?'1':''));render();});
document.querySelectorAll('.fo').forEach(b=>b.onclick=()=>{fo=b.dataset.v;document.querySelectorAll('.fo').forEach(x=>x.setAttribute('data-on',x===b?'1':''));render();});
document.querySelector('.fb[data-v=""]').setAttribute('data-on','1');
document.querySelector('.fs[data-v=""]').setAttribute('data-on','1');
document.querySelector('.fo[data-v="conf"]').setAttribute('data-on','1');
$('#nones').innerHTML=D.none.map(n=>'<span class="chipn">'+n+'</span>').join('')||'<span class="chipn">无</span>';
$('#foot').textContent='数据源: 15品种=新浪财经(akshare 小时K 主力连续) / 指数底层='+D.idx_src+
  ' · 指数编制: 成分主力连续小时K 各自以首根收盘=100 归一后等权平均(OHLC同法), 量能=成分均值 · 引擎: 枢轴几何法(ATR-zigzag+上下轨拟合) · 描述性研究, 不构成投资建议 · WINDRISE'+
  (D.errs.length?('　跳过: '+D.errs.map(e=>e[0]).join('、')):'');
kpis();render();
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
