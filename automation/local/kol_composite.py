"""Deterministic KOL composite index, diagnostics, and price backtests."""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from typing import Any


ASSET_KEYS = ("energy", "metals", "grains", "softs")
SIGNAL_THRESHOLD = 8.0
EVENT_CHANGE_THRESHOLD = 18.0
ATTENTION_LOOKBACK = 20


def build_composite_history(
    index_history: dict[str, Any],
    event_labels: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Combine asset indices using directional samples times confidence."""
    event_labels = event_labels or {}
    daily: list[dict[str, Any]] = []

    for source_row in index_history.get("daily", []):
        assets = source_row.get("assets", {})
        weights: dict[str, float] = {}
        for key in ASSET_KEYS:
            item = assets.get(key, {})
            score = item.get("score")
            samples = int(item.get("signal_tweets") or 0)
            confidence = float(item.get("confidence") or 0.0)
            if score is not None and samples > 0 and confidence > 0:
                weights[key] = samples * confidence

        total_weight = sum(weights.values())
        contributions = {key: None for key in ASSET_KEYS}
        composite = None
        if total_weight:
            for key, weight in weights.items():
                contributions[key] = round(
                    float(assets[key]["score"]) * weight / total_weight, 2
                )
            composite = round(sum(v for v in contributions.values() if v is not None), 1)

        bullish = sum(int(assets.get(key, {}).get("bullish") or 0) for key in ASSET_KEYS)
        bearish = sum(int(assets.get(key, {}).get("bearish") or 0) for key in ASSET_KEYS)
        directional = bullish + bearish
        disagreement = (
            round(100 * (1 - abs(bullish - bearish) / directional), 1)
            if directional else None
        )
        mentions = sum(int(assets.get(key, {}).get("mentions") or 0) for key in ASSET_KEYS)
        date = str(source_row.get("date") or "")
        daily.append({
            "date": date,
            "score": composite,
            "contributions": contributions,
            "active_assets": len(weights),
            "coverage": round(100 * len(weights) / len(ASSET_KEYS), 1),
            "effective_weight": round(total_weight, 3),
            "mentions": mentions,
            "directional_samples": directional,
            "bullish": bullish,
            "bearish": bearish,
            "disagreement": disagreement,
            "event_zh": str(event_labels.get(date, {}).get("zh") or ""),
            "event_en": str(event_labels.get(date, {}).get("en") or ""),
        })

    for index, row in enumerate(daily):
        row["attention"] = _attention_score(daily, index)
        row["change_5d"] = _period_change(daily, index, 5)
        row["change_20d"] = _period_change(daily, index, 20)
        previous = _previous_valid(daily, index)
        row["day_change"] = (
            round(float(row["score"]) - float(previous["score"]), 1)
            if row["score"] is not None and previous else None
        )
        row["event"] = bool(
            row["score"] is not None
            and row["day_change"] is not None
            and abs(row["day_change"]) >= EVENT_CHANGE_THRESHOLD
            and row["event_zh"]
        )

    return {
        "method": {
            "composite": "sum(asset_score * signal_samples * confidence) / sum(signal_samples * confidence)",
            "contribution": "asset_score * asset_effective_weight / total_effective_weight",
            "coverage": "active directional asset groups / 4",
            "attention": "clip(50 + 15 * zscore(total mentions vs prior 20 reports), 0, 100)",
            "disagreement": "100 * (1 - abs(bullish - bearish) / directional_samples)",
            "missing": "no directional sample remains null; missing values are never filled with zero",
            "signal_threshold": SIGNAL_THRESHOLD,
            "event_threshold": EVENT_CHANGE_THRESHOLD,
        },
        "daily": daily,
    }


def run_price_backtests(
    composite_daily: list[dict[str, Any]],
    price_series: dict[str, dict[str, float]],
    *,
    horizons: tuple[int, ...] = (1, 3, 5),
) -> dict[str, Any]:
    """Test whether the index direction agrees with future closing-price returns."""
    products = {}
    for product, prices in price_series.items():
        ordered = sorted(
            (date, float(close)) for date, close in prices.items()
            if close is not None and float(close) > 0
        )
        position = {date: index for index, (date, _) in enumerate(ordered)}
        metrics = {}
        for horizon in horizons:
            pairs = []
            for row in composite_daily:
                score = row.get("score")
                date = row.get("date")
                if score is None or abs(float(score)) < SIGNAL_THRESHOLD or date not in position:
                    continue
                start = position[date]
                end = start + horizon
                if end >= len(ordered):
                    continue
                start_close = ordered[start][1]
                future_close = ordered[end][1]
                future_return = 100 * (future_close / start_close - 1)
                directional_return = (1 if score > 0 else -1) * future_return
                pairs.append((float(score), future_return, directional_return))
            metrics[str(horizon)] = _backtest_metrics(pairs)
        products[product] = metrics
    return {
        "method": {
            "entry": "report-date settlement close",
            "forward": "future settlement close after 1/3/5 trading days",
            "signal": f"abs(composite index) >= {SIGNAL_THRESHOLD:g}",
            "directional_return": "sign(index) * future price return",
            "win": "directional return > 0",
            "ic": "Pearson correlation between composite index and future return",
            "warning": "descriptive small-sample validation; no fees, slippage, or execution lag",
        },
        "products": products,
    }


def load_price_series(
    fetcher: Callable[[str], Any],
    symbols: dict[str, str],
) -> dict[str, dict[str, float]]:
    """Normalize a daily-price fetcher into date -> close mappings."""
    output = {}
    for product, symbol in symbols.items():
        try:
            frame = fetcher(symbol)
            if frame is None or len(frame) == 0:
                continue
            date_column = "date" if "date" in frame.columns else frame.columns[0]
            close_column = "close" if "close" in frame.columns else "收盘价"
            rows = {}
            for _, row in frame.iterrows():
                date = str(row[date_column])[:10]
                try:
                    close = float(row[close_column])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(close) and close > 0:
                    rows[date] = close
            if rows:
                output[product] = rows
        except Exception:
            continue
    return output


def _attention_score(rows: list[dict[str, Any]], index: int) -> float | None:
    history = [float(row["mentions"]) for row in rows[max(0, index - ATTENTION_LOOKBACK):index]]
    if len(history) < 5:
        return None
    mean = statistics.fmean(history)
    std = statistics.pstdev(history)
    if std == 0:
        return 50.0
    zscore = (float(rows[index]["mentions"]) - mean) / std
    return round(max(0.0, min(100.0, 50 + 15 * zscore)), 1)


def _period_change(rows: list[dict[str, Any]], index: int, periods: int) -> float | None:
    if index < periods or rows[index].get("score") is None:
        return None
    previous = rows[index - periods].get("score")
    if previous is None:
        return None
    return round(float(rows[index]["score"]) - float(previous), 1)


def _previous_valid(rows: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    for row in reversed(rows[:index]):
        if row.get("score") is not None:
            return row
    return None


def _backtest_metrics(pairs: list[tuple[float, float, float]]) -> dict[str, Any]:
    if not pairs:
        return {"n": 0, "avg_directional_return": None, "win_rate": None, "ic": None}
    scores = [row[0] for row in pairs]
    returns = [row[1] for row in pairs]
    directional = [row[2] for row in pairs]
    wins = sum(value > 0 for value in directional)
    return {
        "n": len(pairs),
        "avg_directional_return": round(statistics.fmean(directional), 3),
        "win_rate": round(100 * wins / len(pairs), 1),
        "ic": _pearson(scores, returns),
    }


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(right) != len(left):
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_var = sum((x - left_mean) ** 2 for x in left)
    right_var = sum((y - right_mean) ** 2 for y in right)
    if left_var <= 0 or right_var <= 0:
        return None
    return round(numerator / math.sqrt(left_var * right_var), 3)
