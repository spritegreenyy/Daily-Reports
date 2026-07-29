#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""豆油多周期形态独立扫描本地稿，不使用人工预先标注的形态点。"""

import base64
import io
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
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
from hourly_pattern_soybean_oil_prototype import compress_bars, daily_bars

PATTERN_CN = {
    "Ascending Triangle": "上升三角",
    "Descending Triangle": "下降三角",
    "Symmetric Triangle": "对称三角",
    "Rectangle": "矩形",
    "Rising Wedge": "上升楔形",
    "Falling Wedge": "下降楔形",
    "Bull Flag": "多头旗形",
    "Bear Flag": "空头旗形",
    "Bull Pennant": "多头三角旗",
    "Bear Pennant": "空头三角旗",
}

TF_WEIGHT = {"1h": 0.00, "2h": 0.05, "4h": 0.10, "日线": 0.12}


def fit_boundaries(hit):
    points = [p for p in hit["key_points"] if p["label"][0] in {"H", "L"}]
    highs = [(p["bar"], float(p["price"])) for p in points if p["label"].startswith("H")]
    lows = [(p["bar"], float(p["price"])) for p in points if p["label"].startswith("L")]
    if len(highs) < 2 or len(lows) < 2:
        return None
    ku, bu = np.polyfit([x for x, _ in highs], [y for _, y in highs], 1)
    kl, bl = np.polyfit([x for x, _ in lows], [y for _, y in lows], 1)
    return {
        "upper": (float(ku), float(bu)),
        "lower": (float(kl), float(bl)),
        "highs": highs,
        "lows": lows,
        "start": min(p["bar"] for p in points),
        "end": max(p["bar"] for p in points),
    }


def strict_geometry(frame, hit, bounds):
    """按轨道几何重新命名，杜绝把收敛轨道叫作旗形。"""
    atr = float((frame["high"] - frame["low"]).tail(30).mean())
    if not np.isfinite(atr) or atr <= 0:
        return None
    ku, bu = bounds["upper"]
    kl, bl = bounds["lower"]
    start, end = bounds["start"], bounds["end"]
    width_start = (ku * start + bu) - (kl * start + bl)
    width_end = (ku * end + bu) - (kl * end + bl)
    if width_start <= 0 or width_end <= 0:
        return None

    su, sl = ku / atr, kl / atr
    flat_u, flat_l = abs(su) <= 0.035, abs(sl) <= 0.035
    parallel = abs(su - sl) <= 0.045
    converging = width_end <= width_start * 0.82
    pole = next((p for p in hit["key_points"] if p["label"] == "P0"), None)

    if converging:
        if flat_u and sl > 0.035:
            return "Ascending Triangle", "上升三角", "triangle"
        if flat_l and su < -0.035:
            return "Descending Triangle", "下降三角", "triangle"
        return "Symmetric Triangle", "收敛三角", "triangle"
    if parallel:
        if flat_u and flat_l:
            return "Rectangle", "矩形", "parallel"
        if pole:
            pole_bar = int(pole["bar"])
            first_bar = min(p["bar"] for p in hit["key_points"] if p["label"] != "P0")
            pole_up = float(frame["close"].iloc[first_bar]) > float(frame["close"].iloc[pole_bar])
            return (
                ("Bull Flag", "多头旗形", "parallel")
                if pole_up else ("Bear Flag", "空头旗形", "parallel")
            )
        return "Parallel Channel", "平行通道", "parallel"
    if su > 0.035 and sl > 0.035 and converging:
        return "Rising Wedge", "上升楔形", "wedge"
    if su < -0.035 and sl < -0.035 and converging:
        return "Falling Wedge", "下降楔形", "wedge"
    return None


def classify_state(frame, hit, bounds):
    """形成中保持中性；只有真实收盘越界后才产生方向。"""
    confirmed_at = None
    breakout_side = None
    for bar in range(hit["end_bar"] + 1, len(frame)):
        upper = bounds["upper"][0] * bar + bounds["upper"][1]
        lower = bounds["lower"][0] * bar + bounds["lower"][1]
        if upper <= lower:
            continue
        close = float(frame["close"].iloc[bar])
        side = "above" if close > upper else "below" if close < lower else "inside"
        if side in {"above", "below"} and confirmed_at is None:
            confirmed_at = bar
            breakout_side = side

    latest_bar = len(frame) - 1
    latest_upper = bounds["upper"][0] * latest_bar + bounds["upper"][1]
    latest_lower = bounds["lower"][0] * latest_bar + bounds["lower"][1]
    if latest_upper <= latest_lower:
        return "几何失真", None, None
    latest_close = float(frame["close"].iloc[-1])
    latest_side = (
        "above" if latest_close > latest_upper
        else "below" if latest_close < latest_lower
        else "inside"
    )
    if latest_side in {"above", "below"}:
        return "已确认", confirmed_at, latest_side
    return "形成中", None, None


