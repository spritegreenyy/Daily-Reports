#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小时级形态识别日报(本地版 2026-07-07, 服务器重装后重建): 15个重点品种 + 商品综合/工业品指数。
引擎: 本目录 chart_patterns.py(枢轴几何法, 本地重写)。
每品种取小时K → 识别近端最高置信度主形态 → 方向/颈线触发位/目标/止损/可信度档位 + 小时K图。
输出 output/hourly_pattern_report.{html,pdf,json}; 交互网页由 日报站/make_pattern_web.py 读 json 生成。
"""
import sys, os, json, base64, io, math, signal
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
import akshare as ak
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import chart_patterns as CP
from pattern_research import enrich_pattern, market_context, walk_forward_backtest

HERE = Path(__file__).parent
OUT = str(HERE / "output")
Path(OUT).mkdir(exist_ok=True)


class _Timeout(Exception):
    pass


class deadline:
    """单次取数超时保护(SIGALRM), 防 akshare/天勤 网络挂死拖垮整份报告。仅主线程有效。"""
    def __init__(self, secs):
        self.secs = secs

    def __enter__(self):
        self._old = signal.signal(signal.SIGALRM, self._raise)
        signal.alarm(self.secs)

    def __exit__(self, *a):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self._old)

    def _raise(self, *a):
        raise _Timeout("timeout")


# 15 重点品种 (老师2026-06-24指定) -> 新浪主力连续代码
VARIETIES = [
    ("原油", "sc0"), ("黄金", "au0"), ("白银", "ag0"), ("铜", "cu0"), ("铝", "al0"),
    ("锌", "zn0"), ("锡", "sn0"), ("碳酸锂", "lc0"), ("多晶硅", "ps0"), ("棕榈油", "p0"),
    ("豆油", "y0"), ("豆粕", "m0"), ("PTA", "ta0"), ("甲醇", "ma0"), ("PP", "pp0"),
]
INDUSTRIAL = ["铜", "铝", "锌", "锡", "碳酸锂", "多晶硅", "PTA", "甲醇", "PP"]  # 工业品篮子
SECTORS = {
    "能源": ["原油"],
    "贵金属": ["黄金", "白银"],
    "有色及新能源": ["铜", "铝", "锌", "锡", "碳酸锂", "多晶硅"],
    "油脂油料": ["棕榈油", "豆油", "豆粕"],
    "化工": ["PTA", "甲醇", "PP"],
}
# 指数底层走天勤主力连续(品种名 -> 天勤合约)
TQ_SYM = {
    "原油": "KQ.m@INE.sc", "黄金": "KQ.m@SHFE.au", "白银": "KQ.m@SHFE.ag",
    "铜": "KQ.m@SHFE.cu", "铝": "KQ.m@SHFE.al", "锌": "KQ.m@SHFE.zn", "锡": "KQ.m@SHFE.sn",
    "碳酸锂": "KQ.m@GFEX.lc", "多晶硅": "KQ.m@GFEX.ps", "棕榈油": "KQ.m@DCE.p",
    "豆油": "KQ.m@DCE.y", "豆粕": "KQ.m@DCE.m", "PTA": "KQ.m@CZCE.TA",
    "甲醇": "KQ.m@CZCE.MA", "PP": "KQ.m@DCE.pp",
}
TQ_CONF = str(Path.home() / ".tqsdk_auth.json")  # {"user":..,"pass":..}; 也可用环境变量 TQSDK_USER/TQSDK_PASS

WIN = 250          # 分析窗口(小时K根数)
MORPH_WINDOWS = (120, 160, 200, 250)  # 华创式截面聚合: 每个观察窗口独立投一票
RECENT_BARS = 45   # 形态右端在最近这么多根内 = 近端/可操作
WATCH_BARS = 90    # 46-90根保留为延长观察，只展示、不进入交易准入
CONF_MIN = 0.74    # 门槛(抵消"每品种取最优窗口"的选择偏差, 对齐原版6-8个的选择性); 老师要求只留高置信度
# 只保留 三角/矩形/楔形/旗形 (老师2026-06-24要求)
KEEP_PATTERNS = {"Ascending Triangle", "Descending Triangle", "Symmetric Triangle",
                 "Rectangle", "Rising Wedge", "Falling Wedge",
                 "Bull Flag", "Bear Flag", "Bull Pennant", "Bear Pennant"}
PAT_CN = {
    "Ascending Triangle": "上升三角", "Descending Triangle": "下降三角",
    "Symmetric Triangle": "对称三角", "Rectangle": "矩形", "Rising Wedge": "上升楔形",
    "Falling Wedge": "下降楔形", "Bull Flag": "多头旗形", "Bear Flag": "空头旗形",
    "Bull Pennant": "多头三角旗", "Bear Pennant": "空头三角旗",
}
BIAS_CN = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}


def tq_fetch(names):
    """从天勤取这些品种的主力连续小时K, 返回 {品种名: df(CST索引,OHLCV)}; 失败/无凭证返回 {}。"""
    user = os.environ.get("TQSDK_USER")
    pwd = os.environ.get("TQSDK_PASS")
    if not (user and pwd):
        try:
            c = json.load(open(TQ_CONF)); user, pwd = c.get("user"), c.get("pass")
        except Exception:
            return {}
    if not (user and pwd):
        return {}
    try:
        from tqsdk import TqApi, TqAuth
        api = TqApi(auth=TqAuth(user, pwd))
    except Exception as e:
        print("天勤连接失败:", str(e)[:80]); return {}
    out = {}
    try:
        refs = {n: api.get_kline_serial(TQ_SYM[n], 3600, data_length=WIN + 60) for n in names if n in TQ_SYM}
        for n, k in refs.items():
            k = k.dropna(subset=["close"]).copy()
            if len(k) < 60:
                continue
            cols = ["open", "high", "low", "close", "volume"]
            if "open_oi" in k.columns:
                cols.append("open_oi")
            df = k[cols].copy()
            if "open_oi" in df.columns:
                df = df.rename(columns={"open_oi": "hold"})
            df.index = pd.to_datetime(k["datetime"]) + pd.Timedelta(hours=8)  # 天勤UTC -> CST
            df = df[df.index <= pd.Timestamp.now()]
            out[n] = df
    except Exception as e:
        print("天勤取数异常:", str(e)[:80])
    finally:
        try:
            api.close()
        except Exception:
            pass
    return out


def fetch_hourly(code):
    df = ak.futures_zh_minute_sina(symbol=code, period="60")
    for c in ("open", "high", "low", "close", "volume", "hold"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).copy()
    df["dt"] = pd.to_datetime(df["datetime"])
    df = df.set_index("dt")
    # 丢掉"未收盘的成形中bar"(akshare用收盘时刻命名, 盘中会标到未来时间)
    df = df[df.index <= pd.Timestamp.now()]
    return df


def tier_of(conf):
    return "很高" if conf >= 0.80 else "高" if conf >= 0.65 else "中" if conf >= 0.50 else "低"


def build_index_df(dfs):
    """成分小时K → base100 等权合成指数 OHLC。dfs: list of 各品种小时df(可含None)。"""
    frames = []
    for i, df in enumerate(dfs):
        if df is None or len(df) < 60:
            continue
        f = df[["open", "high", "low", "close", "volume"]].copy()
        f.columns = [f"{c}{i}" for c in ("o", "h", "l", "c", "v")]
        frames.append(f)
    if len(frames) < 3:
        return None
    m = pd.concat(frames, axis=1, join="inner").dropna().tail(WIN)  # 取共同时间戳
    if len(m) < 60:
        return None
    ids = sorted({int(col[1:]) for col in m.columns})
    avg = lambda p: pd.concat([m[f"{p}{i}"] / m[f"c{i}"].iloc[0] * 100 for i in ids], axis=1).mean(axis=1)
    out = pd.DataFrame({"open": avg("o"), "high": avg("h"), "low": avg("l"), "close": avg("c")}, index=m.index)
    out["volume"] = pd.concat([m[f"v{i}"] for i in ids], axis=1).mean(axis=1)
    return out


def _levels(h, win):
    n = len(win)
    prices = [kp["price"] for kp in h.get("key_points", [])]
    if not prices:
        return None
    pat_hi, pat_lo = max(prices), min(prices)
    height = pat_hi - pat_lo
    last_close = float(win["close"].iloc[-1])
    bias = h.get("bias", "neutral")
    end_b = h.get("end_bar", n - 1)
    bars_since = n - 1 - end_b
    nk = h.get("neckline")
    if nk and "slope" in nk:  # 颈线取形态完成处(end_bar)的值, 夹断防斜率外推失真
        trigger = min(max(nk["slope"] * end_b + nk["intercept"], pat_lo - height), pat_hi + height)
    else:
        trigger = pat_lo if bias == "bearish" else pat_hi if bias == "bullish" else None
    triggered = exhausted = False
    if bias == "bearish":
        target = (trigger - height) if trigger else pat_lo - height
        stop = pat_hi
        triggered = bool(trigger and last_close < trigger)
        exhausted = last_close <= target
    elif bias == "bullish":
        target = (trigger + height) if trigger else pat_hi + height
        stop = pat_lo
        triggered = bool(trigger and last_close > trigger)
        exhausted = last_close >= target
    else:
        target = stop = None
    if bias == "neutral":
        state = "区间震荡"
    elif exhausted:
        state = "目标已到位·形态基本兑现"
    elif triggered:
        state = "已破颈线·目标未到(可跟)" if bias == "bearish" else "已突破·目标未到(可跟)"
    else:
        state = "形成中·待破位" if bias == "bearish" else "形成中·待突破"
    return {
        "pattern": h["pattern"], "pattern_cn": PAT_CN.get(h["pattern"], h["pattern"]),
        "bias": bias, "bias_cn": BIAS_CN.get(bias, bias),
        "confidence": round(h.get("confidence", 0), 2), "tier": tier_of(h.get("confidence", 0)),
        "last_close": last_close, "trigger": trigger, "target": target, "stop": stop,
        "pat_hi": pat_hi, "pat_lo": pat_lo, "state": state,
        "exhausted": bool(exhausted), "triggered": triggered, "bars_since": bars_since,
        "fresh": "近端" if bars_since <= RECENT_BARS else f"偏历史({bars_since}根前)",
        "key_points": h.get("key_points", []), "end_ts": str(win.index[end_b]),
        "start_bar": h.get("start_bar"), "end_bar": end_b,
    }


def analyze(win):
    """挑主形态: 优先 近端+未兑现(可操作), 其次近端, 再次全部; 组内按置信度。"""
    hits = CP.detect_chart_patterns(win.copy(), atr_mult=1.0)
    hits = [h for h in (hits or []) if h.get("pattern") in KEEP_PATTERNS]
    cand = [c for c in (_levels(h, win) for h in hits) if c and c["confidence"] >= CONF_MIN]
    if not cand:
        return None
    pick = lambda pool: max(pool, key=lambda c: c["confidence"]) if pool else None
    actionable = [c for c in cand if c["bars_since"] <= RECENT_BARS and not c["exhausted"] and c["bias"] != "neutral"]
    recent = [c for c in cand if c["bars_since"] <= RECENT_BARS]
    return pick(actionable) or pick(recent) or pick(cand)


def morphology_breadth(df, windows=MORPH_WINDOWS):
    """Aggregate transparent bullish/bearish morphology votes across time windows.

    This borrows the ETF API's positive-minus-negative breadth idea, but does not
    reproduce its undisclosed proprietary score. Every configured window is one
    observable vote; missing/stale/played-out geometry is neutral.
    """
    votes = []
    for size in windows:
        if len(df) < size:
            votes.append({"window": size, "vote": "neutral", "pattern": None})
            continue
        hit = analyze(df.tail(size))
        invalidated = bool(hit and (
            (hit.get("bias") == "bullish" and hit.get("stop") is not None
             and hit.get("last_close") <= hit.get("stop"))
            or (hit.get("bias") == "bearish" and hit.get("stop") is not None
                and hit.get("last_close") >= hit.get("stop"))
        ))
        valid = bool(
            hit and hit.get("bias") in {"bullish", "bearish"}
            and hit.get("bars_since", RECENT_BARS + 1) <= RECENT_BARS
            and not hit.get("exhausted", False)
            and not invalidated
        )
        votes.append({
            "window": size,
            "vote": hit["bias"] if valid else "neutral",
            "pattern": hit.get("pattern") if valid else None,
            "pattern_cn": hit.get("pattern_cn") if valid else None,
            "confidence": hit.get("confidence") if valid else None,
        })
    positive = sum(v["vote"] == "bullish" for v in votes)
    negative = sum(v["vote"] == "bearish" for v in votes)
    breadth = (positive - negative) / len(votes) if votes else 0.0
    patterns = {}
    for vote in votes:
        if vote.get("pattern"):
            patterns[vote["pattern"]] = patterns.get(vote["pattern"], 0) + 1
    dominant = max(patterns, key=patterns.get) if patterns else None
    if breadth >= 0.5:
        label = "偏多共振"
    elif breadth <= -0.5:
        label = "偏空共振"
    elif breadth > 0:
        label = "弱偏多"
    elif breadth < 0:
        label = "弱偏空"
    elif positive or negative:
        label = "多空分歧"
    else:
        label = "无有效形态"
    return {
        "windows": list(windows), "positive": positive, "negative": negative,
        "neutral": len(votes) - positive - negative, "net": positive - negative,
        "breadth": round(breadth, 4), "label": label,
        "dominant_pattern": dominant, "votes": votes,
    }


def extend_watch_state(row):
    """Keep aging geometry visible without relaxing the fresh-signal admission rule."""
    if row.get("trade_state") == "stale" and row.get("bars_since", WATCH_BARS + 1) <= WATCH_BARS:
        row["trade_state"] = "aging"
        row["decision_eligible"] = False
        row["freshness_band"] = "extended_watch"
    elif row.get("trade_state") == "stale":
        row["freshness_band"] = "expired"
    else:
        row["freshness_band"] = "fresh"
    return row


def eligible_hits(win):
    """Pattern detector used by the walk-forward audit, with the live-report universe."""
    return [
        hit for hit in CP.detect_chart_patterns(win.copy(), atr_mult=1.0)
        if hit.get("pattern") in KEEP_PATTERNS
    ]


def sector_breadth(universe):
    rows = {row["name"]: row for row in universe}
    output = []
    for sector, names in SECTORS.items():
        group = [rows[name] for name in names if name in rows]
        bull = sum(row.get("context", {}).get("trend") == "bullish" for row in group)
        bear = sum(row.get("context", {}).get("trend") == "bearish" for row in group)
        actionable = sum(row.get("decision_eligible", False) for row in group)
        output.append({
            "sector": sector,
            "contracts": len(group),
            "bullish_trends": bull,
            "bearish_trends": bear,
            "neutral_trends": max(0, len(group) - bull - bear),
            "actionable": actionable,
            "bias": "bullish" if bull > bear else "bearish" if bear > bull else "neutral",
        })
    return output


def morphology_sector_breadth(universe):
    rows = {row["name"]: row for row in universe}
    output = []
    for sector, names in SECTORS.items():
        group = [rows[name].get("morphology", {}) for name in names if name in rows]
        positive = sum(row.get("positive", 0) for row in group)
        negative = sum(row.get("negative", 0) for row in group)
        total = sum(len(row.get("windows", [])) for row in group)
        breadth = (positive - negative) / total if total else 0.0
        output.append({
            "sector": sector, "positive": positive, "negative": negative,
            "neutral": max(0, total - positive - negative), "windows": total,
            "breadth": round(breadth, 4),
        })
    return output


def aggregate_backtests(universe):
    """Pool contract-level walk-forward trades into one auditable universe test."""
    tests = [row.get("backtest", {}) for row in universe]
    tests = [test for test in tests if test.get("samples", 0) > 0]
    samples = sum(test["samples"] for test in tests)
    horizons = {}
    for horizon in ("8", "24"):
        usable = [test for test in tests if test.get("horizons", {}).get(horizon)]
        count = sum(test["samples"] for test in usable)
        if not count:
            continue
        wins = sum(
            test["horizons"][horizon]["win_rate"] * test["samples"]
            for test in usable
        )
        returns = sum(
            test["horizons"][horizon]["avg_return"] * test["samples"]
            for test in usable
        )
        horizons[horizon] = {
            "samples": count,
            "wins": int(round(wins)),
            "win_rate": wins / count,
            "avg_return": returns / count,
        }
    return {
        "samples": samples, "contracts": len(universe), "horizons": horizons,
        "method": "15-contract pooled no-look-ahead walk-forward",
    }


def gg(x):
    if x is None:
        return "—"
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.2f}"


def plot_kline(win, a):
    """小时K + 形态关键点 + 颈线/目标/止损线; 全英文/数字, 不依赖中文字体。"""
    sub = win.tail(120)
    fig, ax = plt.subplots(figsize=(5.2, 2.3), dpi=130)
    for i, (_, r) in enumerate(sub.iterrows()):
        up = r["close"] >= r["open"]
        col = "#c0392b" if up else "#1f9d55"
        ax.plot([i, i], [r["low"], r["high"]], color=col, lw=0.5, zorder=1)
        ax.add_patch(plt.Rectangle((i - 0.3, min(r["open"], r["close"])), 0.6,
                     max(abs(r["close"] - r["open"]), 1e-6), color=col, zorder=2))
    base = len(win) - len(sub)
    for kp in a["key_points"]:
        bi = kp["bar"] - base
        if 0 <= bi < len(sub):
            ax.scatter([bi], [kp["price"]], s=22, color="#2d5f8a", zorder=4)
            ax.annotate(kp["label"], (bi, kp["price"]), fontsize=6, color="#2d5f8a",
                        xytext=(0, 4), textcoords="offset points", ha="center")
    for val, c, ls in [(a["trigger"], "#e08e0b", "--"), (a["target"], "#1f9d55", ":"),
                       (a["stop"], "#c0392b", ":")]:
        if val is not None:
            ax.axhline(val, color=c, lw=0.8, ls=ls, zorder=3)
    ax.scatter([len(sub) - 1], [a["last_close"]], s=16, color="#000", zorder=5)
    ax.set_xticks([]); ax.tick_params(axis="y", labelsize=6)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout(pad=0.2)
    buf = io.BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight"); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _render(have, none, errs, asof, idx_src):
    BG, INK, MUTE, LINE = "#FBF9F3", "#2A2A28", "#8A8172", "#E4DCC9"
    RED, GRN, GOLD = "#C0392B", "#1E8449", "#B0842B"
    n_act = sum(1 for r in have if not r.get("exhausted") and r.get("bias") != "neutral")
    n_bull = sum(1 for r in have if r.get("bias") == "bullish")
    n_bear = sum(1 for r in have if r.get("bias") == "bearish")
    cards = ""
    for r in have:
        col = RED if r["bias"] == "bullish" else GRN if r["bias"] == "bearish" else GOLD
        idx_tag = ' <span style="font-size:8pt;background:#EEE7D5;border-radius:4px;padding:1px 6px;color:#6E6656">等权指数·base100</span>' if r.get("is_index") else ""
        cards += f"""
