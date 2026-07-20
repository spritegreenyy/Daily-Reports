#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Walk-forward sector and contract backtests for futures seat signals."""

from __future__ import annotations

import math

import numpy as np


COHORTS = ("机构", "杭州", "外资")
HORIZONS = (1, 3, 5)
LOOKBACK = 60
TRAIN_RATIO = 0.70
SIGNAL_THRESHOLD = 0.5
MIN_TRAIN_SAMPLES = 30
MIN_OOS_SAMPLES = 10

FOCUS_TESTS = (
    ("杭州·化工", "杭州", "sector", "化工", None),
    ("杭州·黑色", "杭州", "sector", "黑色", None),
    ("外资·有色", "外资", "sector", "有色", (5, "反向")),
    ("外资·棕榈油", "外资", "contract", "棕榈油", None),
)


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


def _daily_series(data, cohort, kind, target, display, sectors, multipliers):
    by_date = {}
    for variety, cohorts in data.items():
        selected = sectors.get(variety, "其他") == target if kind == "sector" else display.get(variety, variety) == target
        if not selected or cohort not in cohorts:
            continue
        item = cohorts[cohort]
        dates, net, close = item.get("dates", []), item.get("net", []), item.get("close", [])
        n = min(len(dates), len(net), len(close))
        multiplier = multipliers.get(display.get(variety, variety), 10)
        for i in range(1, n):
            if not (_finite(close[i]) and _finite(close[i - 1])) or float(close[i - 1]) == 0:
                continue
            row = by_date.setdefault(dates[i], {"flow": 0.0, "returns": []})
            row["flow"] += (float(net[i]) - float(net[i - 1])) * multiplier * float(close[i]) / 1e8
            row["returns"].append(float(close[i]) / float(close[i - 1]) - 1)
    dates = sorted(by_date)
    flows = np.asarray([by_date[d]["flow"] for d in dates], dtype=float)
    returns = np.asarray([np.mean(by_date[d]["returns"]) for d in dates], dtype=float)
    return dates, flows, returns


def _signals(flows):
    out = np.full(len(flows), np.nan)
    for i in range(LOOKBACK, len(flows)):
        value = _zscore(flows[i], flows[i - LOOKBACK:i])
        if value is not None:
            out[i] = value
    return out


def _observations(signals, returns, horizon, start, end):
    xs, ys = [], []
    stop = min(end, len(signals) - horizon)
    for i in range(max(start, LOOKBACK), stop):
        signal = signals[i]
        if not math.isfinite(signal) or abs(signal) < SIGNAL_THRESHOLD:
            continue
        forward = float(np.prod(1 + returns[i + 1:i + horizon + 1]) - 1)
        if math.isfinite(forward) and forward != 0:
            xs.append(float(signal))
            ys.append(forward)
    return np.asarray(xs), np.asarray(ys)


def _metrics(x, y, mode=None):
    if len(x) < 2:
        return None
    ic = float(np.corrcoef(x, y)[0, 1])
    if not math.isfinite(ic):
        return None
    direct = float(np.mean(np.sign(x) == np.sign(y)))
    if mode is None:
        direct_score = ic * 100 + (direct - 0.5) * 70
        reverse_score = -ic * 100 + ((1 - direct) - 0.5) * 70
        mode = "顺向" if direct_score >= reverse_score else "反向"
    adjusted_ic = ic if mode == "顺向" else -ic
    win_rate = direct if mode == "顺向" else 1 - direct
    reliability = min(1.0, math.sqrt(len(x) / 100))
    score = (adjusted_ic * 100 + (win_rate - 0.5) * 70) * reliability
    return {
        "samples": len(x),
        "ic": round(ic, 4),
        "mode": mode,
        "win_rate": round(win_rate, 4),
        "score": round(score, 3),
    }


