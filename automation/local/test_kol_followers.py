import json
from datetime import date

from kol_followers import build_snapshot
from datamux.sources.news.twitter_monitor import _parse_count


def test_parse_localized_counts():
    assert _parse_count("39.6万 关注者") == 396_000
    assert _parse_count("1.2M Followers") == 1_200_000
    assert _parse_count("2.1亿") == 210_000_000


def test_build_snapshot_computes_real_growth():
    accounts = [
        {"handle": "macro", "tier": 1, "tags": ["macro"]},
        {"handle": "oil", "tier": 1, "tags": ["commodities"]},
    ]
    prior = {
        "date": "2026-08-03",
        "_date": date(2026, 8, 3),
        "accounts": [
            {"handle": "macro", "followers_count": 10_000},
            {"handle": "oil", "followers_count": 20_000},
        ],
    }
    metrics = {
        "macro": {"followers_count": 10_500, "source": "x_profile_response"},
        "oil": {"followers_count": 20_100, "source": "x_profile_response"},
    }
    result = build_snapshot(accounts=accounts, metrics=metrics, report_date=date(2026, 8, 4), prior_snapshots=[prior])
    rows = {row["handle"]: row for row in result["accounts"]}
    assert rows["macro"]["delta_1d"] == 500
    assert rows["macro"]["growth_1d_pct"] == 5.0
    assert result["growth_leaders"][0]["handle"] == "macro"
    assert result["reach_leaders"][0]["handle"] == "macro"
    assert result["summary"]["coverage_pct"] == 100.0


def test_first_snapshot_keeps_growth_empty():
    result = build_snapshot(
        accounts=[{"handle": "new", "tier": 2, "tags": ["ai"]}],
        metrics={"new": {"followers_count": 1_234, "source": "x_profile_response"}},
        report_date=date(2026, 8, 4),
        prior_snapshots=[],
    )
    assert result["accounts"][0]["delta_1d"] is None
    assert result["growth_leaders"] == []
