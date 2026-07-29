#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""豆油多周期主形态本地样例：1h 为最小单位，主结构优先。"""

import base64
import io
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(HERE))

import chart_patterns as CP
from hourly_pattern_report import fetch_hourly


def line_through(a, b):
    x1, y1 = a
    x2, y2 = b
    slope = (y2 - y1) / (x2 - x1)
    return slope, y1 - slope * x1


def find_primary_triangle(df):
    """找已由小时收盘确认向上突破的最近高质量 H-L-H-L 对称三角。"""
    raw = df.reset_index(drop=True)
    atr = CP._atr(raw)
    pivots = CP._pivots(raw, atr, 2.25)
    candidates = []
    for i in range(len(pivots) - 3):
        points = pivots[i:i + 4]
        if [p[2] for p in points] != ["H", "L", "H", "L"]:
            continue
        h1, l1, h2, l2 = points
        if not (h2[1] < h1[1] and l2[1] > l1[1]):
            continue
        if not 12 <= l2[0] - h1[0] <= 80:
            continue
        upper = line_through((h1[0], h1[1]), (h2[0], h2[1]))
        lower = line_through((l1[0], l1[1]), (l2[0], l2[1]))
        start_width = upper[0] * h1[0] + upper[1] - (lower[0] * h1[0] + lower[1])
        end_width = upper[0] * l2[0] + upper[1] - (lower[0] * l2[0] + lower[1])
        if start_width <= 0 or end_width >= start_width:
            continue

        breakout = None
        for bar in range(l2[0] + 1, min(len(raw), l2[0] + 13)):
            boundary = upper[0] * bar + upper[1]
            if raw.iloc[bar]["close"] > boundary:
                breakout = bar
                break
        if breakout is None:
            continue

        height = h1[1] - l1[1]
        follow_end = min(len(raw), breakout + 25)
        follow = raw.iloc[breakout:follow_end]["high"].max() - raw.iloc[breakout]["close"]
        score = follow / max(height, 1) + 0.25 * (l2[0] / len(raw))
        candidates.append({
            "points": points,
            "upper": upper,
            "lower": lower,
            "breakout": breakout,
            "height": height,
            "score": score,
        })
    if not candidates:
        raise RuntimeError("未找到已确认突破的小时级对称三角")
    return max(candidates, key=lambda item: item["score"])


def internal_channel(df, primary):
    """用主形态第一段内部小时K拟合平行下降通道，作为次级结构。"""
    h1, l1, _, _ = primary["points"]
    start = h1[0] + 1
    end = l1[0]
    xs = np.arange(start, end + 1)
    closes = df.iloc[start:end + 1]["close"].to_numpy(dtype=float)
    slope, center_intercept = np.polyfit(xs, closes, 1)
    highs = df.iloc[start:end + 1]["high"].to_numpy(dtype=float)
    lows = df.iloc[start:end + 1]["low"].to_numpy(dtype=float)
    center = slope * xs + center_intercept
    upper_intercept = center_intercept + float(np.quantile(highs - center, 0.8))
    lower_intercept = center_intercept + float(np.quantile(lows - center, 0.2))
    return {
        "start": start,
        "end": end,
        "upper": (float(slope), upper_intercept),
        "lower": (float(slope), lower_intercept),
    }


def first_target_hit(df, primary):
    target = primary["upper"][0] * primary["breakout"] + primary["upper"][1] + primary["height"]
    for i in range(primary["breakout"], len(df)):
        if df.iloc[i]["high"] >= target:
            return i, target
    return None, target


def compress_bars(df, size):
    """按连续小时K合成上级周期，避免把夜盘和日盘空档误当成连续分钟。"""
    group = np.arange(len(df)) // size
    out = df.groupby(group).agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "hold": "last",
    })
    out.index = [df.index[min((i + 1) * size, len(df)) - 1] for i in range(len(out))]
    return out


def daily_bars(df):
    trading_day = pd.Series(df.index.date, index=df.index)
    out = df.groupby(trading_day).agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "hold": "last",
    })
    out.index = pd.to_datetime(out.index)
    return out