def _strategy(dates, signals, returns, horizon, mode, start):
    daily = np.zeros(len(returns), dtype=float)
    trades, i = [], max(start, LOOKBACK)
    direction_multiplier = 1 if mode == "顺向" else -1
    while i < len(signals) - horizon - 1:
        signal = signals[i]
        if not math.isfinite(signal) or abs(signal) < SIGNAL_THRESHOLD:
            i += 1
            continue
        direction = np.sign(signal) * direction_multiplier
        entry, exit_ = i + 2, min(i + horizon + 1, len(returns) - 1)
        if entry > exit_:
            break
        daily[entry:exit_ + 1] = returns[entry:exit_ + 1] * direction
        trade_return = float(np.prod(1 + daily[entry:exit_ + 1]) - 1)
        trades.append(trade_return)
        i = exit_ + 1
    test_daily = daily[start:]
    equity = np.cumprod(1 + test_daily)
    if not len(equity):
        return None
    peaks = np.maximum.accumulate(equity)
    max_drawdown = float(np.min(equity / peaks - 1))
    total = float(equity[-1] - 1)
    annualized = float(equity[-1] ** (252 / max(len(test_daily), 1)) - 1) if equity[-1] > 0 else -1.0
    wins = [x for x in trades if x > 0]
    losses = [x for x in trades if x < 0]
    payoff = (np.mean(wins) / abs(np.mean(losses))) if wins and losses else None
    stride = max(1, len(equity) // 80)
    points = list(range(0, len(equity), stride))
    if points[-1] != len(equity) - 1:
        points.append(len(equity) - 1)
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "total_return": round(total, 4),
        "annualized": round(annualized, 4),
        "max_drawdown": round(max_drawdown, 4),
        "payoff": None if payoff is None else round(float(payoff), 2),
        "dates": [dates[start + j] for j in points],
        "equity": [round(float(equity[j]), 4) for j in points],
    }


def _strength_buckets(x, y, mode):
    result = []
    for label, lo, hi in (("0.5–1", 0.5, 1), ("1–2", 1, 2), ("≥2", 2, float("inf"))):
        mask = (np.abs(x) >= lo) & (np.abs(x) < hi)
        if not np.any(mask):
            continue
        direct = np.mean(np.sign(x[mask]) == np.sign(y[mask]))
        win = direct if mode == "顺向" else 1 - direct
        result.append({"label": label, "samples": int(np.sum(mask)), "win_rate": round(float(win), 4)})
    return result


def _analyze(dates, flows, returns, preset=None):
    if len(dates) <= LOOKBACK + max(HORIZONS) + 20:
        return None
    signals = _signals(flows)
    split = max(LOOKBACK + 20, int(len(dates) * TRAIN_RATIO))
    if preset:
        horizon, mode = preset
        x, y = _observations(signals, returns, horizon, LOOKBACK, split)
        if len(x) < 5:
            return None
        train = _metrics(x, y, mode)
        selection = "预设检验"
    else:
        candidates = []
        for horizon in HORIZONS:
            x, y = _observations(signals, returns, horizon, LOOKBACK, split)
            if len(x) < MIN_TRAIN_SAMPLES:
                continue
            metrics = _metrics(x, y)
            if metrics:
                candidates.append((metrics["score"], horizon, metrics))
        if not candidates:
            return None
        _, horizon, train = max(candidates, key=lambda row: row[0])
        selection = "训练期选择"
    x, y = _observations(signals, returns, horizon, split, len(dates))
    if len(x) < MIN_OOS_SAMPLES:
        return None
    oos = _metrics(x, y, train["mode"])
    if not oos:
        return None
    oos["strategy"] = _strategy(dates, signals, returns, horizon, train["mode"], split)
    oos["buckets"] = _strength_buckets(x, y, train["mode"])
    latest = signals[-1]
    return {
        "horizon": horizon,
        "mode": train["mode"],
        "selection": selection,
        "train": train,
        "oos": oos,
        "train_end": dates[split - 1],
        "oos_start": dates[split],
        "latest_date": dates[-1],
        "latest_z": None if not math.isfinite(latest) else round(float(latest), 2),
    }


def _member_stats(broker_data, variety, member_names):
    members = []
    for name in member_names:
        item = broker_data.get(variety, {}).get(name)
        if not item or len(item.get("net", [])) < 2:
            continue
        net = item["net"]
        members.append({"name": name, "net": round(float(net[-1])), "change": round(float(net[-1] - net[-2]))})
    return sorted(members, key=lambda x: abs(x["change"]), reverse=True)


def _contract_stats(item, horizon, mode, split_ratio=TRAIN_RATIO):
    net = np.asarray(item.get("net", []), dtype=float)
    close = np.asarray([np.nan if not _finite(x) else float(x) for x in item.get("close", [])])
    n = min(len(net), len(close))
    if n <= LOOKBACK + horizon + 20:
        return None, None
    flows = np.diff(net[-n:], prepend=np.nan)
    signals = _signals(flows)
    returns = np.diff(close[-n:], prepend=np.nan) / np.roll(close[-n:], 1)
    split = max(LOOKBACK + 20, int(n * split_ratio))
    x, y = _observations(signals, returns, horizon, split, n)
    stats = _metrics(x, y, mode) if len(x) >= MIN_OOS_SAMPLES else None
    latest = signals[-1]
    return stats, None if not math.isfinite(latest) else float(latest)


