#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多品种4小时形态扫描本地测试：每品种只保留一个4h主结构。"""

import base64
import argparse
import io
import json
import sys
from datetime import datetime
from html import escape
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "output"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(HERE))

from hourly_pattern_report import fetch_hourly
from hourly_pattern_soybean_oil_prototype import compress_bars
from soybean_oil_skill_scan_prototype import dedupe, scan_timeframe

PRODUCTS = [
    ("原油", "sc0"),
    ("黄金", "au0"),
    ("白银", "ag0"),
    ("铜", "cu0"),
    ("铝", "al0"),
    ("锌", "zn0"),
    ("锡", "sn0"),
    ("碳酸锂", "lc0"),
    ("多晶硅", "ps0"),
    ("棕榈油", "p0"),
    ("豆油", "y0"),
    ("豆粕", "m0"),
    ("PTA", "ta0"),
    ("甲醇", "ma0"),
    ("PP", "pp0"),
]
PRODUCT_EN = {
    "原油": "Crude Oil", "黄金": "Gold", "白银": "Silver", "铜": "Copper",
    "铝": "Aluminum", "锌": "Zinc", "锡": "Tin", "碳酸锂": "Lithium Carbonate",
    "多晶硅": "Polysilicon", "棕榈油": "Palm Oil", "豆油": "Soybean Oil",
    "豆粕": "Soybean Meal", "PTA": "PTA", "甲醇": "Methanol", "PP": "Polypropylene",
}
MIN_CONFIDENCE = 0.55


def choose_candidates(frame, limit=3):
    candidates = [
        candidate for candidate in dedupe(scan_timeframe("4h", frame))
        if float(candidate["hit"]["confidence"]) >= MIN_CONFIDENCE
    ]
    kept = []
    for candidate in candidates:
        start = candidate["hit"]["start_bar"]
        end = candidate["hit"]["end_bar"]
        overlaps = False
        for old in kept:
            old_start = old["hit"]["start_bar"]
            old_end = old["hit"]["end_bar"]
            overlap = max(0, min(end, old_end) - max(start, old_start) + 1)
            shorter = max(1, min(end - start + 1, old_end - old_start + 1))
            if overlap / shorter >= 0.70:
                overlaps = True
                break
        if not overlaps:
            kept.append(candidate)
        if len(kept) >= limit:
            break
    return kept


def projected_boundary(candidate):
    bounds = candidate["bounds"]
    return {
        "upper": bounds["upper"],
        "lower": bounds["lower"],
        "start": bounds["start"],
        "end": bounds["end"],
    }


def structure_tilt(candidate):
    if not candidate:
        return "无"
    if candidate["state"] == "形成中":
        # 这里只表示形态统计倾向，不等同于交易信号。
        return "偏多" if candidate["hit"]["bias"] == "bullish" else "偏空"
    return "向上确认" if candidate["breakout_side"] == "above" else "向下确认"


def confidence_band(value):
    if value >= 0.70:
        return "高"
    if value >= 0.60:
        return "中"
    return "观察"


def confidence_band_en(value):
    if value >= 0.70:
        return "High"
    if value >= 0.60:
        return "Medium"
    return "Watch"