def trend_state(frame):
    close = frame["close"].astype(float)
    if len(close) < 20:
        return "样本不足"
    fast = close.ewm(span=min(10, len(close)), adjust=False).mean()
    slow = close.ewm(span=min(20, len(close)), adjust=False).mean()
    if close.iloc[-1] > fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-1] > fast.iloc[-4]:
        return "上行"
    if close.iloc[-1] < fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-1] < fast.iloc[-4]:
        return "下行"
    return "震荡"


def multi_timeframe_states(df):
    frames = {
        "1h": df,
        "2h": compress_bars(df, 2),
        "4h": compress_bars(df, 4),
        "日线": daily_bars(df),
    }
    return {name: trend_state(frame) for name, frame in frames.items()}


def plot_report(df, primary, channel):
    plt.rcParams["font.sans-serif"] = [
        "PingFang SC", "Hiragino Sans GB", "Arial Unicode MS", "DejaVu Sans"
    ]
    plt.rcParams["axes.unicode_minus"] = False

    h1, l1, h2, l2 = primary["points"]
    breakout = primary["breakout"]
    target_hit, target = first_target_hit(df, primary)
    left = max(0, h1[0] - 34)
    right = len(df) - 1
    sub = df.iloc[left:right + 1]
    x = np.arange(left, right + 1)

    fig = plt.figure(figsize=(16, 9), dpi=150, facecolor="#07090b")
    grid = fig.add_gridspec(5, 1, height_ratios=[4.8, 0.03, 0.95, 0.03, 0.95], hspace=0.04)
    ax = fig.add_subplot(grid[0])
    axv = fig.add_subplot(grid[2], sharex=ax)
    axo = fig.add_subplot(grid[4], sharex=ax)
    for axis in (ax, axv, axo):
        axis.set_facecolor("#07090b")
        axis.tick_params(colors="#aab2b9", labelsize=9)
        axis.grid(axis="y", color="#252b31", lw=0.6, alpha=0.72)
        for spine in axis.spines.values():
            spine.set_color("#3a2525")

    up_color, down_color = "#ee493d", "#00cbd0"
    for i, (_, row) in zip(x, sub.iterrows()):
        color = up_color if row["close"] >= row["open"] else down_color
        ax.vlines(i, row["low"], row["high"], color=color, lw=0.8, zorder=2)
        body_low = min(row["open"], row["close"])
        body_h = max(abs(row["close"] - row["open"]), 0.8)
        ax.add_patch(Rectangle((i - 0.30, body_low), 0.60, body_h,
                               facecolor=color, edgecolor=color, lw=0.5, zorder=3))

    for span, color, label, width in (
        (5, "#f4d03f", "MA5", 0.9),
        (20, "#e7e7e7", "MA20", 1.0),
        (60, "#ef3340", "MA60", 1.25),
    ):
        ma = df["close"].astype(float).rolling(span).mean().iloc[left:right + 1]
        ax.plot(x, ma, color=color, lw=width, alpha=0.9, label=label, zorder=3)

    line_end = min(right, breakout + 8)
    red_x = np.arange(h1[0], line_end + 1)
    upper_y = primary["upper"][0] * red_x + primary["upper"][1]
    lower_y = primary["lower"][0] * red_x + primary["lower"][1]
    ax.fill_between(red_x, lower_y, upper_y, color="#ff4d55", alpha=0.08, zorder=0)
    ax.plot(red_x, upper_y, color="#ff4d55", lw=3.0, zorder=5)
    ax.plot(red_x, lower_y, color="#ff4d55", lw=3.0, zorder=5)

    blue_x = np.arange(channel["start"], channel["end"] + 4)
    for key in ("upper", "lower"):
        k, b = channel[key]
        ax.plot(blue_x, k * blue_x + b, color="#00aef3", lw=2.0, zorder=4)

    labels = [
        (h1, "H1 主上轨 8488", "#ff646b", 12),
        (l1, "L1 主下轨 8363", "#ff646b", -18),
        (h2, "H2 8465", "#ff646b", 12),
        (l2, "L2 8393", "#ff646b", -18),
    ]
    for (bar, price, _), text, color, offset in labels:
        ax.scatter(bar, price, s=30, color=color, zorder=7)
        ax.annotate(text, (bar, price), xytext=(0, offset), textcoords="offset points",
                    ha="center", color=color, fontsize=9, fontweight="bold")

    breakout_price = float(df.iloc[breakout]["close"])
    ax.scatter(breakout, breakout_price, s=54, color="#f3c648", edgecolor="#fff4b0", zorder=8)
    ax.annotate(
        f"小时收盘确认突破\n{df.index[breakout]:%m-%d %H:%M}  {breakout_price:.0f}",
        (breakout, breakout_price), xytext=(20, 32), textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": "#f3c648", "lw": 1.4},
        color="#f3c648", fontsize=9, fontweight="bold",
        bbox={"boxstyle": "round,pad=0.35", "fc": "#171b20", "ec": "#7a652c", "alpha": 0.95},
    )

    ax.axhline(target, color="#e8b23d", ls="--", lw=1.1, alpha=0.85)
    ax.text(right + 0.5, target, f"量度目标 {target:.0f}", color="#e8b23d",
            va="center", fontsize=9)
    invalidation = l2[1]
    ax.axhline(invalidation, color="#d33c45", ls=":", lw=1.2)
    ax.text(right + 0.5, invalidation, f"结构失效 {invalidation:.0f}", color="#ff6670",
            va="center", fontsize=9)

    volumes = sub["volume"].astype(float)
    vol_colors = [up_color if c >= o else down_color for o, c in zip(sub["open"], sub["close"])]
    axv.bar(x, volumes, width=0.62, color=vol_colors, alpha=0.72)
    vol_ma = df["volume"].astype(float).rolling(20).mean().iloc[left:right + 1]
    axv.plot(x, vol_ma, color="#f3c648", lw=1.15)
    axv.set_ylabel("成交量\n黄线=20h均量", color="#aab2b9", fontsize=8)

    hold = sub["hold"].astype(float)
    axo.plot(x, hold, color="#d8d8d8", lw=1.25)
    axo.fill_between(x, hold.to_numpy(), hold.min(), color="#d8d8d8", alpha=0.08)
    axo.set_ylabel("持仓量 OI", color="#aab2b9", fontsize=8)

    tick_pos = np.linspace(left, right, 10, dtype=int)
    axo.set_xticks(tick_pos)
    axo.set_xticklabels([df.index[i].strftime("%m-%d\n%H:%M") for i in tick_pos])
    plt.setp(ax.get_xticklabels(), visible=False)
    plt.setp(axv.get_xticklabels(), visible=False)

    ax.set_xlim(left - 1, right + 9)
    y_pad = (sub["high"].max() - sub["low"].min()) * 0.08
    ax.set_ylim(sub["low"].min() - y_pad, sub["high"].max() + y_pad)
    ax.set_ylabel("价格（元/吨）", color="#aab2b9", fontsize=9)
    ax.set_title("豆油主力连续 · 多周期形态识别（1h为最小单位）", loc="left",
                 color="#f5c94d", fontsize=18, fontweight="bold", pad=16)
    ax.text(
        0.0, 1.01,
        "主图：1h连续盘面　|　红色：主结构　|　蓝色：内部结构（辅助）　|　上级周期：2h / 4h / 日线复核",
        transform=ax.transAxes, color="#c9d0d5", fontsize=10,
    )
    ax.legend(loc="upper right", frameon=False, ncol=3, fontsize=8,
              labelcolor="#cfd5d9", bbox_to_anchor=(0.84, 1.005))
    last = df.iloc[-1]
    current_box = (
        f"最新  {last['close']:.0f}\n"
        f"最高  {last['high']:.0f}\n"
        f"最低  {last['low']:.0f}\n"
        f"成交  {last['volume']:,.0f}\n"
        f"持仓  {last['hold']:,.0f}"
    )
    ax.text(
        1.015, 0.96, current_box, transform=ax.transAxes, va="top",
        color="#f0f2f3", fontsize=10, linespacing=1.75,
        bbox={"boxstyle": "square,pad=0.7", "fc": "#0c1013", "ec": "#5d1719", "lw": 1.0},
    )
    fig.text(
        0.86, 0.955, f"数据截至 {df.index[-1]:%Y-%m-%d %H:%M}",
        ha="right", color="#8f9aa3", fontsize=9,
    )
    fig.text(
        0.08, 0.018,
        "方法：1h最小观察单位（并扫描2h/4h/日线）→ ATR ZigZag枢轴 → 主结构优先 → 收盘确认 → 量仓验证。"
        "依据 technical-analysis-chart-reading Skill（Murphy框架）。",
        color="#7f8992", fontsize=8.5,
    )
    fig.subplots_adjust(left=0.08, right=0.86, top=0.90, bottom=0.08)
    return fig


