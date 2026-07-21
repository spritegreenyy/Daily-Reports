#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Walk-forward contract scans for futures seat-position signals."""

from __future__ import annotations

import math

import numpy as np


COHORTS = ("机构", "外资", "杭州")
DISPLAY_ALIASES = {"铁矿石": "铁矿", "燃油": "燃料油", "橡胶": "天然橡胶"}
HORIZONS = (1, 3, 5)
LOOKBACK = 60
TRAIN_RATIO = 0.70
SIGNAL_THRESHOLD = 0.5
MIN_TRAIN_SAMPLES = 30
MIN_OOS_SAMPLES = 10
DISPLAY_MIN_SAMPLES = 30
DISPLAY_MIN_CORRELATION = 0.08

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


def _analyze(dates, flows, returns, preset=None, fixed_mode=None):
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
            metrics = _metrics(x, y, fixed_mode)
            if metrics:
                candidates.append((metrics["score"], horizon, metrics))
        if not candidates:
            return None
        _, horizon, train = max(candidates, key=lambda row: row[0])
        selection = "固定反向筛选" if fixed_mode == "反向" else "训练期选择"
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


def _member_stats(broker_data, variety, member_names, latest_date):
    members = []
    for name in member_names:
        item = broker_data.get(variety, {}).get(name)
        if (not item or len(item.get("net", [])) < 2
                or not item.get("dates") or item["dates"][-1] != latest_date):
            members.append({
                "name": name,
                "net": None,
                "change": None,
                "long_change": None,
                "short_change": None,
                "visible": False,
                "has_data": False,
            })
            continue
        net = item["net"]
        previous, current = float(net[-2]), float(net[-1])
        members.append({
            "name": name,
            "net": round(current),
            "change": round(current - previous),
            "long_change": round(max(current, 0) - max(previous, 0)),
            "short_change": round(max(-current, 0) - max(-previous, 0)),
            "visible": bool(current or previous),
            "has_data": True,
        })
    return sorted(
        members,
        key=lambda x: (x["visible"], abs(x["change"] or 0)),
        reverse=True,
    )


def _contract_item(data, display, cohort, target):
    for variety, cohorts in data.items():
        if display.get(variety, variety) == target and cohort in cohorts:
            return variety, cohorts[cohort]
    return None, None


def _position_snapshot(item):
    net = item.get("net", [])
    if len(net) < 2:
        return None
    previous, current = float(net[-2]), float(net[-1])
    net_change = current - previous
    long_change = max(current, 0) - max(previous, 0)
    short_change = max(-current, 0) - max(-previous, 0)
    return {
        "net": round(current),
        "net_change": round(net_change),
        "long_change": round(long_change),
        "short_change": round(short_change),
    }


def _cohort_net_series(dates, net):
    n = min(len(dates), len(net), 90)
    return dates[-n:], [round(float(value)) for value in net[-n:]]


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
    """Scan every available contract and retain details for strong relationships."""
    broker_data = broker_data or {}
    cohort_members = cohort_members or {}
    contracts = sorted(
        ((DISPLAY_ALIASES.get(display.get(variety, variety), display.get(variety, variety)),
          display.get(variety, variety), variety) for variety in data),
        key=lambda row: row[0],
    )
    scans = []
    for cohort in COHORTS:
        qualified = []
        rankings = []
        analyzed = 0
        for canonical_name, source_name, variety in contracts:
            dates, flows, returns = _daily_series(
                data, cohort, "contract", source_name, display, sectors, multipliers
            )
            result = _analyze(dates, flows, returns)
            if not result:
                continue
            analyzed += 1
            direction = 1 if result["mode"] == "顺向" else -1
            effective_correlation = result["oos"]["ic"] * direction
            rankings.append({
                "name": canonical_name,
                "mode": result["mode"],
                "horizon": result["horizon"],
                "correlation": result["oos"]["ic"],
                "effective_correlation": round(effective_correlation, 4),
                "samples": result["oos"]["samples"],
            })
            if effective_correlation < DISPLAY_MIN_CORRELATION or result["oos"]["samples"] < DISPLAY_MIN_SAMPLES:
                continue
            item = data.get(variety, {}).get(cohort)
            if not item:
                continue
            members = _member_stats(
                broker_data, variety, cohort_members.get(cohort, []), result["latest_date"]
            )
            snapshot = _position_snapshot(item)
            if not snapshot:
                continue
            item_dates, net_series = _cohort_net_series(
                item.get("dates", []), item.get("net", [])
            )
            qualified.append({
                "name": canonical_name,
                "source_name": source_name,
                "mode": result["mode"],
                "horizon": result["horizon"],
                "correlation": result["oos"]["ic"],
                "effective_correlation": round(effective_correlation, 4),
                "samples": result["oos"]["samples"],
                "oos_start": result["oos_start"],
                "latest_date": result["latest_date"],
                **snapshot,
                "members": members,
                "dates": item_dates,
                "net_series": net_series,
            })
        qualified.sort(key=lambda row: row["effective_correlation"], reverse=True)
        rankings.sort(key=lambda row: row["effective_correlation"], reverse=True)
        scans.append({
            "cohort": cohort,
            "requested": len(contracts),
            "analyzed": analyzed,
            "rankings": rankings,
            "results": qualified,
        })

    return {
        "method": {
            "lookback": LOOKBACK,
            "horizons": list(HORIZONS),
            "signal_threshold": SIGNAL_THRESHOLD,
            "train_ratio": TRAIN_RATIO,
            "min_samples": DISPLAY_MIN_SAMPLES,
            "min_correlation": DISPLAY_MIN_CORRELATION,
            "contracts": [name for name, _, _ in contracts],
            "price": "品种未来收益",
        },
        "scans": scans,
    }