def _key_contracts(data, cohort, kind, target, result, display, sectors, broker_data, cohort_members, limit=3):
    ranked = []
    for variety, cohorts in data.items():
        selected = sectors.get(variety, "其他") == target if kind == "sector" else display.get(variety, variety) == target
        if not selected or cohort not in cohorts:
            continue
        item = cohorts[cohort]
        stats, latest = _contract_stats(item, result["horizon"], result["mode"])
        dates, net, close = item.get("dates", []), item.get("net", []), item.get("close", [])
        n = min(len(dates), len(net), len(close), 90)
        if n < 2:
            continue
        current_net = float(net[-1])
        current_change = float(net[-1]) - float(net[-2])
        active_days = sum(a != b for a, b in zip(net[1:], net[:-1]))
        rank_score = (8 if current_net else 0) + (5 if current_change else 0) + min(math.log10(abs(current_net) + 1), 5) + min(active_days / 100, 5) + min(abs(latest or 0), 3)
        ranked.append((rank_score, {
            "name": display.get(variety, variety),
            "latest_z": None if latest is None else round(latest, 2),
            "current_net": round(current_net),
            "current_change": round(current_change),
            "oos": stats,
            "members": _member_stats(broker_data, variety, cohort_members.get(cohort, [])),
            "dates": dates[-n:],
            "net": [round(float(x)) for x in net[-n:]],
            "close": [None if not _finite(x) else round(float(x), 4) for x in close[-n:]],
        }))
    return [item for _, item in sorted(ranked, key=lambda x: x[0], reverse=True)[:limit]]


def _combo_series(data, sector, display, sectors, multipliers):
    hz_dates, hz_flows, hz_returns = _daily_series(data, "杭州", "sector", sector, display, sectors, multipliers)
    wz_dates, wz_flows, _ = _daily_series(data, "外资", "sector", sector, display, sectors, multipliers)
    hz = {d: (f, r) for d, f, r in zip(hz_dates, hz_flows, hz_returns)}
    wz = {d: f for d, f in zip(wz_dates, wz_flows)}
    dates = sorted(set(hz) & set(wz))
    if not dates:
        return [], np.asarray([]), np.asarray([])
    hz_flow = np.asarray([hz[d][0] for d in dates])
    wz_flow = np.asarray([wz[d] for d in dates])
    composite = hz_flow - wz_flow
    return dates, composite, np.asarray([hz[d][1] for d in dates])


def build_cohort_backtests(data, display, sectors, multipliers, sector_order, broker_data=None, cohort_members=None):
    """Build strict train/validation studies, focus tests and the Hangzhou-minus-foreign factor."""
    broker_data = broker_data or {}
    cohort_members = cohort_members or {}
    groups = []
    for cohort in COHORTS:
        candidates = []
        for sector in sector_order:
            dates, flows, returns = _daily_series(data, cohort, "sector", sector, display, sectors, multipliers)
            result = _analyze(dates, flows, returns)
            if result:
                candidates.append((result["train"]["score"], sector, result))
        if not candidates:
            continue
        _, sector, best = max(candidates, key=lambda row: row[0])
        best["sector"] = sector
        best["contracts"] = _key_contracts(data, cohort, "sector", sector, best, display, sectors, broker_data, cohort_members)
        groups.append({"cohort": cohort, "best": best})

    focuses = []
    for label, cohort, kind, target, preset in FOCUS_TESTS:
        dates, flows, returns = _daily_series(data, cohort, kind, target, display, sectors, multipliers)
        result = _analyze(dates, flows, returns, preset=preset)
        if not result:
            continue
        result.update({"label": label, "cohort": cohort, "target": target, "kind": kind})
        result["contracts"] = _key_contracts(data, cohort, kind, target, result, display, sectors, broker_data, cohort_members, limit=2)
        focuses.append(result)

    combo_candidates = []
    for sector in sector_order:
        dates, flows, returns = _combo_series(data, sector, display, sectors, multipliers)
        result = _analyze(dates, flows, returns)
        if result:
            combo_candidates.append((result["train"]["score"], sector, result))
    combo = None
    if combo_candidates:
        _, sector, combo = max(combo_candidates, key=lambda row: row[0])
        combo.update({"name": "跟杭州·反外资", "sector": sector})

    return {
        "method": {
            "lookback": LOOKBACK,
            "horizons": list(HORIZONS),
            "signal_threshold": SIGNAL_THRESHOLD,
            "train_ratio": TRAIN_RATIO,
            "execution_delay": 1,
            "price": "板块等权收益",
        },
        "groups": groups,
        "focuses": focuses,
        "combo": combo,
    }