def build_summary(df, primary):
    h1, l1, h2, l2 = primary["points"]
    breakout = primary["breakout"]
    breakout_row = df.iloc[breakout]
    vol_base = df["volume"].astype(float).rolling(20).mean().iloc[breakout - 1]
    volume_ratio = float(breakout_row["volume"] / vol_base) if vol_base else None
    oi_change = float(breakout_row["hold"] - df.iloc[l2[0]]["hold"])
    hit_bar, target = first_target_hit(df, primary)
    last = df.iloc[-1]
    return {
        "minimum_timeframe": "1小时",
        "timeframes_scanned": ["1h", "2h", "4h", "日线"],
        "timeframe_states": multi_timeframe_states(df),
        "report_frequency": "每交易日",
        "pattern": "对称三角",
        "primary_points": [
            {"role": "H1", "time": str(df.index[h1[0]]), "price": h1[1]},
            {"role": "L1", "time": str(df.index[l1[0]]), "price": l1[1]},
            {"role": "H2", "time": str(df.index[h2[0]]), "price": h2[1]},
            {"role": "L2", "time": str(df.index[l2[0]]), "price": l2[1]},
        ],
        "breakout_time": str(df.index[breakout]),
        "breakout_close": float(breakout_row["close"]),
        "volume_ratio_vs_20h": volume_ratio,
        "oi_change_from_l2": oi_change,
        "measured_target": float(target),
        "target_hit_time": str(df.index[hit_bar]) if hit_bar is not None else None,
        "invalidation": float(l2[1]),
        "latest_time": str(df.index[-1]),
        "latest_close": float(last["close"]),
    }


