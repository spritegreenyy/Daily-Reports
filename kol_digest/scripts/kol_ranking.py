"""Transparent daily KOL and viewpoint priority scoring.

Scores measure research priority, not forecast accuracy. Follower data is
deliberately excluded until a verified follower-history feed is available.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from kol_indices import direction


MARKET_TERMS = (
    "inflation", "rates", "rate cut", "rate hike", "yield", "bond", "treasury",
    "federal reserve", "fed", "central bank", "liquidity", "fiscal", "debt",
    "deficit", "recession", "growth", "economy", "economic", "tax", "pension",
    "dollar", "currency", "yen", "euro", "market", "stocks", "equity", "vix",
    "margin", "earnings", "valuation", "positioning", "consensus", "volatility",
    "oil", "crude", "gas", "lng", "gold", "silver", "copper", "soy", "wheat",
    "corn", "commodity", "commodities", "inventory", "supply", "demand", "opec",
    "iran", "ukraine", "russia", "war", "conflict", "sanction", "missile",
    "trade", "tariff", "diplomacy", "military", "geopolitic",
    "ai", "artificial intelligence", "chip", "semiconductor", "nvidia", "gpu",
    "model", "inference", "software", "agent", "capex", "data center",
    "weather", "heat", "drought", "temperature", "hurricane", "rainfall",
    "通胀", "利率", "降息", "加息", "收益率", "债券", "美联储", "央行", "流动性",
    "财政", "债务", "赤字", "衰退", "增长", "经济", "税", "养老金", "美元", "日元",
    "市场", "股票", "估值", "波动", "原油", "天然气", "黄金", "白银", "铜", "大豆",
    "小麦", "玉米", "库存", "供应", "需求", "战争", "冲突", "制裁", "贸易", "关税",
    "人工智能", "芯片", "半导体", "算力", "模型", "推理", "软件", "天气", "高温", "干旱",
)

OPINION_TERMS = (
    "i think", "i believe", "i expect", "my view", "my base case", "bullish",
    "bearish", "buy", "sell", "long", "short", "upside", "downside", "risk",
    "likely", "unlikely", "underpriced", "overpriced", "should", "could",
    "我认为", "判断", "预计", "预期", "看多", "看空", "偏多", "偏空", "买入", "卖出",
    "做多", "做空", "上行", "下行", "风险", "可能", "应当",
)

RESEARCH_TAGS = {
    "teacher_required", "contrarian_signal", "research", "data", "rates_fx",
    "central_banks", "supply_demand", "oil_energy", "global_macro", "economics",
    "fund_manager", "trader", "technical", "cycle", "long_cycle",
}

BOARD_LABELS = {
    "macro": ("宏观", "Macro"),
    "geopolitics": ("地缘", "Geopolitics"),
    "commodities": ("大宗", "Commodities"),
    "softs": ("软商品", "Softs"),
    "weather": ("天气", "Weather"),
    "ai_semis": ("AI / 半导体", "AI / Semis"),
}


def _percentiles(values: list[int]) -> list[float]:
    if not values:
        return []
    logs = [math.log1p(max(0, value)) for value in values]
    ordered = sorted(logs)
    if len(ordered) == 1:
        return [1.0]
    return [sum(candidate <= value for candidate in ordered) / len(ordered) for value in logs]


def _term_hits(text: str, terms: tuple[str, ...]) -> int:
    lower = text.lower()
    return sum(1 for term in terms if term in lower)


def _recency_score(value: str, generated_at: datetime | None) -> float:
    if not value or generated_at is None:
        return 3.0
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        generated = generated_at
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        hours = max(0.0, (generated - published).total_seconds() / 3600)
    except (TypeError, ValueError):
        return 3.0
    return round(max(0.0, 5.0 * (1.0 - hours / 36.0)), 1)


def _parse_generated(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError:
            return None


def build_rankings(tweets: list[dict[str, Any]], generated_at: str = "") -> dict[str, Any]:
    """Return scored views, diversified top views, and daily KOL rankings."""
    generated = _parse_generated(generated_at)
    engagement_percentiles = _percentiles([int(row.get("eng") or 0) for row in tweets])
    scored: list[dict[str, Any]] = []

    for row, engagement_pct in zip(tweets, engagement_percentiles):
        text_zh = str(row.get("x_zh") or row.get("x_en") or "").strip()
        text_en = str(row.get("x_en") or row.get("x_zh") or "").strip()
        source_text = f"{text_zh} {text_en}"
        tags = {str(tag).lower() for tag in row.get("tags", [])}
        tier = int(row.get("tier") or 3)
        market_hits = _term_hits(source_text, MARKET_TERMS)
        opinion_hits = _term_hits(source_text, OPINION_TERMS)
        signal_direction = direction(source_text)

        source = 20.0 if tier == 1 else (15.0 if tier == 2 else 10.0)
        relevance = 0.0
        relevance += 8.0 if row.get("important") else 0.0
        relevance += 5.0 if "viewpoint" in tags else 0.0
        relevance += min(5.0, 2.5 * len(tags & RESEARCH_TAGS))
        relevance += min(12.0, 3.0 * market_hits)
        relevance = min(30.0, relevance)
        engagement = round(20.0 * engagement_pct, 1)
        stance = 15.0 if signal_direction and opinion_hits >= 2 else (10.0 if signal_direction else (8.0 if opinion_hits else 3.0))
        specificity = 0.0
        specificity += 4.0 if re.search(r"\d", source_text) else 0.0
        specificity += 3.0 if 80 <= len(source_text) <= 900 else 1.0
        specificity += 3.0 if any(term in source_text.lower() for term in ("because", "therefore", "implies", "risk", "due to", "因为", "因此", "意味着", "风险")) else 0.0
        freshness = _recency_score(str(row.get("t") or ""), generated)
        penalty = 18.0 if market_hits == 0 else round(max(0.0, (20.0 - relevance) * 1.5), 1)
        content_lengths = [len(value) for value in (text_zh, text_en) if value]
        shortest_content = min(content_lengths) if content_lengths else 0
        if shortest_content < 50:
            penalty += 12.0
        elif shortest_content < 80:
            penalty += 6.0
        total = round(max(0.0, min(100.0, source + relevance + engagement + stance + specificity + freshness - penalty)), 1)
        board = str(row.get("b") or "macro")
        label_zh, label_en = BOARD_LABELS.get(board, (board, board))
        scored.append({
            "handle": str(row.get("h") or ""),
            "board": board,
            "board_zh": label_zh,
            "board_en": label_en,
            "text_zh": text_zh,
            "text_en": text_en,
            "url": str(row.get("u") or ""),
            "engagement": int(row.get("eng") or 0),
            "tier": tier,
            "direction": signal_direction,
            "score": total,
            "breakdown": {
                "relevance": round(relevance, 1),
                "source": source,
                "engagement": engagement,
                "stance": stance,
                "specificity": round(specificity, 1),
                "freshness": freshness,
                "noise_penalty": penalty,
            },
        })

    by_handle: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in scored:
        by_handle[item["handle"].lower()].append(item)

    kol_rows = []
    max_engagements = [max(row["engagement"] for row in rows) for rows in by_handle.values()]
    kol_engagement_percentiles = _percentiles(max_engagements)
    for (handle_key, rows), engagement_pct in zip(by_handle.items(), kol_engagement_percentiles):
        rows.sort(key=lambda item: item["score"], reverse=True)
        top_scores = [item["score"] for item in rows[:3]]
        tier = min(item["tier"] for item in rows)
        view_quality = 0.5 * (sum(top_scores) / len(top_scores))
        source_quality = 20.0 if tier == 1 else (15.0 if tier == 2 else 10.0)
        engagement_quality = 15.0 * engagement_pct
        consistency = min(15.0, 5.0 * sum(item["score"] >= 55 for item in rows))
        score = round(min(100.0, view_quality + source_quality + engagement_quality + consistency), 1)
        kol_rows.append({
            "handle": rows[0]["handle"],
            "score": score,
            "tier": tier,
            "views": len(rows),
            "qualified_views": sum(item["score"] >= 55 for item in rows),
            "top_view_score": rows[0]["score"],
            "engagement": max(item["engagement"] for item in rows),
        })

    kol_rows.sort(key=lambda item: (-item["score"], -item["top_view_score"], item["handle"].lower()))
    kol_score_by_handle = {item["handle"].lower(): item["score"] for item in kol_rows}
    for item in scored:
        item["kol_score"] = kol_score_by_handle.get(item["handle"].lower(), 0.0)

    scored.sort(key=lambda item: (-item["score"], -item["kol_score"], -item["engagement"]))
    selected: list[dict[str, Any]] = []
    used_handles: set[str] = set()
    board_counts: dict[str, int] = defaultdict(int)
    for item in scored:
        handle_key = item["handle"].lower()
        if item["score"] < 45 or handle_key in used_handles or board_counts[item["board"]] >= 2:
            continue
        selected.append(item)
        used_handles.add(handle_key)
        board_counts[item["board"]] += 1
        if len(selected) == 5:
            break
    if len(selected) < 5:
        for item in scored:
            handle_key = item["handle"].lower()
            if item["score"] < 45 or handle_key in used_handles:
                continue
            selected.append(item)
            used_handles.add(handle_key)
            if len(selected) == 5:
                break

    return {
        "method": {
            "view_score": {
                "relevance": 30,
                "source_quality": 20,
                "engagement": 20,
                "stance_clarity": 15,
                "specificity": 10,
                "freshness": 5,
            },
            "kol_score": {
                "view_quality": 50,
                "source_quality": 20,
                "engagement": 15,
                "consistent_output": 15,
            },
            "noise_penalty": "off-topic, low-relevance, or very short low-information content",
            "note_zh": "分数衡量当日研究优先级，不代表观点正确率；暂不包含粉丝量。",
            "note_en": "Scores measure daily research priority, not forecast accuracy; follower data is not yet included.",
        },
        "top_views": selected,
        "top_kols": kol_rows[:10],
        "scored_views": len(scored),
    }
