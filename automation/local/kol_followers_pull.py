#!/usr/bin/env python3
"""One-off exact follower snapshot collector for the configured KOL universe."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from datamux.sources.news.twitter_monitor import TwitterMonitorSource
from kol_accounts_merge import merged_accounts_file
from kol_followers import write_daily_snapshot


ACCOUNTS = str(merged_accounts_file(
    ROOT / "datamux/kol_accounts_viewpoint_250.yaml",
    HERE / "kol_soft_accounts.yaml",
    HERE / "kol_accounts_runtime.yaml",
))
COOKIES = str(Path.home() / ".x_cookies.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--settle-ms", type=int, default=300)
    args = parser.parse_args()

    metrics = {}
    for tier in (1, 2, 3):
        source = TwitterMonitorSource(
            accounts_file=ACCOUNTS,
            tier=tier,
            name_suffix=f"followers_t{tier}",
            cookies_file=COOKIES,
            max_tweets_per_account=0,
        )
        tier_metrics = source.collect_profile_metrics_only(settle_ms=args.settle_ms)
        metrics.update(tier_metrics)
        print(f"tier{tier}: {len(tier_metrics)} follower profiles")

    if not metrics:
        print("Follower collection returned no profiles", file=sys.stderr)
        return 2
    destination = write_daily_snapshot(
        accounts_file=ACCOUNTS,
        metrics=metrics,
        root=ROOT,
        report_date=args.date,
    )
    print(f"followers: {len(metrics)} profiles -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
