#!/usr/bin/env python3
"""Decision-oriented metrics and walk-forward validation for pattern reports."""

from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd


def _safe_float(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    previous = close.shift(1).fillna(close.iloc[0])
    true_range = pd.concat(
        [high - low, (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean().bfill()


def market_context(df: pd.DataFrame) -> dict:
    """Return transparent trend, participation and volatility observations."""
    close = pd.to_numeric(df["close"], errors="coerce")
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema60 = close.ewm(span=60, adjust=False).mean()
    last = _safe_float(close.iloc[-1], 0.0)
    if last > ema20.iloc[-1] > ema60.iloc[-1]:
        trend = "bullish"
    elif last < ema20.iloc[-1] < ema60.iloc[-1]:
        trend = "bearish"
    else:
        trend = "neutral"

    atr_series = atr(df)
    atr_now = _safe_float(atr_series.iloc[-1], 0.0)
    atr_pct = atr_now / last if last else 0.0
    atr_history = (atr_series / close.replace(0, np.nan)).tail(60).dropna()
    atr_median = _safe_float(atr_history.median(), atr_pct) or atr_pct
    vol_ratio = atr_pct / atr_median if atr_median else 1.0
    volatility = "high" if vol_ratio >= 1.25 else "low" if vol_ratio <= 0.8 else "normal"

    volume_ratio = None
    if "volume" in df and len(df) >= 40:
        volume = pd.to_numeric(df["volume"], errors="coerce").replace(0, np.nan)
        recent = _safe_float(volume.tail(8).mean())
        baseline = _safe_float(volume.iloc[-40:-8].mean())
        if recent is not None and baseline:
            volume_ratio = recent / baseline

    oi_change = None
    oi_col = "hold" if "hold" in df else "open_interest" if "open_interest" in df else None
    if oi_col and len(df) >= 9:
        oi = pd.to_numeric(df[oi_col], errors="coerce").replace(0, np.nan)
        old, new = _safe_float(oi.iloc[-9]), _safe_float(oi.iloc[-1])
        if old and new is not None:
            oi_change = new / old - 1.0

    momentum20 = last / close.iloc[-21] - 1.0 if len(close) >= 21 and close.iloc[-21] else 0.0
    return {
        "trend": trend,
        "ema20": _safe_float(ema20.iloc[-1]),
        "ema60": _safe_float(ema60.iloc[-1]),
        "atr": atr_now,
        "atr_pct": atr_pct,
        "volatility": volatility,
        "volume_ratio": _safe_float(volume_ratio),
        "oi_change": _safe_float(oi_change),
        "momentum20": _safe_float(momentum20, 0.0),
    }


def _trend_from_close(close: pd.Series) -> str:
    close = pd.to_numeric(close, errors="coerce").dropna()
    if len(close) < 20:
        return "neutral"
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema60 = close.ewm(span=60, adjust=False).mean()
    last = close.iloc[-1]
    if last > ema20.iloc[-1] > ema60.iloc[-1]:
        return "bullish"
    if last < ema20.iloc[-1] < ema60.iloc[-1]:
        return "bearish"
    return "neutral"


def _resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df:
        agg["volume"] = "sum"
    if "hold" in df:
        agg["hold"] = "last"
    return df.resample(rule, label="right", closed="right").agg(agg).dropna(subset=["close"])


def _rsi(close: pd.Series, period: int = 14):
    close = pd.to_numeric(close, errors="coerce")
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    avg_gain = _safe_float(gain.iloc[-1], 0.0) or 0.0
    avg_loss = _safe_float(loss.iloc[-1], 0.0) or 0.0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def technical_snapshot(df: pd.DataFrame) -> dict:
    """Murphy-style futures context from OHLCVI without cross-market inputs."""
    hourly = df.copy()
    four_hour = _resample_ohlc(hourly, "4h")
    # Night-session bars are shifted into the following trading date before daily grouping.
    daily_source = hourly.copy()
    shifted = daily_source.index + pd.to_timedelta(
        [1 if ts.hour >= 20 else 0 for ts in daily_source.index], unit="D"
    )
    daily_source.index = shifted.normalize()
    daily = _resample_ohlc(daily_source, "1D")
    trends = {
        "hourly": _trend_from_close(hourly["close"]),
        "four_hour": _trend_from_close(four_hour["close"]),
        "daily": _trend_from_close(daily["close"]),
    }

    close = pd.to_numeric(hourly["close"], errors="coerce")
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = _safe_float((macd - macd_signal).iloc[-1], 0.0)
    rsi14 = _rsi(close)
    recent = hourly.tail(60)
    prior = recent.iloc[:-1] if len(recent) > 1 else recent
    resistance20 = _safe_float(prior["high"].tail(20).max())
    support20 = _safe_float(prior["low"].tail(20).min())
    resistance60 = _safe_float(prior["high"].max())
    support60 = _safe_float(prior["low"].min())

    price_change = close.iloc[-1] / close.iloc[-9] - 1 if len(close) >= 9 else None
    oi_change = None
    if "hold" in hourly and len(hourly) >= 9:
        oi = pd.to_numeric(hourly["hold"], errors="coerce")
        if oi.iloc[-9]:
            oi_change = oi.iloc[-1] / oi.iloc[-9] - 1
    if price_change is None or oi_change is None:
        participation = "unavailable"
    elif price_change > 0 and oi_change > 0:
        participation = "long_build"
    elif price_change > 0 and oi_change < 0:
        participation = "short_cover"
    elif price_change < 0 and oi_change > 0:
        participation = "short_build"
    elif price_change < 0 and oi_change < 0:
        participation = "long_exit"
    else:
        participation = "mixed"

    directional = [trend for trend in trends.values() if trend != "neutral"]
    aligned = len(directional) == 3 and len(set(directional)) == 1
    return {
        "trends": trends,
        "aligned": aligned,
        "alignment": directional[0] if aligned else "mixed",
        "rsi14": rsi14,
        "macd_hist": macd_hist,
        "macd_state": "bullish" if macd_hist > 0 else "bearish" if macd_hist < 0 else "neutral",
        "support20": support20, "resistance20": resistance20,
        "support60": support60, "resistance60": resistance60,
        "price_change8": _safe_float(price_change), "oi_change8": _safe_float(oi_change),
        "participation": participation,
        "bars": {"hourly": len(hourly), "four_hour": len(four_hour), "daily": len(daily)},
    }


def enrich_pattern(pattern: dict, context: dict, recent_bars: int = 45) -> dict:
    """Convert a geometric pattern into a trade-state assessment without hiding inputs."""
    row = dict(pattern)
    bias = row.get("bias")
    last = _safe_float(row.get("last_close"))
    trigger = _safe_float(row.get("trigger"))
    target = _safe_float(row.get("target"))
    stop = _safe_float(row.get("stop"))
    atr_now = _safe_float(context.get("atr"), 0.0) or 0.0
    bars_since = int(row.get("bars_since") or 0)

    geometry_valid = all(v is not None for v in (last, trigger, target, stop))
    if geometry_valid and bias == "bullish":
        geometry_valid = target > trigger > stop
        invalidated = last <= stop
    elif geometry_valid and bias == "bearish":
        geometry_valid = target < trigger < stop
        invalidated = last >= stop
    else:
        invalidated = True

    stale = bars_since > recent_bars
    exhausted = bool(row.get("exhausted"))
    triggered = bool(row.get("triggered"))
    distance_atr = abs(last - trigger) / atr_now if atr_now and trigger is not None else None
    risk = abs(trigger - stop) if geometry_valid else None
    reward = abs(target - trigger) if geometry_valid else None
    reward_risk = reward / risk if risk else None

    if not geometry_valid:
        trade_state = "invalid"
    elif stale:
        trade_state = "stale"
    elif invalidated:
        trade_state = "invalid"
    elif exhausted:
        trade_state = "played"
    elif triggered:
        trade_state = "active"
    elif distance_atr is not None and distance_atr <= 1.5:
        trade_state = "setup"
    else:
        trade_state = "monitor"

    trend_aligned = context.get("trend") == bias
    volume_confirmed = (context.get("volume_ratio") or 0.0) >= 1.10
    directional_momentum = (context.get("momentum20") or 0.0) * (1 if bias == "bullish" else -1)
    oi_confirmed = (context.get("oi_change") or 0.0) > 0 and directional_momentum > 0
    decision_eligible = (
        trade_state in {"active", "setup"}
        and trend_aligned
        and reward_risk is not None
        and reward_risk >= 1.2
    )

    row.update(
        {
            "geometry_valid": bool(geometry_valid),
            "trade_state": trade_state,
            "stale": stale,
            "distance_atr": _safe_float(distance_atr),
            "reward_risk": _safe_float(reward_risk),
            "trend_aligned": trend_aligned,
            "volume_confirmed": volume_confirmed,
            "oi_confirmed": oi_confirmed,
            "decision_eligible": decision_eligible,
            "context": context,
        }
    )
    return row


def walk_forward_backtest(
    df: pd.DataFrame,
    detector: Callable[[pd.DataFrame], list],
    level_builder: Callable[[dict, pd.DataFrame], dict | None],
    *,
    confidence_min: float = 0.74,
    recent_bars: int = 45,
    window: int = 250,
    step: int = 4,
    trigger_window: int = 12,
    horizons: tuple[int, ...] = (8, 24),
) -> dict:
    """Walk forward without using bars after each detection point.

    A pattern is detected using data available at time t. A trade is counted only if
    price crosses its fixed trigger during the following ``trigger_window`` bars.
    Returns are measured from that crossing close in the pattern direction.
    """
    max_horizon = max(horizons)
    if len(df) < 220 + trigger_window + max_horizon:
        return {"samples": 0, "horizons": {}, "method": "walk_forward_hourly"}

    records = []
    seen = set()
    start = min(window - 1, 219)
    end = len(df) - trigger_window - max_horizon - 1
    for t in range(start, end, step):
        history = df.iloc[max(0, t - window + 1): t + 1].copy()
        for hit in detector(history):
            if hit.get("confidence", 0.0) < confidence_min:
                continue
            if len(history) - 1 - int(hit.get("end_bar", 0)) > recent_bars:
                continue
            levels = level_builder(hit, history)
            if not levels:
                continue
            key = (
                levels.get("pattern"),
                str(history.index[int(levels.get("start_bar", 0))]),
                str(history.index[int(levels.get("end_bar", 0))]),
            )
            if key in seen:
                continue
            seen.add(key)
            bias = levels.get("bias")
            trigger = _safe_float(levels.get("trigger"))
            if bias not in {"bullish", "bearish"} or trigger is None:
                continue
            future = pd.to_numeric(
                df["close"].iloc[t + 1: t + trigger_window + 1], errors="coerce"
            )
            crossed = future[future > trigger] if bias == "bullish" else future[future < trigger]
            if crossed.empty:
                continue
            entry_label = crossed.index[0]
            entry_pos = df.index.get_loc(entry_label)
            entry = _safe_float(df["close"].iloc[entry_pos])
            if not entry or entry_pos + max_horizon >= len(df):
                continue
            direction = 1.0 if bias == "bullish" else -1.0
            item = {"bias": bias, "pattern": levels.get("pattern")}
            for horizon in horizons:
                exit_price = _safe_float(df["close"].iloc[entry_pos + horizon])
                item[f"ret_{horizon}"] = direction * (exit_price / entry - 1.0)
            records.append(item)

    summary = {"samples": len(records), "horizons": {}, "method": "walk_forward_hourly"}
    for horizon in horizons:
        values = [r[f"ret_{horizon}"] for r in records]
        summary["horizons"][str(horizon)] = {
            "win_rate": sum(v > 0 for v in values) / len(values) if values else None,
            "avg_return": sum(values) / len(values) if values else None,
        }
    return summary
