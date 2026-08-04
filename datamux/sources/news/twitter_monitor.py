"""Twitter/X account monitor — Playwright-based profile scraping.

Reads a flat KOL list from an external YAML file with the shape:

    accounts:
      - {handle: JavierBlas, tier: 1, tags: [oil_energy, journalist, framing]}
      - {handle: niubi,      tier: 2, tags: [china_macro, geopolitics, framing]}
      - {handle: SamRo,      tier: 3, tags: [macro, journalist]}

A single source instance filters by `tier`. `news_type` is set to `tags[0]`
(primary) and the full `tags` list plus `tier` go into `raw_json` for
downstream multi-tag dispatch in kol-digest.

Multiple instances (tier1 / tier2 / tier3) are expected to run with different
cadences and distinct `name_suffix` values; their cursors are namespaced via
`self.name = "twitter_x_{suffix}"`, while the `news_items.source` column
stays `"twitter_x"` (hardcoded literal in `_normalize`) so downstream
queries keep working.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from datamux.core.source import BasePollingSource, SyncSourceMixin
from datamux.core.types import FetchResult, utcnow_iso

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

ROW_SOURCE = "twitter_x"  # value written to news_items.source — never changes

# Profile text and metrics come from the DOM/API; these resources only add bandwidth.
BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})

# Engagement threshold for marking tweets as important
IMPORTANT_ENGAGEMENT = 100

# Max age in days for tweets (filters out pinned tweets from years ago)
MAX_TWEET_AGE_DAYS = 7

# Meta tags do not create kol-digest bundles; they only flavor LLM prompts.
VALID_TIERS = frozenset({1, 2, 3})

META_TAGS = frozenset({
    "framing", "journalist", "sellside", "official", "thinktank", "sovereign",
})


def _route_profile_resource(route: Any) -> None:
    """Skip heavy presentation assets while preserving page data requests."""
    if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
        route.abort()
    else:
        route.continue_()


def _parse_count(text: str) -> int:
    """Parse Twitter count strings like '1.2K', '3.4M', or '39.6万'."""
    if not text:
        return 0
    text = text.strip().lower().replace(",", "").replace("，", "")
    try:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([kmb万亿]?)", text)
        if not match:
            return 0
        value = float(match.group(1))
        unit = match.group(2)
        multipliers = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "万": 10_000, "亿": 100_000_000}
        return int(value * multipliers[unit])
    except (ValueError, TypeError):
        return 0


def _parse_cookies(raw_json: str) -> list[dict]:
    """Parse cookie JSON string into Playwright-compatible cookie list."""
    cookies = json.loads(raw_json)
    return [
        {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".x.com"),
            "path": c.get("path", "/"),
        }
        for c in cookies
    ]


def _detect_language(text: str) -> str:
    """Lightweight language detection based on script distribution."""
    if not text:
        return "en"
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    arabic = sum(1 for c in text if "؀" <= c <= "ۿ")
    total = len(text.replace(" ", ""))
    if total == 0:
        return "en"
    if cjk / total > 0.3:
        return "zh"
    if arabic / total > 0.3:
        return "ar"
    return "en"


def _load_accounts(path: str) -> list[dict]:
    """Load and validate the flat KOL list. Raises on duplicate handles.

    `path` is resolved against:
      1. as-is (absolute, or relative to CWD),
      2. the datamux package directory (same convention as `jobs.yaml`).
    """
    candidates: list[Path] = [Path(path)]
    pkg_dir = Path(__file__).resolve().parent.parent.parent  # .../datamux/
    candidates.append(pkg_dir / path)
    resolved: Path | None = next((c for c in candidates if c.is_file()), None)
    if resolved is None:
        raise FileNotFoundError(
            f"kol_accounts file not found; tried: {[str(c) for c in candidates]}"
        )
    with open(resolved, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("accounts", []) or []
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"kol_accounts: entry is not a mapping: {entry!r}")
        handle = (entry.get("handle") or "").strip()
        try:
            tier = int(entry.get("tier"))
        except (TypeError, ValueError):
            tier = 0
        tags = entry.get("tags") or []
        if not handle:
            raise ValueError(f"kol_accounts: missing handle in entry {entry!r}")
        if tier not in VALID_TIERS:
            raise ValueError(
                f"kol_accounts: @{handle} has invalid tier {tier!r} "
                f"(must be one of {sorted(VALID_TIERS)})"
            )
        if not isinstance(tags, list) or not tags:
            raise ValueError(f"kol_accounts: @{handle} has no tags")
        key = handle.lower()
        if key in seen:
            raise ValueError(
                f"kol_accounts: duplicate handle @{handle} (tier {seen[key]['tier']} and {tier})"
            )
        seen[key] = entry
        out.append({"handle": handle, "tier": tier, "tags": [str(t) for t in tags]})
    return out


class TwitterMonitorSource(SyncSourceMixin, BasePollingSource):
    """Monitor Twitter/X expert accounts via Playwright profile scraping.

    Args:
        accounts_file: Path (absolute or relative to the datamux package root)
            to the flat KOL list YAML.
        tier: Filter — only handles with this tier are scraped by this instance.
        name_suffix: Appended to self.name to namespace the cursor row in
            `source_state` (e.g. suffix "t1" → self.name = "twitter_x_t1").
        cookies_file / cookies_env: where to load X cookies.
        max_tweets_per_account: cap per profile per poll.
        wall_clock_budget_seconds: optional soft budget; the loop breaks if
            elapsed time exceeds this, deferring remaining handles to the
            next cycle (cursor is per-handle, so no data loss).
    """

    data_type = "news"

    def __init__(
        self,
        *,
        accounts_file: str,
        tier: int,
        name_suffix: str = "",
        cookies_file: str = "",
        cookies_env: str = "TWITTER_COOKIES",
        max_tweets_per_account: int = 10,
        wall_clock_budget_seconds: int | None = None,
    ):
        self.name = ROW_SOURCE + (f"_{name_suffix}" if name_suffix else "")
        self._tier = int(tier)
        self._cookies_file = cookies_file
        self._cookies_env = cookies_env
        self._max_tweets = int(max_tweets_per_account)
        self._budget = wall_clock_budget_seconds
        self.profile_metrics: dict[str, dict[str, Any]] = {}

        all_specs = _load_accounts(accounts_file)
        self._specs: list[dict] = [s for s in all_specs if s["tier"] == self._tier]
        if not self._specs:
            logger.warning(
                "twitter_x: no handles match tier=%d in %s", self._tier, accounts_file
            )

    def _load_cookies(self) -> str:
        """Load cookies from file (priority) or environment variable."""
        if self._cookies_file:
            path = os.path.expanduser(self._cookies_file)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    return f.read().strip()
        return os.environ.get(self._cookies_env, "")

    def _fetch_sync(self, cursor: dict[str, Any] | None) -> FetchResult:
        last_ids: dict[str, str] = (cursor or {}).get("last_ids", {})

        cookies_raw = self._load_cookies()
        if not cookies_raw:
            logger.warning(
                "%s: no cookies (checked file=%s, env=%s)",
                self.name, self._cookies_file, self._cookies_env,
            )
            return FetchResult(
                source=self.name,
                data_type=self.data_type,
                items=[],
                cursor={"last_ids": last_ids},
            )

        try:
            pw_cookies = _parse_cookies(cookies_raw)
        except Exception:
            logger.error("%s: invalid %s JSON", self.name, self._cookies_env)
            return FetchResult(
                source=self.name,
                data_type=self.data_type,
                items=[],
                cursor={"last_ids": last_ids},
            )

        items: list[dict] = []
        self.profile_metrics = {}
        new_last_ids = dict(last_ids)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("%s: playwright not installed", self.name)
            return FetchResult(
                source=self.name, data_type=self.data_type, items=[],
                cursor={"last_ids": last_ids},
            )

        started = time.monotonic()
        truncated = False

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=USER_AGENT)
                context.add_cookies(pw_cookies)
                context.route("**/*", _route_profile_resource)
                page = context.new_page()
                page.on("response", self._capture_profile_response)

                for spec in self._specs:
                    if self._budget and (time.monotonic() - started) > self._budget:
                        truncated = True
                        logger.warning(
                            "%s: wall-clock budget %ds exhausted; deferring remaining handles",
                            self.name, self._budget,
                        )
                        break
                    handle = spec["handle"]
                    tags = spec["tags"]
                    prev_last_id = last_ids.get(handle)
                    h_t0 = time.monotonic()
                    try:
                        tweets = self._scrape_profile(page, handle, prev_last_id)
                        if handle.lower() not in self.profile_metrics:
                            self._capture_profile_dom(page, handle)
                        h_dur = time.monotonic() - h_t0
                        for tweet in tweets:
                            items.append(self._normalize(tweet, handle, tags))
                        if tweets:
                            new_last_ids[handle] = tweets[0]["tweet_id"]
                            logger.debug(
                                "%s: @%s -> %d tweets in %.1fs",
                                self.name, handle, len(tweets), h_dur,
                            )
                        else:
                            logger.debug(
                                "%s: @%s -> 0 tweets in %.1fs",
                                self.name, handle, h_dur,
                            )
                    except Exception as exc:
                        h_dur = time.monotonic() - h_t0
                        logger.warning(
                            "%s: failed @%s after %.1fs: %s",
                            self.name, handle, h_dur, exc,
                        )
            finally:
                browser.close()

        logger.info(
            "%s: fetched %d tweets from %d/%d handles%s",
            self.name, len(items),
            len([h for h in self._specs if h["handle"] in new_last_ids]),
            len(self._specs),
            " (truncated)" if truncated else "",
        )
        return FetchResult(
            source=self.name,
            data_type=self.data_type,
            items=items,
            cursor={"last_ids": new_last_ids},
        )

    def collect_profile_metrics_only(self, settle_ms: int = 300) -> dict[str, dict[str, Any]]:
        """Collect public profile metrics without waiting for tweet articles."""
        cookies_raw = self._load_cookies()
        if not cookies_raw:
            logger.warning("%s: no cookies for follower collection", self.name)
            return {}
        try:
            pw_cookies = _parse_cookies(cookies_raw)
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            logger.error("%s: follower collector setup failed: %s", self.name, exc)
            return {}

        self.profile_metrics = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=USER_AGENT)
                context.add_cookies(pw_cookies)
                context.route("**/*", _route_profile_resource)
                page = context.new_page()
                page.on("response", self._capture_profile_response)
                for index, spec in enumerate(self._specs, 1):
                    handle = spec["handle"]
                    try:
                        with page.expect_response(
                            lambda response: "UserByScreenName" in response.url,
                            timeout=6_000,
                        ) as response_info:
                            page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=8_000)
                        self._capture_profile_response(response_info.value)
                        if handle.lower() not in self.profile_metrics:
                            page.wait_for_timeout(settle_ms)
                            self._capture_profile_dom(page, handle)
                    except Exception as exc:
                        page.wait_for_timeout(settle_ms)
                        self._capture_profile_dom(page, handle)
                        if handle.lower() not in self.profile_metrics:
                            logger.warning("%s: follower collection failed @%s: %s", self.name, handle, exc)
                    if index % 25 == 0:
                        logger.info("%s: follower progress %d/%d", self.name, index, len(self._specs))
            finally:
                browser.close()
        return dict(self.profile_metrics)

    def _capture_profile_response(self, response: Any) -> None:
        """Capture exact public follower counts from X's profile response."""
        if "UserByScreenName" not in str(getattr(response, "url", "")):
            return
        try:
            payload = response.json()
            result = (((payload.get("data") or {}).get("user") or {}).get("result") or {})
            core = result.get("core") or {}
            counts = result.get("relationship_counts") or {}
            handle = str(core.get("screen_name") or "").strip()
            followers = counts.get("followers")
            if not handle or followers is None:
                return
            self.profile_metrics[handle.lower()] = {
                "handle": handle,
                "followers_count": int(followers),
                "following_count": int(counts.get("following") or 0),
                "source": "x_profile_response",
                "fetched_at": utcnow_iso(),
            }
        except Exception:
            logger.debug("%s: failed to parse profile metrics response", self.name)

    def _capture_profile_dom(self, page: Any, handle: str) -> None:
        """Fallback to the visible compact follower count when API capture misses."""
        try:
            selector = (
                f'a[href="/{handle}/verified_followers"],'
                f'a[href="/{handle}/followers"]'
            )
            link = page.query_selector(selector)
            followers = _parse_count(link.inner_text() if link else "")
            if followers <= 0:
                return
            self.profile_metrics[handle.lower()] = {
                "handle": handle,
                "followers_count": followers,
                "following_count": None,
                "source": "x_profile_dom_compact",
                "fetched_at": utcnow_iso(),
            }
        except Exception:
            logger.debug("%s: failed DOM follower fallback for @%s", self.name, handle)

    def normalize(self, raw: Any) -> list[dict]:
        return [raw] if isinstance(raw, dict) else []

    def _scrape_profile(self, page, handle: str, last_id: str | None) -> list[dict]:
        """Scrape recent tweets from a user's profile page.

        Two timeout tightenings vs upstream:
          1. `goto` gets an 8s cap (X usually returns dcl in <1s; anything
             longer means the network or the JS bundle is stuck).
          2. `wait_for_selector` for tweet articles is 10s (real profiles
             render articles in 1-2s on a warm context but a slow profile
             like JavierBlas can take 5-8s; 10s is a 2-3x margin over normal
             yet still 33% lower than the prior 15s. Net cost saved per dead
             handle: 5s).

        After a selector timeout we probe the body once for dead-account
        markers and log them at INFO level so the operator can prune
        kol_accounts.yaml. This costs +0.1s only on misses, not on hits.
        """
        try:
            page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=8_000)
        except Exception as exc:
            logger.debug("%s: goto failed for @%s: %s", self.name, handle, exc)
            return []

        try:
            page.wait_for_selector(
                'article[data-testid="tweet"]', timeout=10_000,
            )
        except Exception:
            # Distinguish dead handles from slow/blocked ones so the operator
            # can prune them. Reading body.innerText is a few ms.
            try:
                body_snippet = page.evaluate("() => document.body.innerText.slice(0, 600)") or ""
            except Exception:
                body_snippet = ""
            if any(marker in body_snippet for marker in (
                "doesn’t exist", "doesn't exist",
                "Account suspended", "has been suspended",
            )):
                logger.info("%s: @%s appears dead/suspended; skipping", self.name, handle)
            else:
                logger.debug("%s: no tweets loaded for @%s", self.name, handle)
            return []

        time.sleep(1.0)
        articles = page.query_selector_all('article[data-testid="tweet"]')

        tweets: list[dict] = []
        for article in articles[:self._max_tweets]:
            tweet = self._extract_tweet(article, handle)
            if not tweet:
                continue
            if tweet["tweet_id"] == last_id:
                break
            tweets.append(tweet)

        return tweets

    def _extract_tweet(self, article, expected_handle: str) -> dict | None:
        """Extract tweet data from an article element (vibuzz pattern)."""
        time_el = article.query_selector("time")
        if not time_el:
            return None

        href = time_el.evaluate("el => el.parentElement?.href || ''")
        if not href:
            return None

        id_match = re.search(r"/status/(\d+)", href)
        if not id_match:
            return None
        tweet_id = id_match.group(1)

        # Skip retweets from other users
        user_el = article.query_selector('[data-testid="User-Name"]')
        if user_el:
            user_text = user_el.inner_text()
            handle_match = re.search(r"@(\w+)", user_text)
            if handle_match:
                actual_handle = handle_match.group(1).lower()
                if actual_handle != expected_handle.lower():
                    return None

        text_el = article.query_selector('[data-testid="tweetText"]')
        content = text_el.inner_text() if text_el else ""
        if not content:
            return None

        like_el = article.query_selector('[data-testid="like"] span')
        reply_el = article.query_selector('[data-testid="reply"] span')
        retweet_el = article.query_selector('[data-testid="retweet"] span')

        likes = _parse_count(like_el.inner_text() if like_el else "")
        replies = _parse_count(reply_el.inner_text() if reply_el else "")
        retweets = _parse_count(retweet_el.inner_text() if retweet_el else "")

        timestamp = time_el.get_attribute("datetime") or ""

        if timestamp:
            try:
                tweet_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - tweet_time).total_seconds() / 86400
                if age_days > MAX_TWEET_AGE_DAYS:
                    return None
            except (ValueError, TypeError):
                pass

        return {
            "tweet_id": tweet_id,
            "url": href,
            "content": content,
            "timestamp": timestamp,
            "likes": likes,
            "replies": replies,
            "retweets": retweets,
            "engagement": likes + replies + retweets,
        }

    def _normalize(self, tweet: dict, handle: str, tags: list[str]) -> dict:
        """Normalize a scraped tweet into news_items schema.

        `news_items.source` is hardcoded to ROW_SOURCE so the column stays
        constant across tier instances and downstream queries
        (kol-digest, MCP) keep working with `WHERE source='twitter_x'`.
        """
        now = utcnow_iso()
        content = tweet["content"]
        engagement = tweet["engagement"]
        primary_tag = tags[0] if tags else "other"

        return {
            "source": ROW_SOURCE,
            "source_id": f"tw_{tweet['tweet_id']}",
            "title": content[:200],
            "body": content,
            "url": tweet["url"],
            "author": f"@{handle}",
            "published_at": tweet.get("timestamp", ""),
            "language": _detect_language(content),
            "news_type": primary_tag,
            "important": 1 if engagement >= IMPORTANT_ENGAGEMENT else 0,
            "raw_json": json.dumps({
                "handle": handle,
                "tags": tags,
                "tier": self._tier,
                "likes": tweet["likes"],
                "replies": tweet["replies"],
                "retweets": tweet["retweets"],
            }, ensure_ascii=False),
            "fetched_at": now,
            "analysis_status": "pending",
            "claimed_at": None,
            "claim_token": None,
            "analysis_json": None,
            "analysis_model": None,
            "created_at": now,
            "updated_at": now,
        }