<div style="background:#fff;border:1px solid {LINE};border-radius:8px;padding:10px 14px;margin:10px 0;page-break-inside:avoid">
 <div style="display:flex;justify-content:space-between;align-items:baseline">
   <div style="font-size:13pt;font-weight:700">{r['name']}{idx_tag}　<span style="color:{col}">{r['pattern_cn']} · {r['bias_cn']}</span></div>
   <div style="color:{GOLD};font-weight:700">可信度 {r['confidence']:.2f} · {r['tier']}</div>
 </div>
 <div style="font-size:9pt;color:{MUTE};margin:2px 0 6px">{r['state']}　{r['fresh']} · 形态完成 {r['end_ts'][:16]}</div>
 <img style="width:100%;max-width:640px;display:block" src="data:image/png;base64,{r['img']}">
 <table style="font-size:9.5pt;border-collapse:collapse;margin-top:4px">
  <tr><td style="padding:1px 18px 1px 0;color:{MUTE}">现价</td><td style="font-weight:700">{gg(r['last_close'])}</td>
      <td style="padding:1px 18px;color:{MUTE}">颈线/触发</td><td style="font-weight:700;color:#e08e0b">{gg(r['trigger'])}</td>
      <td style="padding:1px 18px;color:{MUTE}">目标</td><td style="font-weight:700;color:{GRN}">{gg(r['target'])}</td>
      <td style="padding:1px 18px;color:{MUTE}">止损</td><td style="font-weight:700;color:{RED}">{gg(r['stop'])}</td></tr>
 </table>