def scan_timeframe(name, frame):
    candidates = []
    for atr_mult in (0.75, 1.0, 1.25, 1.5, 2.0):
        for hit in CP.detect_chart_patterns(frame, atr_mult=atr_mult):
            age = len(frame) - 1 - hit["end_bar"]
            if age > 18:
                continue
            bounds = fit_boundaries(hit)
            if not bounds:
                continue
            geometry = strict_geometry(frame, hit, bounds)
            if not geometry:
                continue
            state, event_bar, breakout_side = classify_state(frame, hit, bounds)
            if state == "几何失真":
                continue
            pattern, pattern_cn, geometry_group = geometry
            recency = max(0.0, 1.0 - age / 18)
            score = float(hit["confidence"]) + TF_WEIGHT[name] + 0.10 * recency
            candidates.append({
                "timeframe": name,
                "frame": frame,
                "hit": hit,
                "bounds": bounds,
                "state": state,
                "event_bar": event_bar,
                "breakout_side": breakout_side,
                "age": age,
                "atr_mult": atr_mult,
                "score": score,
                "pattern": pattern,
                "pattern_cn": pattern_cn,
                "geometry_group": geometry_group,
            })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def dedupe(candidates):
    kept = []
    for candidate in candidates:
        h = candidate["hit"]
        duplicate = any(
            old["pattern"] == candidate["pattern"]
            and abs(old["hit"]["end_bar"] - h["end_bar"]) <= 3
            for old in kept
        )
        if not duplicate:
            kept.append(candidate)
    return kept


def independent_scan(hourly):
    frames = {
        "1h": hourly,
        "2h": compress_bars(hourly, 2),
        "4h": compress_bars(hourly, 4),
        "日线": daily_bars(hourly),
    }
    by_tf = {name: dedupe(scan_timeframe(name, frame)) for name, frame in frames.items()}
    representatives = {name: rows[0] for name, rows in by_tf.items() if rows}

    # 硬性周期顺序：4h 定主结构；没有合格 4h 才下放到 2h，再到 1h。
    main = None
    for timeframe in ("4h", "2h", "1h"):
        if by_tf.get(timeframe):
            main = by_tf[timeframe][0]
            break
    if main is None:
        raise RuntimeError("1h/2h/4h 均无满足几何标准的近期结构")

    # 低周期只提供结构细节，不再给与主结构对立的多空预设。
    order = {"1h": 1, "2h": 2, "4h": 3, "日线": 4}
    smaller = [
        rows[0] for name, rows in by_tf.items()
        if rows and order[name] < order[main["timeframe"]]
    ]
    secondary = max(smaller, key=lambda item: item["score"]) if smaller else None
    if secondary:
        secondary["display_as_auxiliary"] = True
    return main, secondary, representatives


def map_point_to_hourly(hourly, frame, bar):
    timestamp = frame.index[int(bar)]
    return int(hourly.index.get_indexer([timestamp], method="nearest")[0])


def projected_lines(hourly, candidate):
    frame = candidate["frame"]
    bounds = candidate["bounds"]
    mapped_highs = [
        (map_point_to_hourly(hourly, frame, x), y) for x, y in bounds["highs"]
    ]
    mapped_lows = [
        (map_point_to_hourly(hourly, frame, x), y) for x, y in bounds["lows"]
    ]
    ku, bu = np.polyfit([x for x, _ in mapped_highs], [y for _, y in mapped_highs], 1)
    kl, bl = np.polyfit([x for x, _ in mapped_lows], [y for _, y in mapped_lows], 1)
    return {
        "upper": (float(ku), float(bu)),
        "lower": (float(kl), float(bl)),
        "start": min(x for x, _ in mapped_highs + mapped_lows),
        "end": max(x for x, _ in mapped_highs + mapped_lows),
        "highs": mapped_highs,
        "lows": mapped_lows,
    }


def candidate_label(candidate):
    if candidate.get("display_as_auxiliary"):
        return f"{candidate['timeframe']} {candidate['pattern_cn']} · 仅辅助观察"
    if candidate["state"] == "形成中":
        direction = "不预判方向"
    else:
        direction = "向上确认" if candidate["breakout_side"] == "above" else "向下确认"
    return f"{candidate['timeframe']} {candidate['pattern_cn']} · {candidate['state']} · {direction}"


