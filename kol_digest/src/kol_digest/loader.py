"""Pull recent KOL tweets from datamux unified_news.sqlite."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import yaml


VALID_TIERS = frozenset({1, 2, 3})
DEFAULT_ACCOUNTS_FILE = "kol_accounts.yaml"

CATEGORY_ORDER = [
    "macro",
    "central_banks",
    "rates_fx",
    "china_macro",
    "geopolitics",
    "oil_energy",
    "nat_gas_lng",
    "commodities",
    "metals_industrial",
    "precious_metals",
    "agri_softs",
    "weather_climate",
    "ai_semis",
    "technology",
    "semiconductors",
    "shipping_freight",
    "power_carbon",
]
CATEGORY_LABEL = {
    "macro": "宏观",
    "central_banks": "央行",
    "rates_fx": "利率 / 外汇",
    "china_macro": "中国宏观",
    "geopolitics": "地缘政治",
    "oil_energy": "原油 / 能源",
    "nat_gas_lng": "天然气 / LNG",
    "commodities": "大宗商品",
    "metals_industrial": "工业金属",
    "precious_metals": "贵金属",
    "agri_softs": "农产品 / 软商品",
    "weather_climate": "天气气候",
    "ai_semis": "AI / 半导体",
    "technology": "科技",
    "semiconductors": "半导体",
    "shipping_freight": "航运 / 货运",
    "power_carbon": "电力 / 碳",
}


@dataclass(slots=True)
class KolAccount:
    handle: str
    tier: int
    tags: list[str]

    @property
    def primary_tag(self) -> str:
        return self.tags[0] if self.tags else "other"

    def to_dict(self) -> dict:
        return {"handle": self.handle, "tier": self.tier, "tags": self.tags}


@dataclass(slots=True)
class Tweet:
    handle: str
    category: str
    published_at: str
    title: str
    body: str
    url: str
    likes: int
    replies: int
    retweets: int
    engagement: int
    important: int
    language: str
    source_id: str = ""
    tags: list[str] = field(default_factory=list)
    tier: int = 0
    primary_tag: str = "other"

    def to_dict(self) -> dict:
        return {
            "handle": self.handle,
            "category": self.category,
            "primary_tag": self.primary_tag,
            "tags": self.tags,
            "tier": self.tier,
            "published_at": self.published_at,
            "source_id": self.source_id,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "likes": self.likes,
            "replies": self.replies,
            "retweets": self.retweets,
            "engagement": self.engagement,
            "important": self.important,
            "language": self.language,
        }


@dataclass(slots=True)
class CategoryBundle:
    category: str
    label: str
    tweets: list[Tweet] = field(default_factory=list)

    @property
    def handles_count(self) -> int:
        return len({t.handle for t in self.tweets})


def resolve_accounts_path(path: str | Path | None = None) -> Path:
    raw = path or os.environ.get("KOL_DIGEST_ACCOUNTS_FILE") or DEFAULT_ACCOUNTS_FILE
    p = Path(raw).expanduser()
    if p.is_absolute():
        candidates = [p]
    else:
        module_path = Path(__file__).resolve()
        workspace_root = module_path.parents[3]
        candidates = [
            Path.cwd() / p,
            workspace_root / p,
            workspace_root / "datamux" / p,
            Path.cwd().parent / "datamux" / p,
        ]
    resolved = next((c for c in candidates if c.is_file()), None)
    if resolved is None:
        raise FileNotFoundError(
            f"kol accounts file not found; tried: {[str(c) for c in candidates]}"
        )
    return resolved


def load_accounts(path: str | Path | None = None) -> list[KolAccount]:
    resolved = resolve_accounts_path(path)
    with open(resolved, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("accounts", []) or []
    seen: dict[str, KolAccount] = {}
    accounts: list[KolAccount] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"kol_accounts: entry is not a mapping: {entry!r}")
        handle = str(entry.get("handle") or "").strip().lstrip("@")
        try:
            tier = int(entry.get("tier"))
        except (TypeError, ValueError):
            tier = 0
        tags_raw = entry.get("tags") or []
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
        if not handle:
            raise ValueError(f"kol_accounts: missing handle in entry {entry!r}")
        if tier not in VALID_TIERS:
            raise ValueError(
                f"kol_accounts: @{handle} has invalid tier {tier!r} "
                f"(must be one of {sorted(VALID_TIERS)})"
            )
        if not tags:
            raise ValueError(f"kol_accounts: @{handle} has no tags")
        key = handle.lower()
        if key in seen:
            raise ValueError(
                f"kol_accounts: duplicate handle @{handle} "
                f"(also @{seen[key].handle})"
            )
        account = KolAccount(handle=handle, tier=tier, tags=tags)
        seen[key] = account
        accounts.append(account)
    return accounts


def accounts_by_handle(accounts: Iterable[KolAccount]) -> dict[str, KolAccount]:
    return {a.handle.lower(): a for a in accounts}


def load_recent_tweets(
    db_path: str | Path,
    hours: int = 24,
    end_dt: datetime | None = None,
    *,
    accounts: Iterable[KolAccount] | None = None,
) -> list[Tweet]:
    end_dt = end_dt or datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(hours=hours)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    account_map = accounts_by_handle(accounts) if accounts is not None else None

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT source_id, author, news_type, published_at, title, body, url,
                   raw_json, important, language
            FROM news_items
            WHERE source = 'twitter_x'
              AND published_at >= ?
              AND published_at <  ?
            ORDER BY published_at DESC
            """,
            (start_iso, end_iso),
        ).fetchall()
    finally:
        con.close()

    tweets: list[Tweet] = []
    for r in rows:
        meta = {}
        try:
            meta = json.loads(r["raw_json"] or "{}")
        except Exception:
            meta = {}

        handle = (r["author"] or meta.get("handle") or "").lstrip("@")
        account = account_map.get(handle.lower()) if account_map is not None else None
        if account_map is not None and account is None:
            continue

        meta_tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
        tags = list(account.tags if account else meta_tags or [r["news_type"] or "other"])
        tier = int(account.tier if account else meta.get("tier") or 0)
        primary_tag = tags[0] if tags else (r["news_type"] or "other")
        likes = int(meta.get("likes", 0) or 0)
        replies = int(meta.get("replies", 0) or 0)
        retweets = int(meta.get("retweets", 0) or 0)
        tweets.append(
            Tweet(
                handle=account.handle if account else handle,
                category=primary_tag,
                primary_tag=primary_tag,
                tags=tags,
                tier=tier,
                source_id=r["source_id"] or "",
                published_at=r["published_at"] or "",
                title=r["title"] or "",
                body=r["body"] or r["title"] or "",
                url=r["url"] or "",
                likes=likes,
                replies=replies,
                retweets=retweets,
                engagement=likes + replies + retweets,
                important=int(r["important"] or 0),
                language=r["language"] or "en",
            )
        )
    return tweets


def group_by_category(tweets: Iterable[Tweet]) -> list[CategoryBundle]:
    by_cat: dict[str, list[Tweet]] = {c: [] for c in CATEGORY_ORDER}
    for t in tweets:
        by_cat.setdefault(t.category, []).append(t)
    result: list[CategoryBundle] = []
    ordered = list(CATEGORY_ORDER) + sorted(c for c in by_cat if c not in CATEGORY_ORDER)
    for cat in ordered:
        items = by_cat.get(cat, [])
        items.sort(key=lambda x: (x.engagement, x.published_at), reverse=True)
        result.append(CategoryBundle(category=cat, label=CATEGORY_LABEL.get(cat, cat), tweets=items))
    return result


def top_n(bundle: CategoryBundle, n: int = 8) -> list[Tweet]:
    return bundle.tweets[:n]