def structure_analysis(candidate, upper, lower):
    confidence = float(candidate["hit"]["confidence"])
    if candidate["state"] == "形成中":
        if candidate["hit"]["bias"] == "bullish":
            direction = "偏向上突破"
            direction_en = "Upside breakout bias"
            reminder = (
                f"优先观察4h收盘能否站上上轨 {upper:,.0f}；"
                f"若先跌破下轨 {lower:,.0f}，偏多倾向失效并转为向下确认。"
            )
            reminder_en = (
                f"Watch for a 4h close above {upper:,.0f}; a break below "
                f"{lower:,.0f} invalidates the bullish tilt and confirms downside."
            )
        else:
            direction = "偏向下突破"
            direction_en = "Downside breakout bias"
            reminder = (
                f"优先观察4h收盘能否跌破下轨 {lower:,.0f}；"
                f"若先站上上轨 {upper:,.0f}，偏空倾向失效并转为向上确认。"
            )
            reminder_en = (
                f"Watch for a 4h close below {lower:,.0f}; a break above "
                f"{upper:,.0f} invalidates the bearish tilt and confirms upside."
            )
    elif candidate["breakout_side"] == "above":
        direction = "向上突破已确认"
        direction_en = "Upside breakout confirmed"
        reminder = (
            f"观察能否守住上轨 {upper:,.0f} 或回踩不破；"
            "若4h收盘重新回到结构内部，警惕假突破。"
        )
        reminder_en = (
            f"Watch whether price holds {upper:,.0f} or retests it successfully; "
            "a 4h close back inside the structure warns of a false breakout."
        )
    else:
        direction = "向下突破已确认"
        direction_en = "Downside breakout confirmed"
        reminder = (
            f"观察反抽是否受制于下轨 {lower:,.0f}；"
            "若4h收盘重新回到结构内部，警惕假跌破。"
        )
        reminder_en = (
            f"Watch whether a rebound is capped by {lower:,.0f}; a 4h close "
            "back inside the structure warns of a false breakdown."
        )
    return {
        "band": confidence_band(confidence),
        "band_en": confidence_band_en(confidence),
        "direction": direction,
        "direction_en": direction_en,
        "reminder": reminder,
        "reminder_en": reminder_en,
    }


def current_levels(frame, candidate):
    if not candidate:
        return None, None
    bounds = candidate["bounds"]
    bar = len(frame) - 1
    upper = bounds["upper"][0] * bar + bounds["upper"][1]
    lower = bounds["lower"][0] * bar + bounds["lower"][1]
    return float(upper), float(lower)