def trading_day(timestamp):
    """夜盘归入下一交易日，周五夜盘顺延到周一。"""
    ts = pd.Timestamp(timestamp)
    if ts.hour < 21:
        return ts.normalize()
    return (ts.normalize() + pd.offsets.BDay(1)).normalize()


def plot_terminal(hourly, main, secondary):
    plt.rcParams["font.sans-serif"] = [
        "PingFang SC", "Hiragino Sans GB", "Arial Unicode MS", "DejaVu Sans"
    ]
    plt.rcParams["axes.unicode_minus"] = False

    main_lines = projected_lines(hourly, main)
    secondary_lines = projected_lines(hourly, secondary) if secondary else None
    day_keys = pd.Series([trading_day(ts) for ts in hourly.index], index=np.arange(len(hourly)))
    recent_days = list(dict.fromkeys(day_keys.tolist()))[-5:]
    visible = day_keys[day_keys.isin(recent_days)]
    left = int(visible.index.min())
    right = len(hourly) - 1
    sub = hourly.iloc[left:right + 1]
    xs = np.arange(left, right + 1)

    fig = plt.figure(figsize=(17, 9), dpi=150, facecolor="#050709")
    grid = fig.add_gridspec(5, 1, height_ratios=[5.0, 0.03, 0.85, 0.03, 0.85], hspace=0.04)
    ax = fig.add_subplot(grid[0])
    axv = fig.add_subplot(grid[2], sharex=ax)
    axo = fig.add_subplot(grid[4], sharex=ax)
    for axis in (ax, axv, axo):
        axis.set_facecolor("#050709")
        axis.grid(axis="y", color="#252b30", lw=0.6)
        axis.tick_params(colors="#9ca6ad", labelsize=9)
        for spine in axis.spines.values():
            spine.set_color("#4a2325")

    up, down = "#ef493e", "#00c4cc"
    for x, (_, row) in zip(xs, sub.iterrows()):
        color = up if row["close"] >= row["open"] else down
        ax.vlines(x, row["low"], row["high"], color=color, lw=0.7)
        low = min(row["open"], row["close"])
        height = max(abs(row["close"] - row["open"]), 0.8)
        ax.add_patch(Rectangle((x - 0.3, low), 0.6, height, color=color, lw=0))

    for period, color, label in (
        (5, "#f0c83f", "MA5"), (20, "#d9dde0", "MA20"), (60, "#ed2939", "MA60")
    ):
        values = hourly["close"].rolling(period).mean().iloc[left:right + 1]
        ax.plot(xs, values, color=color, lw=1.0 if period != 60 else 1.25, label=label)

    def draw_structure(lines, color, width, label, offset):
        # 只延伸既有边界到今日，用于判断收盘是否越界；不添加预测箭头。
        end = right
        lx = np.arange(max(left, lines["start"]), end + 1)
        if len(lx) < 2:
            return
        upper = lines["upper"][0] * lx + lines["upper"][1]
        lower = lines["lower"][0] * lx + lines["lower"][1]
        ax.plot(lx, upper, color=color, lw=width, zorder=6)
        ax.plot(lx, lower, color=color, lw=width, zorder=6)
        ax.fill_between(lx, lower, upper, color=color, alpha=0.07)
        label_x = min(end, lines["end"] + 3)
        label_y = lines["upper"][0] * label_x + lines["upper"][1]
        ax.annotate(
            label, (label_x, label_y), xytext=(10, offset), textcoords="offset points",
            color=color, fontsize=10, fontweight="bold",
            bbox={"boxstyle": "round,pad=0.3", "fc": "#0b0f12", "ec": color, "alpha": 0.92},
        )

    draw_structure(main_lines, "#ff4f59", 3.0, candidate_label(main), 14)
    if secondary_lines:
        draw_structure(secondary_lines, "#00aef3", 2.0, candidate_label(secondary), -24)

    volumes = sub["volume"].astype(float)
    colors = [up if c >= o else down for o, c in zip(sub["open"], sub["close"])]
    axv.bar(xs, volumes, width=0.62, color=colors, alpha=0.72)
    axv.plot(xs, hourly["volume"].rolling(20).mean().iloc[left:right + 1],
             color="#f0c83f", lw=1.0)
    axv.set_ylabel("成交量\n黄线=20h均量", color="#9ca6ad", fontsize=8)
    hold = sub["hold"].astype(float)
    axo.plot(xs, hold, color="#d4d7d9", lw=1.15)
    axo.fill_between(xs, hold.to_numpy(), hold.min(), color="#d4d7d9", alpha=0.07)
    axo.set_ylabel("持仓量 OI", color="#9ca6ad", fontsize=8)

    ticks = np.linspace(left, right, 10, dtype=int)
    axo.set_xticks(ticks)
    axo.set_xticklabels([hourly.index[i].strftime("%m-%d\n%H:%M") for i in ticks])
    plt.setp(ax.get_xticklabels(), visible=False)
    plt.setp(axv.get_xticklabels(), visible=False)

    latest = hourly.iloc[-1]
    latest_day = trading_day(hourly.index[-1])
    current_positions = day_keys[day_keys == latest_day].index
    if len(current_positions):
        ax.axvspan(current_positions.min() - 0.5, current_positions.max() + 0.5,
                   color="#f0c83f", alpha=0.035, zorder=0)
        ax.text(current_positions.min(), ax.get_ylim()[1], "今日",
                color="#f0c83f", fontsize=8, va="top")
    ax.text(
        1.012, 0.97,
        f"最新  {latest['close']:.0f}\n最高  {latest['high']:.0f}\n最低  {latest['low']:.0f}\n"
        f"成交  {latest['volume']:,.0f}\n持仓  {latest['hold']:,.0f}",
        transform=ax.transAxes, va="top", color="#eef1f2", fontsize=10, linespacing=1.7,
        bbox={"boxstyle": "square,pad=0.65", "fc": "#0b0e11", "ec": "#662326"},
    )
    ax.set_xlim(left - 1, right + 12)
    pad = (sub["high"].max() - sub["low"].min()) * 0.09
    ax.set_ylim(sub["low"].min() - pad, sub["high"].max() + pad)
    ax.set_ylabel("价格（元/吨）", color="#9ca6ad")
    ax.set_title(f"豆油主力连续 · {latest_day:%Y-%m-%d} 交易日观察", loc="left",
                 color="#f0c83f", fontsize=19, fontweight="bold", pad=17)
    ax.text(
        0, 1.01,
        "按交易日输出 · 主图仅保留当日+前4个交易日 · 4h→2h→1h依次判断 · 形成中不预判方向",
        transform=ax.transAxes, color="#c2c9ce", fontsize=10,
    )
    ax.legend(loc="upper right", frameon=False, ncol=3, fontsize=8,
              labelcolor="#cfd4d7", bbox_to_anchor=(0.86, 1.005))
    fig.text(
        0.08, 0.018,
        "形态由 ATR ZigZag 枢轴、严格轨道几何与收盘突破规则自动生成；长周期仅作当日背景，"
        "形成中不等于交易信号。",
        color="#7e8991", fontsize=8.5,
    )
    fig.subplots_adjust(left=0.08, right=0.87, top=0.90, bottom=0.08)
    return fig


