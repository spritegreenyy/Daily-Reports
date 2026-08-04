"""Deterministic KOL anomaly and sentiment-propagation alerts."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date as date_type
from pathlib import Path
from typing import Any


BOARD_ZH = {
    "macro": "宏观",
    "geopolitics": "地缘政治",
    "commodities": "大宗商品",
    "softs": "软商品",
    "weather": "天气气候",
    "ai_semis": "AI / 半导体",
}
BOARD_EN = {
    "macro": "Macro",
    "geopolitics": "Geopolitics",
    "commodities": "Commodities",
    "softs": "Soft Commodities",
    "weather": "Weather",
    "ai_semis": "AI / Semis",
}
MACRO_TAGS = {"rates_fx", "central_banks", "contrarian_signal", "sovereign_debt", "dollar", "liquidity"}
MACRO_TERMS = (
    "interest rate", "rate cut", "rate hike", "yield", "treasury", "federal reserve", " fed ",
    "central bank", "liquidity", "money supply", "fiscal", "sovereign debt", "public debt",
    "dollar", "currency", "inflation", "deflation", "recession",
    "利率", "降息", "加息", "收益率", "美债", "美联储", "央行", "流动性", "货币供应",
    "财政", "主权债务", "公共债务", "美元", "汇率", "通胀", "通缩", "衰退",
)
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
TYPE_ORDER = {"follower_spike": 0, "extreme_stance": 1, "consensus_crowding": 2, "attention_surge": 3, "macro_key_variable": 4}


def build_attention_baseline(output_dir: str | Path, report_date: str, limit: int = 20) -> dict[str, Any]:
    """Build per-board mention-share baselines from prior daily raw dumps."""
    output = Path(output_dir)
    current = date_type.fromisoformat(report_date)
    rows = []
    for path in sorted(output.glob("kol_tweets_????????.json"), reverse=True):
        tag = path.stem[-8:]
        try:
            day = date_type(int(tag[:4]), int(tag[4:6]), int(tag[6:]))
            if day >= current:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        counts = Counter()
        total = 0
        for section in payload.get("sections", []):
            key = str(section.get("key") or "macro")
            count = len(section.get("tweets", []))
            counts[key] += count
            total += count
        if total:
            rows.append({"date": day.isoformat(), "shares": {key: value / total for key, value in counts.items()}})
        if len(rows) >= limit:
            break

    boards = set().union(*(row["shares"].keys() for row in rows)) if rows else set()
    summary = {}
    for board in boards:
        values = [row["shares"].get(board, 0.0) for row in rows]
        summary[board] = {
            "mean": round(statistics.fmean(values), 6),
            "std": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
            "samples": len(values),
        }
    return {"days": [row["date"] for row in rows], "boards": summary}


def _alert(
    alert_type: str,
    severity: str,
    *,
    title_zh: str,
    title_en: str,
    summary_zh: str,
    summary_en: str,
    evidence_zh: str,
    evidence_en: str,
    implication_zh: str,
    implication_en: str,
    handle: str = "",
    url: str = "",
) -> dict[str, Any]:
    return {
        "type": alert_type,
        "severity": severity,
        "title_zh": title_zh,
        "title_en": title_en,
        "summary_zh": summary_zh,
        "summary_en": summary_en,
        "evidence_zh": evidence_zh,
        "evidence_en": evidence_en,
        "implication_zh": implication_zh,
        "implication_en": implication_en,
        "handle": handle,
        "url": url,
    }


def detect_anomalies(
    scored_views: list[dict[str, Any]],
    follower_snapshot: dict[str, Any] | None = None,
    attention_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    follower_snapshot = follower_snapshot or {}
    attention_baseline = attention_baseline or {}
    alerts: list[dict[str, Any]] = []

    # 1. Follower-growth extremes: attention propagation, never truth.
    for row in (follower_snapshot.get("growth_leaders") or [])[:5]:
        growth = float(row.get("growth_1d_pct") or 0.0)
        delta = int(row.get("delta_1d") or 0)
        if growth >= 1.0 or delta >= 10_000:
            severity = "high"
        elif growth >= 0.3 or delta >= 2_000:
            severity = "medium"
        else:
            continue
        handle = str(row.get("handle") or "")
        alerts.append(_alert(
            "follower_spike", severity,
            title_zh=f"粉丝传播异常 · @{handle}",
            title_en=f"Follower Propagation Spike · @{handle}",
            summary_zh=f"单日新增 {delta:+,}，增幅 {growth:+.2f}% 。",
            summary_en=f"Followers changed {delta:+,} in one day ({growth:+.2f}%).",
            evidence_zh=f"当前粉丝 {int(row.get('followers_count') or 0):,}；达到日增幅0.3%或新增2,000的提醒门槛。",
            evidence_en=f"Current followers {int(row.get('followers_count') or 0):,}; crossed the 0.3% or +2,000 daily alert threshold.",
            implication_zh="关注正在快速扩散，需检查其近期主张是否形成拥挤叙事；不代表观点正确。",
            implication_en="Attention is diffusing quickly. Check whether the account's thesis is becoming crowded; this does not imply accuracy.",
            handle=handle,
        ))
        if sum(alert["type"] == "follower_spike" for alert in alerts) >= 2:
            break

    # 2. High-reach, high-score explicit stance.
    stance_candidates = [
        item for item in scored_views
        if item.get("direction") in (-1, 1)
        and float(item.get("score") or 0) >= 68
        and float(item.get("influence_score") or 0) >= 70
        and float((item.get("breakdown") or {}).get("stance") or 0) >= 15
    ]
    for item in stance_candidates[:2]:
        handle = str(item.get("handle") or "")
        direction_zh = "偏多" if item["direction"] > 0 else "偏空"
        direction_en = "bullish" if item["direction"] > 0 else "bearish"
        tags = set(item.get("tags") or [])
        severity = "high" if "contrarian_signal" in tags or float(item.get("score") or 0) >= 80 else "medium"
        text_zh = str(item.get("text_zh") or item.get("text_en") or "")
        text_en = str(item.get("text_en") or item.get("text_zh") or "")
        alerts.append(_alert(
            "extreme_stance", severity,
            title_zh=f"高影响力明确立场 · @{handle} {direction_zh}",
            title_en=f"High-Reach Explicit Stance · @{handle} {direction_en}",
            summary_zh=text_zh[:220] + ("…" if len(text_zh) > 220 else ""),
            summary_en=text_en[:220] + ("…" if len(text_en) > 220 else ""),
            evidence_zh=f"观点分 {item['score']:.1f}；传播分 {float(item.get('influence_score') or 0):.1f}；立场清晰度 {float((item.get('breakdown') or {}).get('stance') or 0):.0f}/15。",
            evidence_en=f"View score {item['score']:.1f}; reach {float(item.get('influence_score') or 0):.1f}; stance clarity {float((item.get('breakdown') or {}).get('stance') or 0):.0f}/15.",
            implication_zh="高传播力账号给出明确方向，需核对是否被其他KOL快速跟随或形成反向拥挤。",
            implication_en="A high-reach account has taken a clear side. Monitor follow-through and contrarian crowding risk.",
            handle=handle,
            url=str(item.get("url") or ""),
        ))

    # 3. Directional consensus crowding by board.
    directional: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in scored_views:
        if item.get("direction") in (-1, 1) and float(item.get("score") or 0) >= 50:
            directional[str(item.get("board") or "macro")].append(item)
    for board, rows in directional.items():
        if len(rows) < 4:
            continue
        positive = sum(item["direction"] > 0 for item in rows)
        negative = len(rows) - positive
        dominant = 1 if positive >= negative else -1
        ratio = max(positive, negative) / len(rows)
        if ratio < 0.80:
            continue
        board_zh, board_en = BOARD_ZH.get(board, board), BOARD_EN.get(board, board)
        direction_zh, direction_en = ("偏多", "bullish") if dominant > 0 else ("偏空", "bearish")
        severity = "high" if ratio >= 0.90 and len(rows) >= 6 else "medium"
        alerts.append(_alert(
            "consensus_crowding", severity,
            title_zh=f"{board_zh}观点一致性过高 · {direction_zh}",
            title_en=f"{board_en} Consensus Crowding · {direction_en}",
            summary_zh=f"{len(rows)}条明确方向观点中，{ratio:.0%}指向{direction_zh}。",
            summary_en=f"{ratio:.0%} of {len(rows)} explicit views point {direction_en}.",
            evidence_zh="达到至少4条方向观点且80%以上同向的拥挤提醒门槛。",
            evidence_en="Crossed the crowding threshold: at least four directional views and 80% aligned.",
            implication_zh="一致性过高可能代表趋势强化，也可能意味着反向交易风险上升。",
            implication_en="Strong consensus can reinforce a trend, but it also raises contrarian reversal risk.",
        ))

    # 4. Board attention share versus the prior 20 reports.
    counts = Counter(str(item.get("board") or "macro") for item in scored_views)
    total = sum(counts.values())
    baselines = attention_baseline.get("boards") or {}
    if total:
        for board, count in counts.items():
            baseline = baselines.get(board) or {}
            if int(baseline.get("samples") or 0) < 5 or count < 5:
                continue
            share = count / total
            mean = float(baseline.get("mean") or 0)
            std = float(baseline.get("std") or 0)
            threshold = max(mean + 2 * std, mean + 0.08)
            if share <= threshold:
                continue
            board_zh, board_en = BOARD_ZH.get(board, board), BOARD_EN.get(board, board)
            alerts.append(_alert(
                "attention_surge", "medium",
                title_zh=f"{board_zh}关注度异常抬升",
                title_en=f"{board_en} Attention Surge",
                summary_zh=f"本期占全部有效观点的 {share:.1%}，过去{int(baseline['samples'])}期均值为 {mean:.1%}。",
                summary_en=f"Current share is {share:.1%} versus a {mean:.1%} mean over the prior {int(baseline['samples'])} reports.",
                evidence_zh="当前占比超过历史均值两倍标准差或至少高出8个百分点。",
                evidence_en="The current share is above two historical standard deviations or at least eight percentage points above the mean.",
                implication_zh="市场讨论正在向该主题集中，需判断是新趋势萌芽还是事件驱动的短期拥挤。",
                implication_en="Discussion is concentrating in this theme. Distinguish an emerging trend from event-driven crowding.",
            ))

    # 5. One macro key variable, if not already represented by an explicit-stance alert.
    represented = {alert.get("handle", "").lower() for alert in alerts}
    macro = []
    for item in scored_views:
        text = f" {item.get('text_zh') or ''} {item.get('text_en') or ''} ".lower()
        if (
            item.get("board") == "macro"
            and float(item.get("score") or 0) >= 68
            and set(item.get("tags") or []) & MACRO_TAGS
            and any(term in text for term in MACRO_TERMS)
            and item.get("handle", "").lower() not in represented
        ):
            macro.append(item)
    if macro:
        item = macro[0]
        handle = str(item.get("handle") or "")
        text_zh = str(item.get("text_zh") or item.get("text_en") or "")
        text_en = str(item.get("text_en") or item.get("text_zh") or "")
        alerts.append(_alert(
            "macro_key_variable", "low",
            title_zh=f"宏观关键变量 · @{handle}",
            title_en=f"Macro Key Variable · @{handle}",
            summary_zh=text_zh[:220] + ("…" if len(text_zh) > 220 else ""),
            summary_en=text_en[:220] + ("…" if len(text_en) > 220 else ""),
            evidence_zh=f"观点分 {item['score']:.1f}，命中利率/央行/美元/流动性等宏观关键标签。",
            evidence_en=f"View score {item['score']:.1f}; matched a key rates, central-bank, dollar, or liquidity tag.",
            implication_zh="列入宏观优先阅读，但只有出现传播或方向异常时才升级为中高等级。",
            implication_en="Prioritize for macro review; escalate only if propagation or directional anomalies emerge.",
            handle=handle,
            url=str(item.get("url") or ""),
        ))

    alerts.sort(key=lambda item: (SEVERITY_ORDER[item["severity"]], TYPE_ORDER[item["type"]]))
    alerts = alerts[:6]
    return {
        "status": "active" if alerts else "normal",
        "count": len(alerts),
        "alerts": alerts,
        "method": {
            "follower_spike": "growth >= 0.3% or delta >= 2,000; high at growth >= 1% or delta >= 10,000",
            "extreme_stance": "view score >= 68, reach percentile >= 70, explicit direction and stance clarity = 15/15",
            "consensus_crowding": "at least four directional views with >= 80% alignment",
            "attention_surge": "share above prior-20 mean + 2 standard deviations or +8 percentage points",
            "interpretation_zh": "异常提醒用于提高研究优先级，不构成交易建议。",
            "interpretation_en": "Alerts raise research priority and are not trading advice.",
        },
    }