def plot_contract(name, frame, candidates):
    plt.rcParams["font.sans-serif"] = [
        "PingFang SC", "Hiragino Sans GB", "Arial Unicode MS", "DejaVu Sans"
    ]
    plt.rcParams["axes.unicode_minus"] = False

    visible = frame.tail(52)
    left = len(frame) - len(visible)
    right = len(frame) - 1
    xs = np.arange(left, right + 1)
    fig = plt.figure(figsize=(9.2, 5.4), dpi=125, facecolor="#050709")
    grid = fig.add_gridspec(5, 1, height_ratios=[4.8, 0.03, 0.82, 0.03, 0.82], hspace=0.04)
    ax = fig.add_subplot(grid[0])
    axv = fig.add_subplot(grid[2], sharex=ax)
    axo = fig.add_subplot(grid[4], sharex=ax)
    for axis in (ax, axv, axo):
        axis.set_facecolor("#050709")
        axis.grid(axis="y", color="#252b30", lw=0.55)
        axis.tick_params(colors="#9ca6ad", labelsize=7)
        for spine in axis.spines.values():
            spine.set_color("#4a2325")

    up, down = "#ef493e", "#00c4cc"
    for x, (_, row) in zip(xs, visible.iterrows()):
        color = up if row["close"] >= row["open"] else down
        ax.vlines(x, row["low"], row["high"], color=color, lw=0.65)
        body_low = min(row["open"], row["close"])
        body_height = max(abs(row["close"] - row["open"]), 1e-6)
        ax.add_patch(Rectangle((x - 0.29, body_low), 0.58, body_height, color=color, lw=0))

    for period, color, label in (
        (5, "#f0c83f", "MA5"), (20, "#d9dde0", "MA20"), (40, "#ed2939", "MA40")
    ):
        values = frame["close"].rolling(period).mean().iloc[left:right + 1]
        ax.plot(xs, values, color=color, lw=0.9 if period != 40 else 1.1, label=label)

    palette = ("#ff505a", "#00bafa", "#f0c83f")
    for rank, candidate in enumerate(candidates):
        color = palette[rank]
        lines = projected_boundary(candidate)
        lx = np.arange(max(left, lines["start"]), right + 1)
        upper_line = lines["upper"][0] * lx + lines["upper"][1]
        lower_line = lines["lower"][0] * lx + lines["lower"][1]
        width = 2.5 if rank == 0 else 1.7
        ax.plot(lx, upper_line, color=color, lw=width, zorder=7)
        ax.plot(lx, lower_line, color=color, lw=width, zorder=7)
        ax.fill_between(lx, lower_line, upper_line, color=color, alpha=0.06)
        label_x = min(right - 1, max(lines["end"], left + 3))
        label_y = lines["upper"][0] * label_x + lines["upper"][1]
        ax.annotate(
            f"{rank + 1}. 4h {candidate['pattern_cn']} / {candidate['pattern']}",
            (label_x, label_y), xytext=(8, 12 + rank * 18), textcoords="offset points",
            color=color, fontsize=8.0, fontweight="bold",
            bbox={"boxstyle": "round,pad=0.28", "fc": "#0b0f12", "ec": color},
        )
        upper, lower = current_levels(frame, candidate)
        ax.text(right + 0.45, upper, f"{rank + 1}上 {upper:,.0f}",
                color=color, va="center", fontsize=7.0)
        ax.text(right + 0.45, lower, f"{rank + 1}下 {lower:,.0f}",
                color=color, va="center", fontsize=7.0)
    if not candidates:
        ax.text(
            0.5, 0.5, "4h 未识别到满足几何标准的近期形态",
            transform=ax.transAxes, ha="center", va="center",
            color="#8e9aa2", fontsize=11,
            bbox={"boxstyle": "round,pad=0.5", "fc": "#11171c", "ec": "#34414a"},
        )

    volumes = visible["volume"].astype(float)
    colors = [up if c >= o else down for o, c in zip(visible["open"], visible["close"])]
    axv.bar(xs, volumes, width=0.62, color=colors, alpha=0.72)
    axv.plot(xs, frame["volume"].rolling(10).mean().iloc[left:right + 1],
             color="#f0c83f", lw=0.8)
    axv.set_ylabel("量", color="#9ca6ad", fontsize=7)
    if "hold" in visible.columns:
        hold = visible["hold"].astype(float)
        axo.plot(xs, hold, color="#d4d7d9", lw=0.9)
        axo.fill_between(xs, hold.to_numpy(), hold.min(), color="#d4d7d9", alpha=0.07)
    axo.set_ylabel("OI", color="#9ca6ad", fontsize=7)

    ticks = np.linspace(left, right, 7, dtype=int)
    axo.set_xticks(ticks)
    axo.set_xticklabels([frame.index[i].strftime("%m-%d") for i in ticks])
    plt.setp(ax.get_xticklabels(), visible=False)
    plt.setp(axv.get_xticklabels(), visible=False)
    latest = frame.iloc[-1]
    ax.scatter(right, latest["close"], s=24, color="#ffffff", edgecolor="#f0c83f", zorder=9)
    ax.set_xlim(left - 1, right + 7)
    pad = (visible["high"].max() - visible["low"].min()) * 0.10
    ax.set_ylim(visible["low"].min() - pad, visible["high"].max() + pad)
    ax.set_title(f"{name} / {PRODUCT_EN[name]} · 4h", loc="left",
                 color="#f0c83f", fontsize=13, fontweight="bold", pad=10)
    ax.text(
        0, 1.01, f"截至 {frame.index[-1]:%Y-%m-%d %H:%M} · 最新 {latest['close']:,.0f}",
        transform=ax.transAxes, color="#aeb7bd", fontsize=7.5,
    )
    ax.legend(loc="upper right", frameon=False, ncol=3, fontsize=6.5,
              labelcolor="#cfd4d7")
    fig.subplots_adjust(left=0.08, right=0.87, top=0.89, bottom=0.10)
    return fig