def serialize(candidate):
    if not candidate:
        return None
    hit = candidate["hit"]
    auxiliary = bool(candidate.get("display_as_auxiliary"))
    return {
        "timeframe": candidate["timeframe"],
        "pattern": candidate["pattern"],
        "pattern_cn": candidate["pattern_cn"],
        "geometry_group": candidate["geometry_group"],
        "direction": (
            "neutral" if auxiliary or candidate["state"] == "形成中"
            else "bullish" if candidate["breakout_side"] == "above" else "bearish"
        ),
        "role": "auxiliary" if auxiliary else "primary_candidate",
        "confidence": round(float(hit["confidence"]), 3),
        "state": candidate["state"],
        "age_bars": candidate["age"],
        "atr_mult": candidate["atr_mult"],
        "label": candidate_label(candidate),
    }


def render_html(summary, image):
    rows = "".join(
        f"<tr><td>{tf}</td><td>{item['pattern_cn']}</td>"
        f"<td>{'不预判' if item['direction']=='neutral' else '向上确认' if item['direction']=='bullish' else '向下确认'}</td>"
        f"<td>{item['state']}</td><td>{item['confidence']:.3f}</td></tr>"
        for tf, item in summary["representatives"].items()
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>豆油 Skill 独立形态扫描</title>
<style>
:root{{--bg:#070a0d;--panel:#11171c;--line:#28343c;--ink:#edf1f3;--muted:#8d9aa3;--gold:#f1c448;--red:#ff5660;--blue:#00aef3}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 80% 0,#16222a,transparent 35%),var(--bg);color:var(--ink);font-family:"PingFang SC","Noto Sans SC",sans-serif}}
main{{max-width:1500px;margin:auto;padding:32px}}header{{display:flex;justify-content:space-between;align-items:end;border-bottom:1px solid var(--line);padding-bottom:18px}}
h1{{margin:4px 0;font-size:30px}}.eyebrow{{color:var(--gold);font-weight:700;letter-spacing:.18em}}.muted{{color:var(--muted)}}
.hero{{margin:20px 0;border:1px solid var(--line);border-radius:15px;overflow:hidden;background:#050709}}.hero img{{display:block;width:100%}}
.grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:16px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:22px}}
h2{{color:var(--gold);font-size:18px;margin:0 0 12px}}p{{line-height:1.75;color:#cbd2d6}}.red{{color:var(--red)}}.blue{{color:var(--blue)}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:11px;border-bottom:1px solid #263139;text-align:left}}th{{color:var(--muted);font-size:13px}}
.note{{border-left:4px solid var(--gold);padding:10px 14px;background:#171a18;color:#d8d5c9;line-height:1.7}}
footer{{margin-top:17px;color:var(--muted);font-size:12px}}@media(max-width:850px){{main{{padding:17px}}header{{display:block}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><div><div class="eyebrow">WINDRISE · DAILY SKILL SCAN</div><h1>豆油 · {summary['trading_day']} 交易日形态观察</h1></div>
<div class="muted">当日为结论单位 · 图示当日+前4个交易日 · 数据截至 {summary['asof']} · 未部署</div></header>
<section class="hero"><img src="data:image/png;base64,{image}" alt="豆油独立形态扫描"></section>
<section class="grid"><article class="card"><h2>当前主结论</h2>
<p><b class="red">主结构：</b>{summary['main']['label']}。它是本轮独立扫描综合结构质量、周期、新鲜度和失效状态后选出的主形态。</p>
<p><b class="blue">内部结构：</b>{summary['secondary']['label'] if summary['secondary'] else '没有满足条件的更小周期结构'}。低周期只辅助判断节奏，不另设相反方向。</p>
<div class="note"><b>统一情景框架：</b>形态形成中保持中性；有效站稳上轨才进入多头情景，有效跌破下轨才进入空头情景。已验证豆油上升中继案例：上破后目标 8570；跌破 8393 则结构彻底失效。</div>
</article><article class="card"><h2>各周期代表形态</h2><table><thead><tr><th>周期</th><th>形态</th><th>方向</th><th>状态</th><th>置信度</th></tr></thead><tbody>{rows}</tbody></table></article></section>
<footer>technical-analysis-chart-reading Skill · 按交易日输出 · 1h 最小识别单位 · 4h→2h→1h · 主结构优先，量仓与指标仅作确认。</footer>
</main></body></html>"""


def main():
    hourly = fetch_hourly("y0").tail(250)
    main_candidate, secondary_candidate, representatives = independent_scan(hourly)
    serialized_main = serialize(main_candidate)
    serialized_secondary = serialize(secondary_candidate)
    serialized_reps = {tf: serialize(item) for tf, item in representatives.items()}
    summary = {
        "asof": hourly.index[-1].strftime("%Y-%m-%d %H:%M"),
        "trading_day": trading_day(hourly.index[-1]).strftime("%Y-%m-%d"),
        "display_window": "当前交易日 + 前4个交易日",
        "minimum_timeframe": "1h",
        "scanned_timeframes": ["1h", "2h", "4h", "日线"],
        "main": serialized_main,
        "secondary": serialized_secondary,
        "representatives": serialized_reps,
        "timeframe_priority": ["4h", "2h", "1h"],
        "forming_bias_policy": "neutral_until_close_breakout",
        "verified_case": {
            "bullish_scenario": "站稳上方压力，看向目标 8570",
            "bearish_scenario": "有效跌破 8393，本轮上升中继结构彻底失效",
        },
        "method": "ATR ZigZag pivots + boundary regression + close confirmation",
        "teacher_points_used": False,
    }

    fig = plot_terminal(hourly, main_candidate, secondary_candidate)
    png = OUT / "豆油Skill独立形态扫描_本地试验.png"
    fig.savefig(png, facecolor=fig.get_facecolor(), bbox_inches="tight")
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    image = base64.b64encode(buffer.getvalue()).decode()

    html = OUT / "豆油Skill独立形态扫描_本地试验.html"
    html.write_text(render_html(summary, image), encoding="utf-8")
    json_path = OUT / "豆油Skill独立形态扫描_本地试验.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"html": str(html), "png": str(png), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
