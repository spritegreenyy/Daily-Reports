#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sector backtests for institutional, Hangzhou and foreign futures seats."""

from __future__ import annotations

import math

import numpy as np


COHORTS = ("机构", "杭州", "外资")
HORIZONS = (1, 3, 5)
LOOKBACK = 60
SIGNAL_THRESHOLD = 0.5
MIN_SECTOR_SAMPLES = 40


def _finite(value):
    return value is not None and math.isfinite(float(value))


def _zscore(current, history):
    history = np.asarray(history, dtype=float)
    history = history[np.isfinite(history)]
    if len(history) < 20:
        return None
    std = float(np.std(history))
    if std <= 1e-12:
        return None
    return (float(current) - float(np.mean(history))) / std


def _score(ic, win_rate, samples):
    """Rank effect size and hit-rate edge, shrinking small samples."""
    raw = abs(ic) * 100 + abs(win_rate - 0.5) * 70
    reliability = min(1.0, math.sqrt(samples / 200))
    return raw * reliability


def _sector_daily(data, cohort, sector, display, sectors, multipliers):
    by_date = {}
    for variety, cohorts in data.items():
        if sectors.get(variety, "其他") != sector or cohort not in cohorts:
            continue
        item = cohorts[cohort]
        dates, net, close = item.get("dates", []), item.get("net", []), item.get("close", [])
        n = min(len(dates), len(net), len(close))
        multiplier = multipliers.get(display.get(variety, variety), 10)
        for i in range(1, n):
            if not (_finite(close[i]) and _finite(close[i - 1])) or float(close[i - 1]) == 0:
                continue
            flow = (float(net[i]) - float(net[i - 1])) * multiplier * float(close[i]) / 1e8
            daily_return = float(close[i]) / float(close[i - 1]) - 1
            row = by_date.setdefault(dates[i], {"flow": 0.0, "returns": []})
            row["flow"] += flow
            row["returns"].append(daily_return)
    dates = sorted(by_date)
    flows = np.asarray([by_date[d]["flow"] for d in dates], dtype=float)
    returns = np.asarray([np.mean(by_date[d]["returns"]) for d in dates], dtype=float)
    return dates, flows, returns


def _test_series(flows, returns, horizon):
    signals, forward_returns = [], []
    for i in range(LOOKBACK, len(flows) - horizon):
        signal = _zscore(flows[i], flows[i - LOOKBACK:i])
        if signal is None or abs(signal) < SIGNAL_THRESHOLD:
            continue
        forward = float(np.prod(1 + returns[i + 1:i + horizon + 1]) - 1)
        if not math.isfinite(forward) or forward == 0:
            continue
        signals.append(signal)
        forward_returns.append(forward)
    if len(signals) < MIN_SECTOR_SAMPLES:
        return None
    x, y = np.asarray(signals), np.asarray(forward_returns)
    ic = float(np.corrcoef(x, y)[0, 1])
    if not math.isfinite(ic):
        return None
    direct = float(np.mean(np.sign(x) == np.sign(y)))
    reverse = 1 - direct
    mode = "顺向" if direct >= reverse else "反向"
    win_rate = max(direct, reverse)
    return {
        "horizon": horizon,
        "samples": len(x),
        "ic": round(ic, 4),
        "direct_win": round(direct, 4),
        "reverse_win": round(reverse, 4),
        "mode": mode,
        "win_rate": round(win_rate, 4),
        "score": round(_score(ic, win_rate, len(x)), 3),
    }


