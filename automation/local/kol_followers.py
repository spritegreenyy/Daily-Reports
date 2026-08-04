"""Persist daily KOL follower snapshots and compute real growth deltas."""

from __future__ import annotations

import json
from datetime import date as date_type, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


def _load_accounts(path: str | Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    accounts = []
    for item in payload.get("accounts", []):
        handle = str(item.get("handle") or "").strip()
        if not handle:
            continue
        accounts.append({
            "handle": handle,
            "tier": int(item.get("tier") or 3),
            "tags": list(item.get("tags") or []),
        })
    return accounts


def _load_prior_snapshots(report_root: Path, report_date: date_type) -> list[dict[str, Any]]:
    snapshots = []
    for path in sorted(report_root.glob("????????/KOL粉丝_????????.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            snapshot_date = date_type.fromisoformat(str(payload.get("date") or ""))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if snapshot_date < report_date:
            payload["_date"] = snapshot_date
            snapshots.append(payload)
    return snapshots


def _account_map(snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not snapshot:
        return {}
    return {
        str(item.get("handle") or "").lower(): item
        for item in snapshot.get("accounts", [])
        if item.get("handle") and item.get("followers_count") is not None
    }


def _pct(delta: int | None, previous: int | None) -> float | None:
    if delta is None or not previous:
        return None
    return round(100.0 * delta / previous, 4)


def build_snapshot(
    *,
    accounts: list[dict[str, Any]],
    metrics: dict[str, dict[str, Any]],
    report_date: date_type,
    prior_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    prior_snapshots = sorted(prior_snapshots, key=lambda item: item["_date"])
    previous = prior_snapshots[-1] if prior_snapshots else None
    seven_cutoff = report_date - timedelta(days=7)
    prior_seven = next((item for item in reversed(prior_snapshots) if item["_date"] <= seven_cutoff), None)
    previous_map = _account_map(previous)
    seven_map = _account_map(prior_seven)

    rows = []
    exact_count = compact_count = 0
    for account in accounts:
        key = account["handle"].lower()
        metric = metrics.get(key) or {}
        followers = metric.get("followers_count")
        followers = int(followers) if followers is not None else None
        previous_followers = (previous_map.get(key) or {}).get("followers_count")
        seven_followers = (seven_map.get(key) or {}).get("followers_count")
        delta_1d = followers - int(previous_followers) if followers is not None and previous_followers is not None else None
        delta_7d = followers - int(seven_followers) if followers is not None and seven_followers is not None else None
        source = str(metric.get("source") or "")
        if source == "x_profile_response":
            exact_count += 1
        elif source:
            compact_count += 1
        rows.append({
            **account,
            "followers_count": followers,
            "following_count": metric.get("following_count"),
            "delta_1d": delta_1d,
            "growth_1d_pct": _pct(delta_1d, int(previous_followers) if previous_followers is not None else None),
            "delta_7d": delta_7d,
            "growth_7d_pct": _pct(delta_7d, int(seven_followers) if seven_followers is not None else None),
            "source": source or "missing",
            "fetched_at": metric.get("fetched_at"),
        })

    covered = [row for row in rows if row["followers_count"] is not None]
    comparable = [row for row in covered if row["delta_1d"] is not None]
    growth_pool = [row for row in comparable if row["followers_count"] >= 1_000 and row["delta_1d"] > 0]
    growth_leaders = sorted(growth_pool, key=lambda row: (-(row["growth_1d_pct"] or 0), -row["delta_1d"]))[:20]
    reach_leaders = sorted(growth_pool, key=lambda row: (-row["delta_1d"], -(row["growth_1d_pct"] or 0)))[:20]
    total = len(rows)
    return {
        "date": report_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_accounts": total,
            "covered_accounts": len(covered),
            "coverage_pct": round(100.0 * len(covered) / total, 1) if total else 0.0,
            "exact_accounts": exact_count,
            "compact_fallback_accounts": compact_count,
            "missing_accounts": total - len(covered),
            "comparable_1d_accounts": len(comparable),
            "total_followers": sum(row["followers_count"] for row in covered),
            "previous_snapshot_date": previous.get("date") if previous else None,
            "seven_day_base_date": prior_seven.get("date") if prior_seven else None,
        },
        "growth_leaders": growth_leaders,
        "reach_leaders": reach_leaders,
        "accounts": rows,
        "method": {
            "delta_1d": "current followers minus the latest prior daily snapshot",
            "growth_1d_pct": "delta_1d / prior followers * 100",
            "growth_leader_floor": "current followers >= 1,000 and delta_1d > 0",
            "interpretation_zh": "粉丝增长衡量观点传播与关注扩散，不代表观点正确性。",
            "interpretation_en": "Follower growth measures attention diffusion, not forecast accuracy.",
        },
    }


def write_daily_snapshot(
    *,
    accounts_file: str | Path,
    metrics: dict[str, dict[str, Any]],
    root: str | Path,
    report_date: str,
) -> Path:
    root = Path(root)
    day = date_type.fromisoformat(report_date)
    report_root = root / "日报"
    destination = report_root / report_date.replace("-", "") / f"KOL粉丝_{report_date.replace('-', '')}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_snapshot(
        accounts=_load_accounts(accounts_file),
        metrics={key.lower(): value for key, value in metrics.items()},
        report_date=day,
        prior_snapshots=_load_prior_snapshots(report_root, day),
    )
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return destination