</div>"""
    none_html = "、".join(none) if none else "无"
    errs_html = ("　跳过: " + "; ".join(f"{n}({m})" for n, m in errs)) if errs else ""
    html = f"""<!DOCTYPE html><html lang=zh-CN><head><meta charset=UTF-8><style>
@page{{size:A4;margin:12mm}}
body{{font-family:'PingFang SC','Noto Sans CJK SC',sans-serif;background:{BG};color:{INK};margin:0;font-size:10pt;line-height:1.5;padding:8px 14px}}
h1{{font-size:17pt;margin:4px 0 2px}}
</style></head><body>
<h1>期货 · 小时级形态识别日报</h1>
<div style="color:{MUTE};font-size:9pt">15 重点品种 + 商品综合/工业品指数(等权编制) · 小时K · 枢轴几何法识别 三角/矩形/楔形/旗形 · 截至 {asof}</div>
<div style="background:#F3EEE0;border-radius:8px;padding:8px 14px;margin:10px 0;font-size:9pt;color:#6E6656">
这份报告在做什么: 对 15 个重点品种取小时K, 用枢轴点几何法识别 <b>三角/矩形/楔形/旗形</b> 四类形态(已删头肩顶/双顶底),
仅保留<b>置信度高(≥0.65)</b>的, 挑选近端主形态, 给出方向、颈线触发位、目标、止损与可信度档位。
另按<b>等权法编制 商品综合指数/工业品指数</b>(base100, 公式见文末)一并识别形态并置顶。按可信度从高到低排列。</div>
<div style="font-size:10.5pt;margin:6px 0"><b style="color:{INK}">{n_act} 可操作</b>　·　{len(have)} 识别到形态　·　<b style="color:{RED}">{n_bull} 偏多</b>　·　<b style="color:{GRN}">{n_bear} 偏空</b></div>
<div style="font-size:9pt;color:{MUTE}">无明确形态: {none_html}</div>
{cards}
<div style="margin-top:12px;border-top:1px solid {LINE};padding-top:6px;font-size:8pt;color:{MUTE}">
数据源: 15品种=新浪财经(akshare 小时K 主力连续) / 指数底层={idx_src} · 指数编制: 成分主力连续小时K 各自以首根收盘=100 归一后等权平均(OHLC 同法), 量能=成分均值 ·
生成 {datetime.now():%Y-%m-%d %H:%M} · 描述性研究, 不构成投资建议。{errs_html}</div>
</body></html>"""
    Path(f"{OUT}/hourly_pattern_report.html").write_text(html, encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--no-sandbox"])
            pg = b.new_page()
            pg.set_content(html, wait_until="networkidle")
            pg.pdf(path=f"{OUT}/hourly_pattern_report.pdf", format="A4",
                   margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
                   print_background=True)
            b.close()
        print("PDF ok")
    except Exception as e:
        print("PDF fail:", str(e)[:120])


def main():
    results, universe, errs, asof_bars, dfs = [], [], [], [], {}
    for name, code in VARIETIES:
        try:
            with deadline(30):            # 单品种取数最多等30秒, 超时跳过
                df = fetch_hourly(code)
            dfs[name] = df
            if len(df) < 60:
                errs.append((name, "数据不足")); continue
            asof_bars.append(str(df.index[-1]))
            context = market_context(df)
            morphology = morphology_breadth(df)
            backtest = walk_forward_backtest(
                df, eligible_hits, _levels,
                confidence_min=CONF_MIN, recent_bars=RECENT_BARS, window=WIN,
            )
            win = df.tail(WIN)
            a = analyze(win)
            if not a:
                universe.append({"name": name, "code": code, "context": context,
                                 "morphology": morphology,
                                 "backtest": backtest,
                                 "trade_state": "none", "decision_eligible": False})
                results.append({"name": name, "code": code, "none": True}); continue
            a = extend_watch_state(enrich_pattern(a, context, RECENT_BARS))
            a["backtest"] = backtest
            a["img"] = plot_kline(win, a)
            a["name"] = name; a["code"] = code
            a["morphology"] = morphology
            results.append(a)
            universe.append({k: v for k, v in a.items() if k not in {"img", "key_points"}})
        except Exception as e:
            errs.append((name, f"{type(e).__name__}:{str(e)[:50]}"))
    # 指数底层走天勤主力连续(取不到则回退已抓的新浪数据)
    try:
        with deadline(60):
            tqd = tq_fetch([n for n, _ in VARIETIES])
    except _Timeout:
        print("天勤超时, 回退新浪"); tqd = {}
    idx_src = "天勤 TqSdk(信易科技)" if tqd else "新浪财经(akshare)"
    src_pool = tqd if tqd else dfs
    for idx_name, members in [("商品综合指数", [n for n, _ in VARIETIES]), ("工业品指数", INDUSTRIAL)]:
        try:
            idf = build_index_df([src_pool.get(m) for m in members])
            a = analyze(idf) if (idf is not None and len(idf) >= 60) else None
            if not a:
                results.append({"name": idx_name, "code": "指数", "none": True}); continue
            context = market_context(idf)
            a = extend_watch_state(enrich_pattern(a, context, RECENT_BARS))
            a["backtest"] = walk_forward_backtest(
                idf, eligible_hits, _levels,
                confidence_min=CONF_MIN, recent_bars=RECENT_BARS, window=WIN,
            )
            a["img"] = plot_kline(idf, a)
            a["name"] = idx_name; a["code"] = "指数"; a["is_index"] = True
            results.append(a)
        except Exception as e:
            errs.append((idx_name, f"{type(e).__name__}:{str(e)[:50]}"))
    # 指数置顶, 其余有形态的按可信度排序
    have = sorted([r for r in results if not r.get("none")],
                  key=lambda r: (not r.get("is_index", False), r.get("exhausted", False), -r["confidence"]))
    none = [r["name"] for r in results if r.get("none")]
    asof = (max(asof_bars)[:16] if asof_bars else str(datetime.now())[:16])
    payload = {
        "asof": asof,
        "idx_src": idx_src,
        "results": have,
        "universe": universe,
        "sectors": sector_breadth(universe),
        "morphology_sectors": morphology_sector_breadth(universe),
        "portfolio_backtest": aggregate_backtests(universe),
        "none": none,
        "errs": errs,
        "methodology": {
            "decision_rule": "仅新鲜且未失效的形态；趋势方向一致；按触发价计算的盈亏比不低于1.2",
            "trend": "现价、EMA20、EMA60同向排列",
            "volume": "最近8小时均量 / 此前32小时均量，达到1.10视为放量",
            "open_interest": "近8小时持仓量增加且20小时价格动量与形态方向一致",
            "backtest": "逐小时滚动；每个时点只使用当时可见K线；未来12小时触发后，统计8/24小时方向收益",
            "morphology_breadth": "120/160/200/250小时四个窗口独立识别；(偏多票-偏空票)/4；旧形态、已兑现形态和无形态记0",
        },
    }
    json.dump(payload,
              open(f"{OUT}/hourly_pattern_report.json", "w"), ensure_ascii=False, default=str)
    decision_rows = [row for row in have if row.get("decision_eligible")]
    _render(decision_rows, none, errs, asof, idx_src)
    print(f"形态: {len(have)} | 无明确形态: {len(none)} | 错误: {len(errs)} {errs if errs else ''}")


if __name__ == "__main__":
    main()