def render_html(summary, image_b64):
    ratio = summary["volume_ratio_vs_20h"]
    ratio_text = f"{ratio:.2f} 倍" if ratio is not None else "数据不足"
    oi_text = f"{summary['oi_change_from_l2']:+,.0f} 手"
    target_state = (
        f"已于 {summary['target_hit_time'][5:16]} 到达"
        if summary["target_hit_time"] else "尚未到达"
    )
    points = " / ".join(
        f"{item['role']} {item['price']:.0f}" for item in summary["primary_points"]
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>豆油多周期主形态 · 本地试验</title>
<style>
:root{{--bg:#080b0e;--panel:#10161b;--line:#28323a;--ink:#edf1f2;--muted:#8d9aa3;--gold:#f2c34c;--red:#ff5660;--blue:#00aef3}}
*{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 80% 0,#172128 0,transparent 34%),var(--bg);color:var(--ink);font-family:"PingFang SC","Noto Sans SC",sans-serif}}
main{{max-width:1500px;margin:auto;padding:34px}} header{{display:flex;justify-content:space-between;align-items:end;border-bottom:1px solid var(--line);padding-bottom:18px}}
h1{{margin:0;font-size:30px}} .eyebrow{{color:var(--gold);letter-spacing:.22em;font-weight:700;margin-bottom:8px}} .asof{{color:var(--muted)}}
.hero{{margin-top:22px;border:1px solid var(--line);background:#06090b;border-radius:16px;overflow:hidden}} .hero img{{display:block;width:100%}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}} .metric{{background:var(--panel);border:1px solid var(--line);padding:18px;border-radius:12px}}
.metric span{{display:block;color:var(--muted);font-size:13px;margin-bottom:7px}} .metric strong{{font-size:22px}}
.analysis{{display:grid;grid-template-columns:1.3fr 1fr;gap:16px}} .card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:22px}}
h2{{font-size:18px;margin:0 0 14px;color:var(--gold)}} p{{color:#cbd2d6;line-height:1.8;margin:8px 0}} b{{color:#fff}}
.red{{color:var(--red)}} .blue{{color:var(--blue)}} .rule{{padding:10px 0;border-bottom:1px solid #202a31}} .rule:last-child{{border:0}}
footer{{color:var(--muted);font-size:12px;margin-top:18px}}
@media(max-width:850px){{main{{padding:18px}}header{{display:block}}.asof{{margin-top:10px}}.grid{{grid-template-columns:1fr 1fr}}.analysis{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><div><div class="eyebrow">WINDRISE · LOCAL PROTOTYPE</div><h1>豆油 · 多周期主形态识别</h1></div><div class="asof">1h为最小单位 · 2h / 4h / 日线复核 · 数据截至 {summary['latest_time'][:16]} · 未部署</div></header>
<section class="grid">
<div class="metric"><span>主形态</span><strong class="red">对称三角 · 向上突破</strong></div>
<div class="metric"><span>四个主转折点</span><strong>{points}</strong></div>
<div class="metric"><span>突破时成交量 / 前20小时均量</span><strong>{ratio_text}</strong></div>
<div class="metric"><span>自 L2 起持仓变化</span><strong>{oi_text}</strong></div>
</section>
<section class="hero"><img src="data:image/png;base64,{image_b64}" alt="豆油多周期主形态图"></section>
<section class="analysis">
<article class="card"><h2>结论怎么读</h2>
<p><b class="red">红色主结构：</b>在最小观察层 1h 上，H1 与 H2 形成下降上轨，L1 与 L2 形成上升下轨，波动区间持续收窄，因此识别为小时级对称三角。{points}。</p>
<p><b class="blue">蓝色内部结构：</b>主三角内部曾出现短下降通道，它解释整理过程，但级别更小，不能替代红色主结构，也不能单独决定交易方向。</p>
<p><b>确认：</b>{summary['breakout_time'][5:16]} 的 60 分钟 K 线收于 {summary['breakout_close']:.0f}，站上当时上轨，才把“候选形态”升级为“向上突破”；盘中刺穿不算确认。</p>
<p><b>验证结果：</b>量度目标约 {summary['measured_target']:.0f}，{target_state}。这是已完成形态的复盘示范，不等于当前重新追多信号。</p>
</article>
<article class="card"><h2>Skill 证据链</h2>
<div class="rule"><b>1. 多周期复核</b><p>1h {summary['timeframe_states']['1h']} · 2h {summary['timeframe_states']['2h']} · 4h {summary['timeframe_states']['4h']} · 日线 {summary['timeframe_states']['日线']}。上级周期用于确认或揭示矛盾，不把多套形态线堆在主图上。</p></div>
<div class="rule"><b>2. 趋势与结构优先</b><p>先识别红色主三角，再看蓝色内部通道；均线用于辅助读盘，不替代价格结构。</p></div>
<div class="rule"><b>3. 量仓确认</b><p>突破小时成交量为前 20 个已完成小时均量的 {ratio_text}；从 L2 到突破小时，持仓量变化 {oi_text}。OI 只说明参与变化，本身不直接代表多空。</p></div>
<div class="rule"><b>4. 失效条件</b><p>若突破后重新跌破并收于 L2 结构低点 {summary['invalidation']:.0f} 下方，主三角的多头解释失效。</p></div>
</article>
</section>
<footer>识别框架：technical-analysis-chart-reading Skill（Murphy 风格）· 1h为最小识别单位，2h/4h/日线复核 · 数据：新浪财经主力连续 OHLCV/OI · 仅作形态研究演示。</footer>
</main></body></html>"""


def main():
    df = fetch_hourly("y0").tail(250)
    primary = find_primary_triangle(df)
    channel = internal_channel(df, primary)
    summary = build_summary(df, primary)
    fig = plot_report(df, primary, channel)

    png = OUT / "豆油多周期主形态_本地试验.png"
    fig.savefig(png, facecolor=fig.get_facecolor(), bbox_inches="tight")
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    image_b64 = base64.b64encode(buffer.getvalue()).decode()

    html = OUT / "豆油多周期主形态_本地试验.html"
    html.write_text(render_html(summary, image_b64), encoding="utf-8")
    (OUT / "豆油多周期主形态_本地试验.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"html": str(html), "png": str(png), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