def serialize(name, code, frame, candidates):
    row = {
        "name": name,
        "code": code,
        "asof": frame.index[-1].strftime("%Y-%m-%d %H:%M"),
        "latest": float(frame["close"].iloc[-1]),
        "timeframe": "4h",
        "structures": [],
    }
    for candidate in candidates:
        upper, lower = current_levels(frame, candidate)
        analysis = structure_analysis(candidate, upper, lower)
        row["structures"].append({
            "pattern": candidate["pattern"],
            "pattern_cn": candidate["pattern_cn"],
            "state": candidate["state"],
            "tilt": structure_tilt(candidate),
            "confidence": round(float(candidate["hit"]["confidence"]), 3),
            "upper": upper,
            "lower": lower,
            "start": frame.index[candidate["hit"]["start_bar"]].strftime("%m-%d %H:%M"),
            "end": frame.index[candidate["hit"]["end_bar"]].strftime("%m-%d %H:%M"),
            "confidence_band": analysis["band"],
            "confidence_band_en": analysis["band_en"],
            "direction": analysis["direction"],
            "direction_en": analysis["direction_en"],
            "reminder": analysis["reminder"],
            "reminder_en": analysis["reminder_en"],
        })
    return row


def render_html(rows, images, generated):
    def attr(text):
        return escape(str(text), quote=True)

    ranked = sorted(
        (
            (row["name"], row["code"], item)
            for row in rows
            for item in row["structures"]
        ),
        key=lambda entry: entry[2]["confidence"],
        reverse=True,
    )
    high_count = sum(item["confidence"] >= 0.70 for _, _, item in ranked)
    forming_count = sum(item["state"] == "形成中" for _, _, item in ranked)
    forming = [
        (name, code, item)
        for name, code, item in ranked
        if item["state"] == "形成中"
    ]
    confirmed = [
        (name, code, item)
        for name, code, item in ranked
        if item["state"] != "形成中"
    ]
    forming_cards = "".join(
        f"""<a class="watch" href="#contract-{code}" data-target="contract-{code}">
<div><b data-en="{attr(PRODUCT_EN[name] + ' · ' + item['pattern'])}">{name} · {item['pattern_cn']}</b><span class="band {'high' if item['confidence'] >= 0.70 else ''}" data-en="{item['confidence_band_en']} {item['confidence']:.3f}">{item['confidence_band']} {item['confidence']:.3f}</span></div>
<strong data-en="{attr(item['direction_en'])}">{item['direction']}</strong>
<small data-en="{attr(item['reminder_en'])}">{item['reminder']}</small>
<em data-en="Click to view chart ↓">点击查看对应K线图 ↓</em>
</a>"""
        for name, code, item in forming[:12]
    ) or '<div class="watch empty">当前没有达到门槛的待突破结构。</div>'
    confirmed_cards = "".join(
        f"""<a class="watch confirmed" href="#contract-{code}" data-target="contract-{code}">
<div><b data-en="{attr(PRODUCT_EN[name] + ' · ' + item['pattern'])}">{name} · {item['pattern_cn']}</b><span class="band {'high' if item['confidence'] >= 0.70 else ''}" data-en="{item['confidence_band_en']} {item['confidence']:.3f}">{item['confidence_band']} {item['confidence']:.3f}</span></div>
<strong data-en="{attr(item['direction_en'])}">{item['direction']}</strong>
<small data-en="{attr(item['reminder_en'])}">{item['reminder']}</small>
<em data-en="Click to view chart ↓">点击查看对应K线图 ↓</em>
</a>"""
        for name, code, item in confirmed[:6]
    )
    cards = ""
    for row, image in zip(rows, images):
        structures = row["structures"]
        state = "；".join(
            f"{i + 1}.{item['pattern_cn']} · {item['state']} · {item['tilt']} "
            f"({item['start']}—{item['end']})"
            for i, item in enumerate(structures)
        ) or "无近期有效形态"
        state_en = "; ".join(
            f"{i + 1}. {item['pattern']} · "
            f"{'Forming' if item['state'] == '形成中' else 'Confirmed'} · "
            f"{item['direction_en']} ({item['start']}—{item['end']})"
            for i, item in enumerate(structures)
        ) or "No recent valid pattern"
        levels = "；".join(
            f"{i + 1} 上轨 {item['upper']:,.0f} / 下轨 {item['lower']:,.0f}"
            for i, item in enumerate(structures)
        ) or "暂无触发边界"
        levels_en = "; ".join(
            f"{i + 1} Upper {item['upper']:,.0f} / Lower {item['lower']:,.0f}"
            for i, item in enumerate(structures)
        ) or "No active trigger boundary"
        confidence = " / ".join(
            f"{item['confidence']:.3f}" for item in structures
        ) or "—"
        analysis = "".join(
            f"""<div class="analysis-row">
<div><b data-en="{attr(str(i + 1) + '. ' + item['pattern'])}">{i + 1}. {item['pattern_cn']}</b><span class="band {'high' if item['confidence'] >= 0.70 else ''}" data-en="{item['confidence_band_en']} confidence {item['confidence']:.3f}">{item['confidence_band']}置信度 {item['confidence']:.3f}</span></div>
<strong data-en="{attr(item['direction_en'])}">{item['direction']}</strong>
<p data-en="{attr(item['reminder_en'])}">{item['reminder']}</p>
</div>"""
            for i, item in enumerate(structures)
        ) or '<div class="analysis-row empty" data-en="No recent 4h structure passes the 0.55 threshold; no breakout direction is assigned.">当前没有达到0.55门槛的近期4h结构，暂不预设突破方向。</div>'
        cards += f"""<article class="card" id="contract-{row['code']}">
<div class="head"><div><h2 data-en="{PRODUCT_EN[row['name']]}">{row['name']}</h2><span data-en="{attr(state_en)}">{state}</span></div>
<div class="latest"><span data-en="Data through">数据至</span> {row['asof']}<br><b>{row['latest']:,.0f}</b></div></div>
<img src="data:image/png;base64,{image}" alt="{row['name']}4小时形态">
<div class="analysis">{analysis}</div>
<div class="foot"><span data-en="{attr(levels_en)}">{levels}</span><span data-en="Confidence {confidence}">置信度 {confidence}</span></div>
</article>"""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>4小时多品种形态扫描</title>
<style>
:root{{--bg:#070a0d;--panel:#11171c;--line:#28343c;--ink:#edf1f3;--muted:#8d9aa3;--gold:#f1c448}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth;scroll-padding-top:18px}}body{{margin:0;background:radial-gradient(circle at 80% 0,#17232a,transparent 36%),var(--bg);color:var(--ink);font-family:"PingFang SC","Noto Sans SC",sans-serif}}
main{{max-width:1800px;margin:auto;padding:28px}}header{{display:flex;justify-content:space-between;align-items:end;border-bottom:1px solid var(--line);padding-bottom:16px}}
h1{{margin:4px 0;font-size:30px}}.eyebrow{{color:var(--gold);font-weight:700;letter-spacing:.18em}}.muted{{color:var(--muted)}}
.header-tools{{display:flex;align-items:center;gap:12px}}.langsw{{display:flex;border:1px solid var(--line);border-radius:999px;padding:3px}}.langsw button{{border:0;background:none;color:var(--muted);padding:5px 9px;border-radius:999px;cursor:pointer;font-weight:700}}.langsw button[data-on="1"]{{background:var(--gold);color:#101417}}
.rule{{margin:18px 0;padding:13px 16px;border-left:4px solid var(--gold);background:#171a18;color:#d8d5c9;line-height:1.7}}
.summary{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0}}.kpi{{background:#11171c;border:1px solid var(--line);border-radius:12px;padding:14px}}.kpi b{{display:block;color:var(--gold);font-size:23px}}.kpi span{{color:var(--muted);font-size:12px}}
.watch-title{{display:flex;align-items:end;justify-content:space-between;margin:20px 2px 9px}}.watch-title h2{{margin:0;color:var(--ink);font-size:18px}}.watch-title span{{color:var(--muted);font-size:11px}}.watchlist{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:0 0 18px}}.watch{{display:block;background:#10171c;border:1px solid var(--line);border-top:3px solid #00bafa;border-radius:10px;padding:12px;color:inherit;text-decoration:none;transition:transform .16s,border-color .16s,box-shadow .16s}}.watch:hover{{transform:translateY(-2px);border-color:#00bafa;box-shadow:0 8px 24px #00aef31f}}.watch.confirmed{{border-top-color:#66747d;opacity:.88}}.watch.empty{{color:var(--muted)}}.watch>div,.analysis-row>div{{display:flex;justify-content:space-between;gap:8px;align-items:center}}.watch strong,.analysis-row strong{{display:block;color:#dce8eb;margin:8px 0 4px}}.watch small,.analysis-row p{{display:block;color:var(--muted);font-size:11px;line-height:1.65;margin:0}}.watch em{{display:block;color:#00bafa;font-size:10px;font-style:normal;margin-top:8px}}.band{{border:1px solid #41515b;border-radius:999px;padding:2px 7px;color:#aeb8be;font-size:10px;white-space:nowrap}}.band.high{{border-color:#b98c25;color:#f1c448;background:#312811}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;overflow:hidden;transition:border-color .2s,box-shadow .2s}}.card:target,.card.flash{{border-color:var(--gold);box-shadow:0 0 0 2px #f1c44855,0 18px 45px #0008}}
.card img{{width:100%;display:block;margin-top:10px;border-radius:8px}}.head,.foot{{display:flex;justify-content:space-between;gap:12px;align-items:center}}
h2{{margin:0 0 5px;color:var(--gold)}}.head span,.foot{{color:var(--muted);font-size:13px}}.latest{{text-align:right;color:var(--muted)}}.latest b{{color:var(--ink);font-size:19px}}
.analysis{{display:grid;gap:8px;margin:11px 0}}.analysis-row{{background:#0b1014;border-left:3px solid #00aef3;border-radius:7px;padding:10px 11px}}.analysis-row:first-child{{border-left-color:#ff505a}}.analysis-row.empty{{border-left-color:#52606a;color:var(--muted);font-size:12px}}
.foot{{border-top:1px solid var(--line);padding-top:11px}}footer{{margin-top:18px;color:var(--muted);font-size:12px}}
@media(max-width:1100px){{.watchlist{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:950px){{main{{padding:15px}}header{{display:block}}.grid,.summary,.watchlist{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><div><div class="eyebrow">WINDRISE · 4H SHAPE SCAN</div><h1 data-en="15 Key Contracts · 4-Hour Pattern Scan">15个重点品种 · 4小时形态扫描</h1></div><div class="header-tools"><div class="muted"><span data-en="Generated">生成于</span> {generated}</div><div class="langsw"><button data-lang="zh">中</button><button data-lang="en">EN</button></div></div></header>
<div class="rule" data-en="Method: 4-hour structures only; no 1h/2h overlays. Up to three recent, non-overlapping structures with confidence ≥{MIN_CONFIDENCE:.2f} are retained per contract. Red marks the primary structure; blue/gold mark secondary structures. Exchange update times differ, so use each card's data timestamp. A forming bias is not a trade signal; confirmation requires a completed 4h close beyond the boundary."><b>统一口径：</b>每个品种只扫描4小时周期，不叠加2h/1h结构；最多保留3个彼此不高度重叠、置信度不低于{MIN_CONFIDENCE:.2f}的近期结构。红色为主结构，蓝色/金色为次级结构。各交易所更新时间不同，以每张卡片“数据至”为准。形成中显示结构倾向，但不等同于交易信号，需等待4h收盘有效越过边界。</div>
<section class="summary"><div class="kpi"><b>{len(ranked)}</b><span data-en="Qualified 4h structures">合格4h结构</span></div><div class="kpi"><b>{high_count}</b><span data-en="High-confidence structures (≥0.70)">高置信度结构（≥0.70）</span></div><div class="kpi"><b>{forming_count}</b><span data-en="Forming; awaiting breakout confirmation">仍在形成，等待突破确认</span></div></section>
<div class="watch-title"><h2 data-en="Priority · Forming Structures">优先关注 · 待突破结构</h2><span data-en="Ranked by confidence; up to 12">按置信度排序，最多展示12项</span></div>
<section class="watchlist">{forming_cards}</section>
<div class="watch-title"><h2 data-en="Review · Confirmed Breakouts">其次复核 · 突破已确认</h2><span data-en="Check acceptance, retests and false breaks; up to 6">重点检查站稳、回踩与假突破，最多展示6项</span></div>
<section class="watchlist">{confirmed_cards}</section>
<section class="grid">{cards}</section>
<footer data-en="Confidence combines pivot clarity, channel geometry and pattern completeness; it is not a probability of gains or a historical win rate. Direction is conditional: forming structures wait for a completed 4h close beyond either boundary; confirmed structures require acceptance/retest checks. technical-analysis-chart-reading Skill assisted validation · ATR ZigZag pivots + strict geometry · Source: Sina main-continuous hourly bars aggregated to 4h.">置信度是识别器对枢轴清晰度、轨道几何与形态完整度的综合评分，不是上涨概率或历史胜率。方向提示采用条件化场景：形成中看上下轨谁先被4h收盘突破，已确认结构继续检查回踩与假突破。technical-analysis-chart-reading Skill辅助校验 · ATR ZigZag枢轴 + 严格轨道几何 · 数据源：新浪主力连续小时行情合成4h。</footer>
</main><script>
var lang=new URLSearchParams(location.search).get('lang')||localStorage.getItem('windrise_lang')||'zh';
var translatable=[].slice.call(document.querySelectorAll('[data-en]'));
translatable.forEach(function(el){{el.dataset.zh=el.textContent}});
function applyLang(next){{
  lang=next==='en'?'en':'zh';
  localStorage.setItem('windrise_lang',lang);
  document.documentElement.lang=lang==='en'?'en':'zh-CN';
  translatable.forEach(function(el){{el.textContent=lang==='en'?el.dataset.en:el.dataset.zh}});
  document.querySelectorAll('.langsw button').forEach(function(btn){{btn.dataset.on=btn.dataset.lang===lang?'1':'0'}});
  document.title=lang==='en'?'4-Hour Multi-Contract Pattern Scan':'4小时多品种形态扫描';
}}
document.querySelectorAll('.langsw button').forEach(function(btn){{btn.addEventListener('click',function(){{applyLang(btn.dataset.lang)}})}});
document.querySelectorAll('.watch[data-target]').forEach(function(link){{
  link.addEventListener('click',function(){{
    var card=document.getElementById(link.dataset.target);
    if(!card)return;
    document.querySelectorAll('.card.flash').forEach(function(el){{el.classList.remove('flash')}});
    card.classList.add('flash');
    window.setTimeout(function(){{card.classList.remove('flash')}},1800);
  }});
}});
applyLang(lang);
</script></body></html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate the 4-hour multi-product pattern report.")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()
    ymd = args.date.replace("-", "")
    rows = []
    images = []
    errors = []
    for name, code in PRODUCTS:
        try:
            hourly = fetch_hourly(code).tail(260)
            frame = compress_bars(hourly, 4)
            candidates = choose_candidates(frame)
            fig = plot_contract(name, frame, candidates)
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
            plt.close(fig)
            rows.append(serialize(name, code, frame, candidates))
            images.append(base64.b64encode(buffer.getvalue()).decode())
            print(name, [(item["pattern_cn"], item["state"]) for item in rows[-1]["structures"]])
        except Exception as exc:
            errors.append({"name": name, "error": str(exc)})
            print(name, "ERROR", exc)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    html_path = OUT / "多品种4小时形态扫描_本地试验.html"
    html_path.write_text(render_html(rows, images, generated), encoding="utf-8")
    json_path = OUT / "多品种4小时形态扫描_本地试验.json"
    json_path.write_text(json.dumps({
        "generated": generated,
        "timeframe": "4h_only",
        "products": rows,
        "errors": errors,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    formal_path = None
    if not args.local_only:
        formal_dir = ROOT / "日报" / ymd
        formal_dir.mkdir(parents=True, exist_ok=True)
        formal_path = formal_dir / f"期货形态_{ymd}.html"
        formal_path.write_text(render_html(rows, images, generated), encoding="utf-8")
    print(json.dumps({
        "html": str(html_path),
        "json": str(json_path),
        "formal_html": str(formal_path) if formal_path else None,
        "products": len(rows),
        "errors": errors,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
