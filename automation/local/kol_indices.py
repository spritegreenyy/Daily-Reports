"""Deterministic, backtest-ready KOL direction indices."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Iterable


ASSETS = {
    "energy": {
        "label_zh": "能源",
        "label_en": "Energy",
        "color": "#ef8f4c",
        "terms": (
            r"\boil\b", r"\bcrude\b", r"\bbrent\b", r"\bwti\b", r"\bopec\b",
            r"\bnatural gas\b", r"\bnat gas\b", r"\blng\b", r"\bhenry hub\b",
            "原油", "石油", "天然气", "液化天然气",
        ),
    },
    "metals": {
        "label_zh": "金属",
        "label_en": "Metals",
        "color": "#d8ad55",
        "terms": (
            r"\bgold\b", r"\bsilver\b", r"\bcopper\b", r"\balumin(?:um|ium)\b",
            r"\bzinc\b", r"\bnickel\b", r"\blithium\b", "黄金", "白银", "铜", "铝", "锌", "镍", "锂",
        ),
    },
    "grains": {
        "label_zh": "谷物油籽",
        "label_en": "Grains & Oilseeds",
        "color": "#76b77b",
        "terms": (
            r"\bcorn\b", r"\bmaize\b", r"\bwheat\b", r"\bsoy(?:bean|beans)?\b",
            r"\bsoymeal\b", r"\bsoybean meal\b", r"\bcanola\b", r"\bgrain\b",
            "玉米", "小麦", "大豆", "豆粕", "豆油", "菜籽", "谷物",
        ),
    },
    "softs": {
        "label_zh": "软商品",
        "label_en": "Soft Commodities",
        "color": "#df6f91",
        "terms": (
            r"\bsugar\b", r"\bcoffee\b", r"\bcocoa\b", r"\bcotton\b",
            r"\borange juice\b", r"\bnatural rubber\b", r"\brubber futures\b",
            r"#(?:sb|kc|cc|ct)\b", "白糖", "咖啡", "可可", "棉花", "橙汁", "天然橡胶",
        ),
    },
}

BULLISH = (
    r"\bbullish\b", r"\bbull market\b", r"\bupside\b", r"\brall(?:y|ies|ied)\b",
    r"\brebound\b", r"\bbreakout\b", r"\bbreak higher\b", r"\bgo long\b", r"\blong position\b", r"\bbuy\b",
    r"\bshort covering\b", r"\bsqueeze\b", r"\btight(?:ness)?\b", r"\bshortage\b",
    r"\bdeficit\b", r"\bstrong demand\b", r"\bsupported\b", r"\btailwind\b",
    r"\brising\b", r"\brise[sd]?\b", r"\bclimb(?:s|ed|ing)?\b", r"\bgain(?:s|ed|ing)?\b",
    r"\babove\b", r"\bup \d", r"\bimprov(?:e|es|ed|ing|ement)\b",
    "看多", "偏多", "上涨", "反弹", "突破", "做多", "买入", "逼空", "供应紧张", "短缺", "需求强劲",
)
BEARISH = (
    r"\bbearish\b", r"\bbear market\b", r"\bdownside\b", r"\bsell[ -]?off\b",
    r"\bbreakdown\b", r"\bbreak lower\b", r"\bgo short\b", r"\bshort positions?\b",
    r"\bshorting\b", r"\bsell\b", r"\btrim\b",
    r"\bsurplus\b", r"\bglut\b", r"\bweak demand\b", r"\boversuppl(?:y|ied)\b",
    r"\bheadwind\b", r"\blower prices?\b", r"\bdemand destruction\b",
    r"\bfall(?:s|ing)?\b", r"\bfell\b", r"\bdrop(?:s|ped|ping)?\b", r"\bdeclin(?:e|es|ed|ing)\b",
    r"\bbelow\b", r"\bdown \d",
    "看空", "偏空", "下跌", "回落", "破位", "做空", "卖出", "减仓", "供应过剩", "需求疲弱",
)
NEGATED_BULL = (r"\bnot bullish\b", r"\bno upside\b", r"\bfailed breakout\b")
NEGATED_BEAR = (r"\bnot bearish\b", r"\bno downside\b", r"\bfailed breakdown\b")
COMPOUND_BULL = (
    r"\bshort covering\b", r"\btrim(?:med|ming)? bearish short(?:s| positions?)\b",
    r"\bestablish(?:ed|ing)? new bullish long\b", r"\bshort positioning (?:is )?(?:starting to )?fall\b",
    r"\breduc(?:e|es|ed|ing) (?:global )?(?:oil )?supply\b", r"\bsupply disruption\b",
    r"\bdisrupt(?:s|ed|ing)? supply\b",
)
COMPOUND_BEAR = (
    r"\blong liquidation\b", r"\bincreas(?:e|es|ed|ing) (?:global )?(?:oil )?supply\b",
    r"\bproduction growth\b", r"\bdemand destruction\b",
)
TIER_WEIGHT = {1: 1.5, 2: 1.2, 3: 1.0}


def match_asset_keys(text: str) -> list[str]:
    lower = str(text or "").lower()
    return [key for key, spec in ASSETS.items() if _matches_any(lower, spec["terms"])]


def direction(text: str) -> int:
    lower = str(text or "").lower()
    bull = _count(lower, NEGATED_BEAR) + _count(lower, COMPOUND_BULL)
    bear = _count(lower, NEGATED_BULL) + _count(lower, COMPOUND_BEAR)
    clean = lower
    for phrase in (*NEGATED_BULL, *NEGATED_BEAR, *COMPOUND_BULL, *COMPOUND_BEAR):
        clean = re.sub(phrase, " ", clean, flags=re.I)
    bull += _count(clean, BULLISH)
    bear += _count(clean, BEARISH)
    if bull == bear:
        return 0
    return 1 if bull > bear else -1


def build_daily_index(payload: dict[str, Any], date: str) -> dict[str, Any]:
    buckets = {key: [] for key in ASSETS}
    for section in payload.get("sections", []):
        for tweet in section.get("tweets", []):
            body = str(tweet.get("body") or tweet.get("title") or "")
            keys = match_asset_keys(body)
            if not keys:
                continue
            item = {
                "handle": str(tweet.get("handle") or "").lstrip("@"),
                "direction": direction(body),
                "weight": _weight(tweet),
            }
            for key in keys:
                buckets[key].append(item)

    assets = {}
    for key, spec in ASSETS.items():
        rows = buckets[key]
        signals = [row for row in rows if row["direction"]]
        denominator = sum(row["weight"] for row in signals)
        score = None
        if denominator:
            score = round(100 * sum(row["direction"] * row["weight"] for row in signals) / denominator, 1)
        assets[key] = {
            "label_zh": spec["label_zh"],
            "label_en": spec["label_en"],
            "color": spec["color"],
            "score": score,
            "mentions": len(rows),
            "signal_tweets": len(signals),
            "kols": len({row["handle"].lower() for row in rows if row["handle"]}),
            "bullish": sum(row["direction"] > 0 for row in signals),
            "bearish": sum(row["direction"] < 0 for row in signals),
        }
    return {"date": date, "assets": assets}


def build_index_history(output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    daily = []
    for path in sorted(output.glob("kol_tweets_????????.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        date = f"{path.stem[-8:-4]}-{path.stem[-4:-2]}-{path.stem[-2:]}"
        row = build_daily_index(payload, date)
        daily.append(row)
        (output / f"kol_indices_{path.stem[-8:]}.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    history = {
        "method": {
            "range": [-100, 100],
            "formula": "100 * sum(direction * weight) / sum(weight), directional tweets only",
            "weight": "tier weight (1.5/1.2/1.0) * capped log engagement weight (1.0-2.0)",
            "neutral": "mentions without deterministic direction are excluded from the score denominator",
        },
        "dates": [row["date"] for row in daily],
        "daily": daily,
    }
    (output / "kol_indices_history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return history


def _matches_any(text: str, terms: Iterable[str]) -> bool:
    return any(re.search(term, text, re.I) if _is_regex(term) else term.lower() in text for term in terms)


def _count(text: str, terms: Iterable[str]) -> int:
    return sum(len(re.findall(term, text, re.I)) if _is_regex(term) else text.count(term.lower()) for term in terms)


def _is_regex(term: str) -> bool:
    return term.startswith(r"\b") or term.startswith("#")


def _weight(tweet: dict[str, Any]) -> float:
    tier = int(tweet.get("tier") or 3)
    engagement = max(0, int(tweet.get("engagement") or 0))
    engagement_weight = 1 + min(math.log1p(engagement) / math.log(1001), 1)
    return TIER_WEIGHT.get(tier, 1.0) * engagement_weight
