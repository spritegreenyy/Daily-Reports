#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""期货资金潮汐 · 竖版长图(海报/信息图版) — 复用 tide_report 的数据与指标, 输出高分辨率 PNG 长图。
更"可视化": 潮汐净值 hero + 多空环形图 + 情绪温度计 + 各类资金分流条 + 板块热力图 + 净买卖 TOP 渐变条 + 背离标签。
"""
import sys, math, base64, io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
import tide_report as T   # 复用: ROWS / DATA / TARGET / notional_series / cohort_flow / sector_series / amt_fmt / SEC_ORDER

ROWS, DATA, DATE = T.ROWS, T.DATA, T.TARGET
BG = "#FBF9F3"; INK = "#26241F"; MUTE = "#8A8172"; LINE = "#ECE4D3"
RED = "#C0392B"; RSOFT = "#D9836B"; GRN = "#1E8449"; GSOFT = "#5FA97E"; GOLD = "#B0842B"; ACC = "#2D5F8A"
OUT = Path(__file__).parent / "output"

n = {a: sum(1 for m in ROWS if m["act"] == a) for a in ("加多", "减多", "加空", "减空")}
tot = len(ROWS)
tot_lots = sum(abs(m["dnet"]) for m in ROWS)
amt_add_long = sum(m["amt"] for m in ROWS if m["act"] == "加多") / 1e8
amt_add_short = sum(m["amt"] for m in ROWS if m["act"] == "加空") / 1e8
senti = (n["加多"] - n["加空"]) / max(1, tot) * 100
tide = T.notional_series("机构", 40)
tlvl = float(tide[-1]); tdl = float(tide[-1] - tide[-2]); thi = float(np.max(tide)); tlo = float(np.min(tide))


def donut(segs, r=120, w=34):
    """segs=[(value,color)]; 返回 SVG 圆环。"""
    C = 2 * math.pi * r; total = sum(v for v, _ in segs) or 1; off = 0; arcs = ""
    for v, col in segs:
        ln = v / total * C
        arcs += (f'<circle cx="150" cy="150" r="{r}" fill="none" stroke="{col}" stroke-width="{w}" '
                 f'stroke-dasharray="{ln:.2f} {C-ln:.2f}" stroke-dashoffset="{-off:.2f}" transform="rotate(-90 150 150)"/>')
        off += ln
    return arcs


def gauge(val, lo=-100, hi=100):
    """情绪半圆仪表, val∈[lo,hi]; 返回 SVG。"""
    frac = (val - lo) / (hi - lo); frac = max(0, min(1, frac))
    ang = math.pi * (1 - frac)  # 左=极空 右=极多
    x = 150 + 118 * math.cos(ang); y = 150 - 118 * math.sin(ang)
    return (f'<path d="M20 150 A130 130 0 0 1 280 150" fill="none" stroke="{GRN}" stroke-width="16" stroke-linecap="round"/>'
            f'<path d="M150 150 L{x:.1f} {y:.1f}" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>'
            f'<circle cx="150" cy="150" r="9" fill="{INK}"/>')


# 各类资金分流(机构/外资/杭州/中财/散户)
cohorts = [(c, T.cohort_flow(c)) for c in ["机构", "外资", "杭州", "中财", "散户"]]
cohorts = [(c, v) for c, v in cohorts if v is not None]
cmax = max((abs(v) for _, v in cohorts), default=1)
cohort_bars = ""
for c, v in cohorts:
    col = RED if v >= 0 else GRN; wpc = abs(v) / cmax * 46
    left = f'<div class="cbwrap"><div class="cbar" style="width:{wpc if v<0 else 0}%;background:{GRN};margin-left:auto"></div></div>'
    right = f'<div class="cbwrap"><div class="cbar" style="width:{wpc if v>=0 else 0}%;background:{RED}"></div></div>'
    cohort_bars += (f'<div class="crow"><div class="clab">{c}</div>{left}'
                    f'<div class="cval" style="color:{col}">{v:+.1f}亿</div>{right}</div>')

# 板块热力
sec_tiles = ""
sd = []
for sec in T.SEC_ORDER:
    ss = T.sector_series(sec, 40)
    if ss is not None:
        sd.append((sec, float(ss[-1])))
smax = max((abs(v) for _, v in sd), default=1)
for sec, v in sd:
    a = 0.16 + 0.84 * abs(v) / smax
    col = f"rgba(192,57,43,{a:.2f})" if v >= 0 else f"rgba(30,132,73,{a:.2f})"
    tc = "#fff" if a > 0.5 else INK
    sec_tiles += f'<div class="stile" style="background:{col};color:{tc}"><div class="sn">{sec}</div><div class="sv">{v:+.0f}亿</div></div>'

# 四类动作榜(加多/减多/加空/减空) — 各自独立成表, 不合并成买卖两栏(避免"卖空=加多"的口径分歧)
def act_table_long(act, col, tip):
    grp = sorted([m for m in ROWS if m["act"] == act], key=lambda m: -m["amt"])[:7]
    mx = max((m["amt"] for m in grp), default=1); rows = ""
    for m in grp:
        w = m["amt"] / mx * 100
        rows += (f'<div class="trow"><div class="tv">{m["disp"]}</div>'
                 f'<div class="tbwrap"><div class="tbar" style="width:{max(w,7):.0f}%;background:linear-gradient(90deg,{col}bb,{col})"></div>'
                 f'<span class="tamt">{T.amt_fmt(m["amt"])}</span></div>'
                 f'<div class="trat" style="{("color:"+GOLD+";font-weight:800") if m["ratio"]>=50 else "color:"+MUTE}">{min(m["ratio"],999):.0f}%</div></div>')
    cnt = sum(1 for m in ROWS if m["act"] == act)
    return (f'<div class="topcard"><div class="toph" style="color:{col}">{act}<span>{cnt}个 · {tip}</span></div>'
            f'{rows or "<div class=none style=padding:12px>无</div>"}</div>')


# 资金持续性榜(机构净持仓连续同向天数)
pers = sorted(ROWS, key=lambda m: -abs(m["streak"]))[:10]
pmax = max((abs(m["streak"]) for m in pers), default=1); pers_rows = ""
for m in pers:
    col = RED if m["streak"] > 0 else GRN; w = abs(m["streak"]) / pmax * 100
    pers_rows += (f'<div class="trow"><div class="tv">{m["disp"]}</div>'
                  f'<div class="tbwrap"><div class="tbar" style="width:{max(w,8):.0f}%;background:{col}"></div>'
                  f'<span class="tamt">{"连加" if m["streak"]>0 else "连减"}{abs(m["streak"])}日</span></div>'
                  f'<div class="trat" style="color:{MUTE};width:120px">{"净多" if m["net"]>=0 else "净空"} {abs(m["net"]):,.0f}</div></div>')

# 资金动能共振榜 · 按板块(机构方向+10日趋势同向, 可信度评分)
reson = [(m, T.score(m)) for m in ROWS]; reson = [(m, cs) for m, cs in reson if cs]
bysec = {}
for m, cs in reson:
    bysec.setdefault(m["sector"], []).append((m, cs))
reson_html = ""
for sec in T.SEC_ORDER:
    g = sorted(bysec.get(sec, []), key=lambda x: -x[1][2])
    if not g:
        continue
    cards = ""
    for m, (dirtxt, col, s, tier) in g:
        tc = RED if dirtxt == "利多" else GRN
        cards += (f'<div class="rcard" style="border-left:6px solid {tc}"><div class="rcn">{m["disp"]}'
                  f'<span class="rtag" style="background:{tc}">{dirtxt}</span></div>'
                  f'<div class="rcs">可信度 <b style="color:{GOLD if tier in ("很高","高") else MUTE}">{s}·{tier}</b></div>'
                  f'<div class="rcm">{m["act"]} · {("价"+format((m["pc"] or 0),"+.1f")+"%")}</div></div>')
    reson_html += f'<div class="rsec"><div class="rsh">{sec} <span>{len(g)}</span></div><div class="rgrid">{cards}</div></div>'

# 背离标签
div_bull = sorted([m for m in ROWS if m["act"] == "加多" and (m["pc"] or 0) < -0.2], key=lambda m: m["pc"])[:5]
div_bear = sorted([m for m in ROWS if m["act"] == "加空" and (m["pc"] or 0) > 0.2], key=lambda m: -m["pc"])[:5]
bull_chips = "".join(f'<span class="chip cb">{m["disp"]} <b>{(m["pc"] or 0):+.1f}%</b></span>' for m in div_bull) or '<span class=none>—</span>'
bear_chips = "".join(f'<span class="chip cs">{m["disp"]} <b>{(m["pc"] or 0):+.1f}%</b></span>' for m in div_bear) or '<span class=none>—</span>'

# 今日速览(自动语句)
bull_sec = max(sd, key=lambda x: x[1]) if sd else None
bear_sec = min(sd, key=lambda x: x[1]) if sd else None
t_al = sorted([m for m in ROWS if m["act"] == "加多"], key=lambda m: -m["amt"])[:3]
t_as = sorted([m for m in ROWS if m["act"] == "加空"], key=lambda m: -m["amt"])[:3]
brief = []
brief.append(f'机构资金潮汐净值 <b style="color:{RED if tlvl>=0 else GRN}">{tlvl:+.0f}亿</b>,今日{"净流出" if tdl<0 else "净流入"} <b>{abs(tdl):.1f}亿</b>,整体情绪偏向 <b style="color:{RED if senti>=0 else GRN}">{senti:+.0f}%</b>(加多率−加空率)。')
if bear_sec and bull_sec:
    brief.append(f'板块层面 <b style="color:{GRN}">{bear_sec[0]}({bear_sec[1]:+.0f}亿)</b> 资金最空、<b style="color:{RED}">{bull_sec[0]}({bull_sec[1]:+.0f}亿)</b> 最多。')
if t_al:
    brief.append(f'加多力度居前:{"、".join(m["disp"]+"("+T.amt_fmt(m["amt"])+")" for m in t_al)}。')
if t_as:
    brief.append(f'加空力度居前:{"、".join(m["disp"]+"("+T.amt_fmt(m["amt"])+")" for m in t_as)}。')
if div_bull or div_bear:
    b1 = "、".join(m["disp"] for m in div_bull[:3]); b2 = "、".join(m["disp"] for m in div_bear[:3])
    brief.append(f'背离信号:逆势吸筹 {b1 or "无"};逆势沽空 {b2 or "无"}。')
brief_html = "".join(f'<li>{x}</li>' for x in brief)

dseg = [(n["加多"], RED), (n["减多"], RSOFT), (n["减空"], GSOFT), (n["加空"], GRN)]

HTML = f"""<!DOCTYPE html><html lang=zh-CN><head><meta charset=UTF-8><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{background:{BG}}}
body{{width:1080px;font-family:'Noto Sans CJK SC',sans-serif;color:{INK}}}
.wrap{{padding:0 0 40px;background:{BG}}}
.hero{{background:linear-gradient(135deg,#2B2822,#3E3830 60%,#4A4235);color:#F5EFE2;padding:44px 54px 40px;position:relative;overflow:hidden}}
.hero::after{{content:'';position:absolute;right:-60px;top:-60px;width:340px;height:340px;border-radius:50%;background:rgba(176,132,43,.14)}}
.brand{{font-family:Georgia,serif;letter-spacing:5px;font-size:19px;color:#CDBd94}}
.hdate{{position:absolute;right:54px;top:48px;color:#B7AE98;font-family:Georgia,serif;font-size:19px}}
.hv{{font-family:Georgia,serif;font-size:96px;font-weight:800;line-height:1;margin-top:14px}}
.hv span{{font-size:34px;margin-left:8px;opacity:.85}}
.hl{{font-size:20px;color:#CDBd94;margin-top:22px;letter-spacing:1px}}
.hsub{{font-size:20px;color:#D8CFB9;margin-top:12px}}
.hbadge{{display:inline-block;margin-top:16px;padding:7px 20px;border-radius:30px;font-size:22px;font-weight:800}}
.sec{{padding:30px 54px 4px}}
.h2{{font-size:27px;font-weight:800;margin-bottom:18px;display:flex;align-items:center;gap:12px}}
.h2::before{{content:'';width:8px;height:28px;background:{GOLD};border-radius:3px}}
.h2 small{{font-size:16px;color:{MUTE};font-weight:500}}
.topgrid{{display:flex;gap:26px;align-items:center}}
.donutbox{{text-align:center;position:relative;width:300px;flex:none}}
.dcenter{{position:absolute;top:0;left:0;width:300px;height:300px;display:flex;flex-direction:column;justify-content:center;align-items:center}}
.dc1{{font-size:52px;font-weight:800;font-family:Georgia,serif}} .dc2{{font-size:17px;color:{MUTE}}}
.kpis{{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.kpi{{border-radius:18px;padding:20px 24px;color:#fff}}
.kl{{font-size:19px;opacity:.92}} .kv{{font-size:52px;font-weight:800;font-family:Georgia,serif;line-height:1.05}} .ks{{font-size:16px;opacity:.9;margin-top:2px}}
.gaugebox{{width:300px;flex:none;text-align:center}}
.gv{{font-size:46px;font-weight:800;font-family:Georgia,serif;margin-top:-30px}}
.crow{{display:flex;align-items:center;gap:14px;margin:14px 0}}
.clab{{width:64px;font-size:23px;font-weight:800}}
.cbwrap{{flex:1;height:30px;display:flex}} .cbar{{height:30px;border-radius:7px}}
.cval{{width:120px;text-align:center;font-size:23px;font-weight:800;font-family:Georgia,serif}}
.heat{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}
.stile{{border-radius:16px;padding:26px 22px}} .sn{{font-size:24px;font-weight:800}} .sv{{font-size:40px;font-weight:800;font-family:Georgia,serif;margin-top:6px}}
.twocol{{display:flex;gap:26px}}
.topcard{{flex:1;background:#fff;border:1px solid {LINE};border-radius:18px;padding:22px 26px}}
.toph{{font-size:24px;font-weight:800;margin-bottom:14px;display:flex;justify-content:space-between}} .toph span{{color:{MUTE};font-weight:600}}
.trow{{display:flex;align-items:center;gap:12px;margin:12px 0}}
.tv{{width:76px;font-size:21px;font-weight:700}}
.tbwrap{{flex:1;background:#F2ECDD;border-radius:8px;height:32px;position:relative;overflow:hidden}}
.tbar{{height:32px;border-radius:8px}}
.tamt{{position:absolute;right:12px;top:5px;font-size:18px;font-weight:800;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.35)}}
.trat{{width:66px;text-align:right;font-size:19px}}
.chip{{display:inline-block;font-size:21px;padding:7px 16px;border-radius:12px;margin:6px 8px 6px 0;font-weight:700}}
.cb{{background:#F7E6E1;color:{RED}}} .cs{{background:#E2F0E8;color:{GRN}}} .none{{color:{MUTE}}}
.divbox{{background:#fff;border:1px solid {LINE};border-radius:18px;padding:20px 26px;margin-bottom:16px}}
.divh{{font-size:21px;font-weight:800;margin-bottom:10px}}
.fourgrid{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}
.defnote{{background:#F3EEE0;border-radius:12px;padding:14px 20px;font-size:16px;color:#6E6656;margin-bottom:18px;line-height:1.6}}
.defnote b{{color:{INK}}}
.rsec{{margin-bottom:16px}} .rsh{{font-size:21px;font-weight:800;color:{ACC};border-left:6px solid {GOLD};padding-left:12px;margin-bottom:10px}}
.rsh span{{color:{MUTE};font-weight:600;font-size:17px}}
.rgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.rcard{{background:#fff;border:1px solid {LINE};border-radius:12px;padding:12px 14px}}
.rcn{{font-size:20px;font-weight:800;display:flex;justify-content:space-between;align-items:center}}
.rtag{{color:#fff;font-size:14px;padding:2px 10px;border-radius:8px;font-weight:700}}
.rcs{{font-size:16px;color:{MUTE};margin-top:6px}} .rcm{{font-size:15px;color:{MUTE};margin-top:2px}}
.briefbox{{background:linear-gradient(135deg,#FFFDF7,#F5EFE2);border:1px solid {LINE};border-radius:18px;padding:8px 30px 8px 14px}}
.briefbox li{{font-size:20px;line-height:1.75;margin:12px 0 12px 22px;color:#3C382F}}
.foot{{padding:24px 54px 0;font-size:16px;color:{MUTE};line-height:1.7}}
</style></head><body><div class="wrap">
<div class="hero">
  <div class="brand">WINDRISE · 期货资金潮汐</div><div class="hdate">{DATE} 盘后</div>
  <div class="hl">机构资金潮汐净值 · 名义净持仓(亿)</div>
  <div class="hv" style="color:{'#F0A89C' if tlvl>=0 else '#9FD8B4'}">{tlvl:+.0f}<span>亿</span></div>
  <div class="hsub">今日变动 <b>{tdl:+.1f}亿</b>　·　40日区间 {tlo:+.0f} ~ {thi:+.0f} 亿　·　总变动 {tot_lots:,.0f} 手</div>
  <div class="hbadge" style="background:{'rgba(240,168,156,.22)' if senti<0 else 'rgba(159,216,180,.22)'};color:{'#F0A89C' if tlvl>=0 else '#9FD8B4'}">
     {'资金偏空' if senti<0 else '资金偏多' if senti>0 else '多空均衡'} · 情绪 {senti:+.0f}%</div>
</div>

<div class="sec"><div class="h2">多空动作全景 <small>加多 / 减多 / 减空 / 加空 品种分布 · 情绪偏向</small></div>
 <div class="topgrid">
   <div class="donutbox"><svg width="300" height="300" viewBox="0 0 300 300">{donut(dseg)}</svg>
     <div class="dcenter"><div class="dc1" style="color:{RED if senti>=0 else GRN}">{senti:+.0f}%</div><div class="dc2">情绪偏向</div></div></div>
   <div class="kpis">
     <div class="kpi" style="background:linear-gradient(135deg,{RED},#9E2E20)"><div class="kl">加多品种</div><div class="kv">{n['加多']}</div><div class="ks">名义 {amt_add_long:.1f}亿</div></div>
     <div class="kpi" style="background:linear-gradient(135deg,{RSOFT},#C06A52)"><div class="kl">减多品种</div><div class="kv">{n['减多']}</div><div class="ks">多头获利了结</div></div>
     <div class="kpi" style="background:linear-gradient(135deg,{GRN},#166B3B)"><div class="kl">加空品种</div><div class="kv">{n['加空']}</div><div class="ks">名义 {amt_add_short:.1f}亿</div></div>
     <div class="kpi" style="background:linear-gradient(135deg,{GSOFT},#4C8C68)"><div class="kl">减空品种</div><div class="kv">{n['减空']}</div><div class="ks">空头回补</div></div>
   </div>
   <div class="gaugebox"><svg width="300" height="180" viewBox="0 0 300 175">{gauge(senti)}</svg>
     <div class="gv" style="color:{RED if senti>=0 else GRN}">{senti:+.0f}%</div>
     <div style="font-size:17px;color:{MUTE}">← 极空　　情绪　　极多 →</div></div>
 </div></div>

<div class="sec"><div class="h2">各类资金净流向 <small>四类主力今日名义净流向 · 亿(左空右多)</small></div>{cohort_bars}</div>

<div class="sec"><div class="h2">板块资金热力 <small>各板块机构名义净持仓 · 亿(红多绿空 深浅=强度)</small></div><div class="heat">{sec_tiles}</div></div>

<div class="sec"><div class="h2">四类动作榜 <small>按名义金额排 · 相对幅度≥50%(金色)=激进加减仓</small></div>
 <div class="defnote">口径:按每个席位<b>当前净方向</b>与仓位增减判定 —— <b style="color:{RED}">加多</b>=净多头且加仓 · <b style="color:{RSOFT}">减多</b>=净多头且减仓 · <b style="color:{GRN}">加空</b>=净空头且加仓 · <b style="color:{GSOFT}">减空</b>=净空头且减仓。<b>非逐笔多空拆分</b>,故"卖空/平多"不会被混计为加多。</div>
 <div class="fourgrid">
   {act_table_long('加多', RED, '净多头·加仓')}{act_table_long('减多', RSOFT, '净多头·减仓')}
   {act_table_long('加空', GRN, '净空头·加仓')}{act_table_long('减空', GSOFT, '净空头·减仓')}
 </div></div>

<div class="sec"><div class="h2">资金持续性榜 <small>机构净持仓连续同向天数 · 越长=趋势资金越坚定</small></div>
 <div class="topcard">{pers_rows}</div></div>

<div class="sec"><div class="h2">资金背离雷达 <small>资金与价格逆向, 常为主力提前布局</small></div>
 <div class="divbox"><div class="divh" style="color:{RED}">逆势吸筹 · 加多而价跌</div>{bull_chips}</div>
 <div class="divbox"><div class="divh" style="color:{GRN}">逆势沽空 · 加空而价涨</div>{bear_chips}</div></div>

<div class="sec"><div class="h2">资金动能共振榜 · 按板块 <small>机构方向与10日趋势同向 · 可信度据样本外回测(跟杭州/反外资)校准</small></div>
 {reson_html}</div>

<div class="sec"><div class="h2">今日速览 <small>基于上述数据自动生成</small></div>
 <div class="briefbox"><ul>{brief_html}</ul></div></div>

<div class="foot">数据源: 奇货可查龙虎榜逐日主力席位净持仓 + akshare 主力合约价格 · 机构=中信+国君+东证 · 名义=持仓×合约乘数×收盘价 · 描述性研究, 不构成投资建议 · WINDRISE CAPITAL</div>
</div></body></html>"""


def render():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--no-sandbox"])
            pg = b.new_page(viewport={"width": 1080, "height": 1600}, device_scale_factor=2)
            pg.set_content(HTML, wait_until="networkidle")
            out = OUT / f"期货资金潮汐_长图_{DATE.replace('-','')}.png"
            pg.screenshot(path=str(out), full_page=True); b.close()
        print("PNG ok", out)
    except Exception as e:
        (OUT / f"期货资金潮汐_长图_{DATE.replace('-','')}.html").write_text(HTML, encoding="utf-8")
        print("PNG fail, HTML written:", str(e)[:160])


if __name__ == "__main__":
    render()
