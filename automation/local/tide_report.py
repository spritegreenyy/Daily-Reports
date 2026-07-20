#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""期货资金潮汐 · 仪表盘日报(v2, 密集版) — 从 cohort_today.json 生成 BW 风格多面板仪表盘。
面板: KPI头卡 / 4动作榜(加多减多加空减空) / 价格×持仓象限 / 资金背离雷达 / 持续性榜 / 板块分组资金动能共振榜。
"""
import sys, json, base64, io
from datetime import datetime
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Arial Unicode MS", "PingFang SC", "Heiti SC"]  # Mac CJK
sys.path.insert(0, str(Path(__file__).parent.parent))
from tide_backtest import build_cohort_backtests

D = Path(__file__).parent; OUT = D / "output"; OUT.mkdir(exist_ok=True)
DATA = json.load(open(D / "cohort_today.json", encoding="utf-8"))
_VAR = json.load(open(D / "varieties.json", encoding="utf-8"))
DISP = {v: _VAR[v]["display"] for v in _VAR}
SECTOR = {v: _VAR[v].get("sector", "其他") for v in _VAR}
BG = "#FBF9F3"; INK = "#2A2A28"; MUTE = "#8A8172"; LINE = "#E4DCC9"
RED = "#C0392B"; GRN = "#1E8449"; GOLD = "#B0842B"; ACC = "#2D5F8A"
plt.rcParams.update({"axes.edgecolor": LINE, "text.color": INK, "xtick.color": MUTE, "ytick.color": MUTE, "font.size": 8})
SEC_ORDER = ["有色", "黑色", "化工", "能源", "农产品", "贵金属", "其他"]
# 合约乘数(单位/手), 用于金额=价格×乘数×变动手数; 缺省10
MULT = {"铜": 5, "铝": 5, "锌": 5, "铅": 5, "镍": 1, "锡": 1, "黄金": 1000, "白银": 15, "不锈钢": 5,
        "氧化铝": 20, "原油": 1000, "PVC": 5, "PP": 5, "LLDPE": 5, "塑料": 5, "苯乙烯": 5, "PTA": 5,
        "棉花": 5, "棉纱": 5, "短纤": 5, "硅铁": 5, "锰硅": 5, "红枣": 5, "花生": 5, "工业硅": 5, "PX": 5,
        "玻璃": 20, "纯碱": 20, "尿素": 20, "液化气": 20, "铁矿石": 100, "焦炭": 100, "动力煤": 100,
        "焦煤": 60, "生猪": 16, "多晶硅": 3, "碳酸锂": 1, "烧碱": 30}


def action(net, dnet):
    if net >= 0:
        return ("加多", RED) if dnet > 0 else ("减多", "#D9836B")
    return ("加空", GRN) if dnet < 0 else ("减空", "#5FA97E")


def metrics(v):
    inst = DATA.get(v, {}).get("机构")
    if not inst or not inst.get("net") or len(inst["net"]) < 12:
        return None
    net = inst["net"]; close = inst["close"]
    dnet = net[-1] - net[-2]; tr10 = net[-1] - net[-11]
    d60 = np.diff(net[-61:]) if len(net) >= 61 else np.diff(net)
    z = float((dnet - d60.mean()) / (d60.std() + 1e-9))
    pc = (close[-1] / close[-2] - 1) * 100 if close and len(close) >= 2 and close[-2] else None
    # 连续同向天数
    diffs = np.diff(net[-40:]); streak = 0
    if len(diffs):
        s0 = np.sign(diffs[-1])
        for dv in diffs[::-1]:
            if np.sign(dv) == s0 and dv != 0:
                streak += 1
            else:
                break
        streak = int(streak * s0)  # 带符号: +连续加 / -连续减
    act, acol = action(net[-1], dnet)
    disp = DISP.get(v, v)
    px = close[-1] if close else None
    mult = MULT.get(disp, 10)
    amt = (px * mult * abs(dnet)) if px else 0.0          # 金额=价格×合约乘数×变动手数(元)
    ratio = abs(dnet) / max(abs(net[-1] - dnet), 1) * 100  # 相对幅度%=变动/原持仓
    d_prev = (net[-2] - net[-3]) if len(net) >= 3 else None  # 昨日Δ
    hb = ((dnet - d_prev) / abs(d_prev) * 100) if (d_prev not in (None, 0)) else None  # 环比=今Δ相对昨Δ

    def cdnet(c):
        m = DATA.get(v, {}).get(c)
        return (m["net"][-1] - m["net"][-2]) if (m and m.get("net") and len(m["net"]) >= 2) else None
    return {"v": v, "disp": disp, "sector": SECTOR.get(v, "其他"), "net": net[-1], "dnet": dnet,
            "tr10": tr10, "z": z, "pc": pc, "act": act, "acol": acol, "streak": streak, "amt": amt, "ratio": ratio,
            "hb": hb, "px": px, "mult": mult,
            "net_series": [float(x) for x in net[-60:]], "hz": cdnet("杭州"), "wz": cdnet("外资")}


ROWS = [m for m in (metrics(v) for v in DATA) if m]
TARGET = max((DATA[v]["机构"]["dates"][-1] for v in DATA if DATA[v].get("机构", {}).get("dates")), default="")


def score(m):
    gd, gt, hd, wd = m["dnet"], m["tr10"], m["hz"], m["wz"]
    if gd > 0 and gt >= 0:
        lean, dirtxt, col = 1, "利多", RED
    elif gd < 0 and gt <= 0:
        lean, dirtxt, col = -1, "利空", GRN
    else:
        return None
    s = 50
    if hd is not None:
        s += 20 if ((hd > 0) == (lean > 0)) else -20
    if wd is not None:
        s += 12 if ((wd > 0) != (lean > 0)) else -8
    s += 6 if abs(gt) > 20000 else 3 if abs(gt) >= 5000 else 0
    s += 4 if abs(gd) > 10000 else 2 if abs(gd) >= 3000 else 0
    s = max(0, min(100, int(round(s))))
    return dirtxt, col, s, ("很高" if s >= 85 else "高" if s >= 70 else "中" if s >= 55 else "低" if s >= 40 else "很低")


def b64(fig):
    buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", facecolor=BG, dpi=140)
    plt.close(fig); return base64.b64encode(buf.getvalue()).decode()


def spark(series, col, h=0.42):
    fig, ax = plt.subplots(figsize=(1.5, h), dpi=130)
    ax.plot(series, color=col, lw=1.1); ax.axhline(0, color=LINE, lw=0.5)
    ax.fill_between(range(len(series)), series, 0, color=col, alpha=0.12)
    ax.axis("off"); fig.patch.set_facecolor(BG); fig.tight_layout(pad=0)
    return b64(fig)


def gg(x):
    return "—" if x is None else f"{int(round(x)):,}"


def fig_quadrant():
    pts = [m for m in ROWS if m["pc"] is not None]
    fig, ax = plt.subplots(figsize=(6.4, 4.7), dpi=140)
    ax.axhline(0, color=LINE, lw=1); ax.axvline(0, color=LINE, lw=1)
    for m in pts:
        col = RED if m["z"] > 0 else GRN
        ax.scatter(m["pc"], m["z"], s=44, color=col, alpha=0.72, edgecolor="white", lw=0.5, zorder=3)
        if abs(m["z"]) > 1.0 or abs(m["pc"]) > 1.2:
            ax.annotate(m["disp"], (m["pc"], m["z"]), fontsize=6.6, color=INK, xytext=(3, 2), textcoords="offset points")
    lim = max(2.5, min(6, max(abs(m["z"]) for m in pts) * 1.1)); xl = max(2.0, max(abs(m["pc"]) for m in pts) * 1.1)
    ax.set_ylim(-lim, lim); ax.set_xlim(-xl, xl)
    ax.set_xlabel("价格涨跌 %", fontsize=9); ax.set_ylabel("机构资金流向强度 z", fontsize=9)
    for x, y, t, c in [(xl * 0.55, lim * 0.85, "量价齐升·强多", RED), (-xl * 0.7, lim * 0.85, "逆势吸筹", ACC),
                       (xl * 0.55, -lim * 0.9, "冲高派发", GOLD), (-xl * 0.7, -lim * 0.9, "杀跌离场", GRN)]:
        ax.text(x, y, t, fontsize=8.3, color=c, fontweight="bold", ha="center")
    ax.set_facecolor(BG)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    fig.patch.set_facecolor(BG); fig.tight_layout()
    return b64(fig)


def amt_fmt(a):
    return f"{a/1e8:.2f}亿" if a >= 1e8 else f"{a/1e4:,.0f}万"


def act_panel(act, col, title):
    grp = sorted([m for m in ROWS if m["act"] == act], key=lambda m: -m["amt"])[:8]  # 按金额(名义价值)排
    rows = "".join(
        f"<tr><td>{m['disp']}</td>"
        f"<td style='text-align:right;color:{col};font-weight:700'>{amt_fmt(m['amt'])}</td>"
        f"<td style='text-align:right;font-size:8pt;{('font-weight:700;color:'+GOLD) if m['ratio']>=50 else ('color:'+MUTE)}'>{min(m['ratio'],999):.0f}%</td>"
        f"<td style='text-align:right;font-size:7.5pt;color:{MUTE}'>{gg(abs(m['dnet']))}</td></tr>"
        for m in grp) or "<tr><td colspan=4 style='color:#aaa'>无</td></tr>"
    return (f"<div class='apanel'><div class='ah' style='color:{col}'>{title} <span class='an'>{len([m for m in ROWS if m['act']==act])}</span></div>"
            f"<table class='at'><tr><th></th><th style='text-align:right;font-weight:400;color:#B3A990;font-size:7pt'>金额</th><th style='text-align:right;font-weight:400;color:#B3A990;font-size:7pt'>相对</th><th style='text-align:right;font-weight:400;color:#B3A990;font-size:7pt'>手</th></tr>{rows}</table></div>")


COHORTS = ["机构", "外资", "杭州", "中财", "散户"]
COHORT_MEMBERS = {
    "机构": ["中信期货", "国泰君安", "东证期货"],
    "外资": ["乾坤期货", "摩根大通"],
    "杭州": ["永安期货", "南华期货", "浙商期货", "宝城期货", "物产中大", "大地期货"],
    "中财": ["中财期货"],
    "散户": ["东方财富期货", "徽商期货", "平安期货"],
}
try:  # 逐席位数据(pull_brokers.py 产出); 缺失时 members 自动为空, 不影响主报告
    BDATA = json.load(open(D / "broker_today.json", encoding="utf-8"))
except Exception:
    BDATA = {}


def broker_flow(bname):
    """某一家席位今日名义净流向(亿)=Σ Δnet×乘数×价。"""
    tot = 0.0; ok = False
    for v in BDATA:
        m = BDATA.get(v, {}).get(bname)
        if not m or not m.get("net") or len(m["net"]) < 2 or not m.get("close") or m["close"][-1] is None:
            continue
        tot += (m["net"][-1] - m["net"][-2]) * MULT.get(DISP.get(v, v), 10) * m["close"][-1] / 1e8; ok = True
    return tot if ok else None


def broker_series(bname, win=40):
    """某一家席位 名义净持仓(亿) 跨品种聚合序列(近 win+1 日)。"""
    L = win + 1; agg = None
    for v in BDATA:
        m = BDATA.get(v, {}).get(bname)
        if not m or not m.get("net") or not m.get("close") or len(m["net"]) < L or len(m["close"]) < L:
            continue
        cl = m["close"][-L:]
        if any(x is None for x in cl):
            continue
        arr = np.asarray(m["net"][-L:], float) * MULT.get(DISP.get(v, v), 10) * np.asarray(cl, float) / 1e8
        agg = arr if agg is None else agg + arr
    return agg


def notional_series(cohort="机构", win=40):
    """各品种 名义净持仓(元)=net×合约乘数×收盘价, 按尾部对齐后跨品种累加; 返回近 win+1 日的 亿 序列。"""
    L = win + 1; agg = None
    for v in DATA:
        m = DATA.get(v, {}).get(cohort)
        if not m or not m.get("net") or not m.get("close"):
            continue
        net, close = m["net"], m["close"]
        if len(net) < L or len(close) < L:
            continue
        arr = np.asarray(net[-L:], float) * MULT.get(DISP.get(v, v), 10) * np.asarray(close[-L:], float) / 1e8
        agg = arr if agg is None else agg + arr
    return agg


def cohort_flow(cohort):
    """今日某类资金 名义净流向(亿)=Σ Δnet×乘数×价。"""
    tot = 0.0; ok = False
    for v in DATA:
        m = DATA.get(v, {}).get(cohort)
        if not m or not m.get("net") or len(m["net"]) < 2 or not m.get("close"):
            continue
        tot += (m["net"][-1] - m["net"][-2]) * MULT.get(DISP.get(v, v), 10) * m["close"][-1] / 1e8; ok = True
    return tot if ok else None


def sector_series(sec, win=40):
    L = win + 1; agg = None
    for v in DATA:
        if SECTOR.get(v, "其他") != sec:
            continue
        m = DATA.get(v, {}).get("机构")
        if not m or not m.get("net") or not m.get("close") or len(m["net"]) < L or len(m["close"]) < L:
            continue
        arr = np.asarray(m["net"][-L:], float) * MULT.get(DISP.get(v, v), 10) * np.asarray(m["close"][-L:], float) / 1e8
        agg = arr if agg is None else agg + arr
    return agg


def yi(x, dec=1):
    return "—" if x is None else f"{x:+.{dec}f}亿"


def fig_tide(series):
    import matplotlib.colors as mcolors
    from matplotlib.patches import Polygon
    from matplotlib.collections import LineCollection
    y = np.asarray(series, float); x = np.arange(len(y))
    cur = float(y[-1]); main = RED if cur >= 0 else GRN
    fig, ax = plt.subplots(figsize=(3.9, 0.98), dpi=160)
    ymin, ymax = float(y.min()), float(y.max())
    pad = (ymax - ymin) * 0.22 + 1e-6; lo, hi = ymin - pad, ymax + pad

    def grad_area(ytop, ybot, color, y0, y1, opaque_top):
        if np.allclose(ytop, ybot):
            return
        rgb = mcolors.to_rgb(color)
        g = np.empty((256, 1, 4)); g[..., :3] = rgb
        ramp = np.linspace(0.50, 0.03, 256) if opaque_top else np.linspace(0.03, 0.50, 256)
        g[..., 3] = ramp.reshape(-1, 1)
        im = ax.imshow(g, extent=[0, len(y) - 1, y0, y1], origin="upper", aspect="auto", zorder=1)
        verts = np.column_stack([np.r_[x, x[::-1]], np.r_[ytop, ybot[::-1]]])
        p = Polygon(verts, closed=True, fc="none", ec="none"); ax.add_patch(p); im.set_clip_path(p)

    zeros = np.zeros_like(y)
    # 零上=偏多(红渐变), 零下=偏空(绿渐变)
    grad_area(np.maximum(y, 0), zeros, RED, 0, max(hi, 1e-6), True)
    grad_area(zeros, np.minimum(y, 0), GRN, min(lo, -1e-6), 0, False)
    # 零轴
    if lo < 0 < hi:
        ax.axhline(0, color=GOLD, lw=0.9, ls=(0, (4, 3)), alpha=0.6, zorder=2)
    # 描边按正负上色, 透明度随时间由浅到深
    pts = np.array([x, y]).T.reshape(-1, 1, 2); segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
    midy = (y[:-1] + y[1:]) / 2
    seg_rgb = [mcolors.to_rgb(RED if m >= 0 else GRN) for m in midy]
    alphas = np.linspace(0.45, 1.0, len(segs))
    lc = LineCollection(segs, colors=[(*c, a) for c, a in zip(seg_rgb, alphas)],
                        linewidths=2.2, capstyle="round", zorder=3)
    ax.add_collection(lc)
    # 末端光晕 + 白边点 + 数值气泡
    ax.scatter([x[-1]], [cur], s=115, color=main, alpha=0.16, zorder=4, linewidths=0)
    ax.scatter([x[-1]], [cur], s=30, color=main, edgecolor="white", lw=1.3, zorder=5)
    ax.annotate(f"{cur:+.0f}亿", (x[-1], cur), xytext=(-3, 7 if cur >= 0 else -12), textcoords="offset points",
                fontsize=9, fontweight="bold", color=main, ha="right", zorder=6)
    ax.set_xlim(-0.5, (len(y) - 1) * 1.07); ax.set_ylim(lo, hi)
    ax.axis("off"); fig.patch.set_facecolor(BG); fig.tight_layout(pad=0)
    return b64(fig)


def fig_cohort():
    cs = [c for c in COHORTS if cohort_flow(c) is not None]
    vals = [cohort_flow(c) for c in cs]
    fig, ax = plt.subplots(figsize=(4.4, 2.7), dpi=140)
    ax.barh(range(len(cs)), vals, color=[RED if x >= 0 else GRN for x in vals], height=0.6, alpha=0.9)
    ax.axvline(0, color=LINE, lw=1); ax.set_yticks(range(len(cs))); ax.set_yticklabels(cs, fontsize=9.5)
    for i, x in enumerate(vals):
        ax.text(x, i, f" {x:+.1f} ", va="center", ha="left" if x >= 0 else "right", fontsize=8.2, color=INK)
    mx = max((abs(v) for v in vals), default=1) * 1.35
    ax.set_xlim(-mx, mx); ax.set_title("今日各类资金净流向 · 亿(名义)", fontsize=10, fontweight="bold", pad=5)
    ax.set_facecolor(BG); ax.tick_params(length=0); ax.set_xticks([])
    for s in ["top", "right", "bottom"]:
        ax.spines[s].set_visible(False)
    fig.patch.set_facecolor(BG); fig.tight_layout()
    return b64(fig)


def fig_flow_dual():
    bull = sorted([m for m in ROWS if m["act"] == "加多"], key=lambda m: -m["amt"])[:6]
    bear = sorted([m for m in ROWS if m["act"] == "加空"], key=lambda m: -m["amt"])[:6]
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 2.6), dpi=140)
    for ax, grp, col, title in [(axes[0], bull[::-1], RED, "净买入(加多)名义强度 TOP"), (axes[1], bear[::-1], GRN, "净卖出(加空)名义强度 TOP")]:
        y = range(len(grp)); ax.barh(y, [m["amt"] / 1e8 for m in grp], color=col, height=0.6, alpha=0.9)
        ax.set_yticks(list(y)); ax.set_yticklabels([m["disp"] for m in grp], fontsize=9)
        for i, m in enumerate(grp):
            ax.text(m["amt"] / 1e8, i, f"  {m['amt']/1e8:.1f}亿", va="center", fontsize=8)
        ax.set_title(title, fontsize=10, fontweight="bold", pad=5); ax.set_facecolor(BG)
        for s in ["top", "right"]:
            ax.spines[s].set_visible(False)
        ax.tick_params(length=0); ax.set_xticks([])
        ax.set_xlim(0, max((m["amt"] / 1e8 for m in grp), default=1) * 1.25)
    fig.patch.set_facecolor(BG); fig.tight_layout(pad=1.0)
    return b64(fig)


def build():
    n = {a: sum(1 for m in ROWS if m["act"] == a) for a in ("加多", "减多", "加空", "减空")}
    tot_add_long = sum(m["dnet"] for m in ROWS if m["act"] == "加多")
    tot_add_short = sum(-m["dnet"] for m in ROWS if m["act"] == "加空")
    senti = (n["加多"] - n["加空"]) / max(1, len(ROWS)) * 100
    kpi = lambda l, v, s, c=INK: f"<div class='kpi'><div class='kl'>{l}</div><div class='kv' style='color:{c}'>{v}</div><div class='ks'>{s}</div></div>"

    # 背离雷达: 加多+价跌(逆势吸筹) / 加空+价涨(逆势沽空)
    div_bull = sorted([m for m in ROWS if m["act"] == "加多" and (m["pc"] or 0) < -0.2], key=lambda m: m["pc"])[:6]
    div_bear = sorted([m for m in ROWS if m["act"] == "加空" and (m["pc"] or 0) > 0.2], key=lambda m: -m["pc"])[:6]
    def divrows(grp, col, tag):
        return "".join(f"<tr><td>{m['disp']}</td><td style='color:{col};font-size:8pt'>{tag}</td>"
                       f"<td style='text-align:right;color:{col};font-weight:700'>{gg(abs(m['dnet']))}</td>"
                       f"<td style='text-align:right;color:{RED if (m['pc'] or 0)>=0 else GRN}'>{(m['pc'] or 0):+.1f}%</td></tr>" for m in grp) or "<tr><td colspan=4 style='color:#aaa'>无</td></tr>"

    # 持续性榜: 连续同向天数 top
    pers = sorted(ROWS, key=lambda m: -abs(m["streak"]))[:10]
    persrows = ""
    for m in pers:
        col = RED if m["streak"] > 0 else GRN
        sp = spark(m["net_series"], col)
        persrows += (f"<tr><td>{m['disp']}</td><td style='color:{col};font-weight:700;text-align:center'>{'连加' if m['streak']>0 else '连减'}{abs(m['streak'])}日</td>"
                     f"<td><img class='sps' src='data:image/png;base64,{sp}'></td>"
                     f"<td style='text-align:right;font-size:8pt'>{'净多' if m['net']>=0 else '净空'}{gg(abs(m['net']))}</td></tr>")

    # 共振榜 按板块
    reson = [(m, score(m)) for m in ROWS]
    reson = [(m, cs) for m, cs in reson if cs]
    bysec = {}
    for m, cs in reson:
        bysec.setdefault(m["sector"], []).append((m, cs))
    sec_html = ""
    for sec in SEC_ORDER:
        grp = sorted(bysec.get(sec, []), key=lambda x: -x[1][2])
        if not grp:
            continue
        cards = ""
        for m, (dirtxt, col, s, tier) in grp:
            sp = spark(m["net_series"], col)
            tcol = RED if (tier in ("很高", "高") and dirtxt == "利多") else GRN if (tier in ("很高", "高")) else GOLD if tier == "中" else MUTE
            cards += (f"<div class='rc'><div class='rcn'>{m['disp']}</div>"
                      f"<img class='sp' src='data:image/png;base64,{sp}'>"
                      f"<div class='rcd'><span style='color:{col};font-weight:700'>{dirtxt}</span> <span style='color:{tcol};font-weight:700'>{s}·{tier}</span></div>"
                      f"<div class='rcm'>{m['act']} {gg(abs(m['dnet']))} · <span style='color:{RED if (m['pc'] or 0)>=0 else GRN}'>{(m['pc'] or 0):+.1f}%</span></div></div>")
        sec_html += f"<div class='secblock'><div class='sech'>{sec} <span class='secn'>{len(grp)}</span></div><div class='reson'>{cards}</div></div>"

    # 顶部潮汐净值(机构名义净持仓聚合)
    tide = notional_series("机构", 40)
    if tide is not None and len(tide) >= 2:
        tlvl = float(tide[-1]); tdl = float(tide[-1] - tide[-2]); thi = float(np.max(tide)); tlo = float(np.min(tide))
        tide_img = fig_tide([float(x) for x in tide])
    else:
        tlvl = tdl = thi = tlo = 0.0; tide_img = None

    # 盘后资金总览
    amt_add_long = sum(m["amt"] for m in ROWS if m["act"] == "加多") / 1e8
    amt_add_short = sum(m["amt"] for m in ROWS if m["act"] == "加空") / 1e8
    lots_tot = sum(abs(m["dnet"]) for m in ROWS)

    # 资金强度排行榜(全品种按名义金额, 含环比+近60日走势)
    rk_top = sorted(ROWS, key=lambda m: -m["amt"])[:15]
    rk_rows = ""
    for i, m in enumerate(rk_top, 1):
        col = m["acol"]; sp = spark(m["net_series"], RED if m["net"] >= 0 else GRN)
        hb = m["hb"]; hbtxt = "—" if hb is None else (f"{hb:+.0f}%" if abs(hb) < 999 else "翻转")
        hbcol = MUTE if hb is None else (RED if hb >= 0 else GRN)
        rk_rows += (f"<tr><td style='color:{MUTE}'>{i}</td><td style='font-weight:700'>{m['disp']}</td>"
                    f"<td style='color:{MUTE};font-size:8pt'>{m['sector']}</td>"
                    f"<td style='color:{col};font-weight:700'>{m['act']}</td>"
                    f"<td style='text-align:right;color:{col};font-weight:700'>{amt_fmt(m['amt'])}</td>"
                    f"<td style='text-align:right;{('color:'+GOLD+';font-weight:700') if m['ratio']>=50 else ('color:'+MUTE)}'>{min(m['ratio'],999):.0f}%</td>"
                    f"<td style='text-align:right;color:{hbcol};font-size:8pt'>{hbtxt}</td>"
                    f"<td><img class='sps' src='data:image/png;base64,{sp}'></td></tr>")

    cohort_img = fig_cohort(); dual_img = fig_flow_dual()

    # 板块迷你走势排(机构名义)
    sec_spark = ""
    for sec in SEC_ORDER:
        ss = sector_series(sec, 40)
        if ss is None:
            continue
        cur = float(ss[-1]); dl = float(ss[-1] - ss[-2]) if len(ss) >= 2 else 0.0
        sp = spark([float(x) for x in ss], RED if cur >= 0 else GRN)
        sec_spark += (f"<div class='ssc'><div class='ssn'>{sec}</div>"
                      f"<img class='ssi' src='data:image/png;base64,{sp}'>"
                      f"<div class='ssv'>净<b style='color:{RED if cur>=0 else GRN}'>{cur:+.1f}亿</b> · 日<span style='color:{RED if dl>=0 else GRN}'>{dl:+.1f}</span></div></div>")

    # ── 交互网页数据(纯数值, 供 make_tide_web 渲染可交互图表) ──
    _dref = max((DATA[v]["机构"]["dates"] for v in DATA if DATA[v].get("机构", {}).get("dates")), key=len, default=[])

    def _row_json(m):
        cs = score(m)
        return {"name": m["disp"], "sector": m["sector"], "act": m["act"],
                "amt": round(m["amt"] / 1e8, 3), "amt_txt": amt_fmt(m["amt"]),
                "ratio": round(min(m["ratio"], 999), 1), "hb": None if m["hb"] is None else round(m["hb"], 1),
                "streak": m["streak"], "net": int(m["net"]), "dnet": int(m["dnet"]),
                "px": m["px"], "pc": None if m["pc"] is None else round(m["pc"], 2), "z": round(m["z"], 2),
                "dir": cs[0] if cs else None, "conf": cs[2] if cs else None, "tier": cs[3] if cs else None,
                "series": [round(float(x)) for x in m["net_series"]]}
    _secser = {sec: sector_series(sec, 40) for sec in SEC_ORDER}

    _bdate = max((BDATA[v][b]["dates"][-1] for v in BDATA for b in BDATA[v]
                  if BDATA[v][b].get("dates")), default=None)
    _members_ok = (_bdate == TARGET)   # 逐席位数据没跟上主数据日期时, 先不带成员(稍后重出)

    def _cohort_json(c):
        cs = notional_series(c, 40)
        members = []
        for b in (COHORT_MEMBERS.get(c, []) if _members_ok else []):
            bf = broker_flow(b)
            if bf is None:
                continue
            bs = broker_series(b, 40)
            members.append({"name": b, "flow": round(bf, 2),
                            "series": [round(float(x), 1) for x in bs] if bs is not None else []})
        return {"name": c, "flow": round(cohort_flow(c), 2),
                "series": [round(float(x), 1) for x in cs] if cs is not None else [], "members": members}
    web_data = {
        "date": TARGET, "net": round(tlvl, 1), "chg": round(tdl, 1), "range40": [round(tlo), round(thi)],
        "lots": int(lots_tot), "senti": round(senti), "in_play": len(ROWS),
        "amt_add_long": round(amt_add_long, 1), "amt_add_short": round(amt_add_short, 1),
        "kpi": {a: n[a] for a in ("加多", "减多", "加空", "减空")},
        "dates40": _dref[-41:], "dates60": _dref[-60:],
        "tide": [round(float(x), 1) for x in tide] if tide is not None else [],
        "cohorts": [_cohort_json(c) for c in COHORTS if cohort_flow(c) is not None],
        "sectors": [{"name": sec, "series": [round(float(x), 1) for x in _secser[sec]]} for sec in SEC_ORDER if _secser[sec] is not None],
        "rows": [_row_json(m) for m in ROWS],
        "backtests": build_cohort_backtests(DATA, DISP, SECTOR, MULT, SEC_ORDER, BDATA, COHORT_MEMBERS),
        "source": "奇货可查龙虎榜逐日主力席位净持仓 + akshare 主力合约价格 · 机构=中信+国君+东证",
    }
    (OUT / f"期货资金潮汐_{TARGET.replace('-','')}_data.json").write_text(json.dumps(web_data, ensure_ascii=False), encoding="utf-8")

    print(f"潮汐数据: {len(ROWS)}品种 加多{n['加多']}/减多{n['减多']}/加空{n['加空']}/减空{n['减空']} -> 期货资金潮汐_{TARGET.replace('-','')}_data.json")


if __name__ == "__main__":
    build()