def _contract_test(item, horizon, mode):
    net = np.asarray(item.get("net", []), dtype=float)
    close = np.asarray([np.nan if not _finite(x) else float(x) for x in item.get("close", [])])
    n = min(len(net), len(close))
    net, close = net[-n:], close[-n:]
    flows = np.diff(net, prepend=np.nan)
    x, y = [], []
    for i in range(LOOKBACK + 1, n - horizon):
        if not (_finite(close[i]) and _finite(close[i + horizon])) or close[i] == 0:
            continue
        signal = _zscore(flows[i], flows[i - LOOKBACK:i])
        if signal is None or abs(signal) < SIGNAL_THRESHOLD:
            continue
        forward = close[i + horizon] / close[i] - 1
        if forward == 0:
            continue
        x.append(signal)
        y.append(forward)
    latest = _zscore(flows[-1], flows[-LOOKBACK - 1:-1]) if n > LOOKBACK + 1 else None
    if len(x) < 20:
        return None, latest
    x, y = np.asarray(x), np.asarray(y)
    ic = float(np.corrcoef(x, y)[0, 1])
    if not math.isfinite(ic):
        return None, latest
    direct = float(np.mean(np.sign(x) == np.sign(y)))
    win_rate = direct if mode == "顺向" else 1 - direct
    return {
        "samples": len(x),
        "ic": round(ic, 4),
        "win_rate": round(win_rate, 4),
        "score": round(_score(ic, win_rate, len(x)), 3),
    }, latest


def _key_contracts(data, cohort, sector, result, display, sectors):
    ranked = []
    for variety, cohorts in data.items():
        if sectors.get(variety, "其他") != sector or cohort not in cohorts:
            continue
        item = cohorts[cohort]
        stats, latest = _contract_test(item, result["horizon"], result["mode"])
        dates, net, close = item.get("dates", []), item.get("net", []), item.get("close", [])
        n = min(len(dates), len(net), len(close), 90)
        if n < 2:
            continue
        active_days = sum(a != b for a, b in zip(net[1:], net[:-1]))
        current_net = float(net[-1])
        current_change = float(net[-1]) - float(net[-2])
        rank_score = (
            (8 if current_net else 0)
            + (5 if current_change else 0)
            + min(math.log10(abs(current_net) + 1), 5)
            + min(active_days / 100, 5)
            + min(abs(latest or 0), 3)
        )
        ranked.append((rank_score, {
            "name": display.get(variety, variety),
            "latest_z": None if latest is None else round(float(latest), 2),
            "current_net": round(current_net),
            "current_change": round(current_change),
            "samples": stats["samples"] if stats else None,
            "ic": stats["ic"] if stats else None,
            "win_rate": stats["win_rate"] if stats else None,
            "dates": dates[-n:],
            "net": [round(float(x)) for x in net[-n:]],
            "close": [None if not _finite(x) else round(float(x), 4) for x in close[-n:]],
        }))
    return [item for _, item in sorted(ranked, key=lambda x: x[0], reverse=True)[:3]]


def build_cohort_backtests(data, display, sectors, multipliers, sector_order):
    """Return one best sector and its key contracts for each requested cohort."""
    groups = []
    for cohort in COHORTS:
        tested = []
        for sector in sector_order:
            dates, flows, returns = _sector_daily(data, cohort, sector, display, sectors, multipliers)
            if len(dates) <= LOOKBACK + max(HORIZONS):
                continue
            latest_z = _zscore(flows[-1], flows[-LOOKBACK - 1:-1])
            for horizon in HORIZONS:
                result = _test_series(flows, returns, horizon)
                if result is None:
                    continue
                result.update({
                    "sector": sector,
                    "latest_date": dates[-1],
                    "latest_z": None if latest_z is None else round(float(latest_z), 2),
                })
                tested.append(result)
        if not tested:
            continue
        best = dict(max(tested, key=lambda x: x["score"]))
        best["contracts"] = _key_contracts(data, cohort, best["sector"], best, display, sectors)
        groups.append({
            "cohort": cohort,
            "best": best,
        })
    return {
        "method": {
            "lookback": LOOKBACK,
            "horizons": list(HORIZONS),
            "signal_threshold": SIGNAL_THRESHOLD,
            "price": "板块等权收益",
        },
        "groups": groups,
    }
