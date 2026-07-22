"""Opinion-first emphasis for KOL reports; numbers are never the emphasis target."""

from __future__ import annotations

import html
import re


_CLAUSE_RE = re.compile(r"[^，,；;。.!?！？]+[，,；;。.!?！？]?")
_NUMBER_RE = re.compile(
    r"(?:[+\-]?[¥$￥]?\d[\d,]*(?:\.\d+)?(?:%|万亿|亿|万|倍|点|台|个月|年|月|日|天|bps|pt|B|K|MM|美元|元|°C)?)"
)
_OPINION_TERMS = (
    "应", "将", "可能", "预计", "意味着", "表明", "提示", "拥有", "受益",
    "利好", "利空", "风险", "承压", "支撑", "压制", "上行", "下行", "走强",
    "走弱", "重估", "受限", "限制", "警惕", "核心", "超卖", "过剩", "短缺",
    "看多", "看空", "偏多", "偏空", "需", "should", "will", "may", "could",
    "likely", "implies", "signals", "benefit", "risk", "bullish", "bearish",
)
_NON_OPINION_PREFIXES = ("关键数据", "互动", "Key data", "Interactions")


def emphasize_opinion(text: str) -> str:
    """Bold one conclusion clause while keeping every numeric token normal weight."""
    source = str(text or "")
    if not source or source.lstrip().startswith(_NON_OPINION_PREFIXES):
        return html.escape(source)

    clauses = list(_CLAUSE_RE.finditer(source))
    ranked = []
    for index, match in enumerate(clauses):
        clause = match.group(0)
        score = sum(term.lower() in clause.lower() for term in _OPINION_TERMS)
        if score:
            ranked.append((score, index, match))
    if not ranked:
        return html.escape(source)

    _, _, chosen = max(ranked)
    before = html.escape(source[:chosen.start()])
    clause = html.escape(chosen.group(0))
    after = html.escape(source[chosen.end():])
    clause = _NUMBER_RE.sub(r'</b>\g<0><b class="em">', clause)
    highlighted = f'<b class="em">{clause}</b>'
    highlighted = highlighted.replace('<b class="em"></b>', "")
    return before + highlighted + after


def strip_numeric_emphasis(value):
    """Recursively remove legacy bold tags whose content is only a number."""
    if isinstance(value, dict):
        return {key: strip_numeric_emphasis(item) for key, item in value.items()}
    if isinstance(value, list):
        return [strip_numeric_emphasis(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        content = html.unescape(match.group(1)).strip()
        return match.group(1) if _NUMBER_RE.fullmatch(content) else match.group(0)

    return re.sub(r'<b class="em">([^<]*)</b>', replace, value)


def compact_core_points(points, lang: str = "zh") -> list[str]:
    """Keep one core view and one trading conclusion; drop duplicated metadata."""
    is_en = lang == "en"
    view_label = "Core view: " if is_en else "核心观点："
    conclusion_label = "Trading conclusion: " if is_en else "交易结论："
    view_prefixes = ("Core view:", "核心观点：")
    conclusion_prefixes = ("Trading implication:", "Trading conclusion:", "交易含义：", "交易结论：")
    drop_prefixes = ("Key data:", "Interactions", "关键数据：", "互动")
    view = conclusion = ""
    for raw in points or []:
        text = str(raw or "").strip()
        plain = re.sub(r"<[^>]+>", "", text).strip()
        if not plain or plain.startswith(drop_prefixes):
            continue
        if plain.startswith(conclusion_prefixes):
            if not conclusion:
                body = re.sub(
                    r"(?:Trading implication|Trading conclusion|交易含义|交易结论)[：:]\s*",
                    "",
                    text,
                    count=1,
                )
                conclusion = conclusion_label + body
        elif not view:
            view = text if plain.startswith(view_prefixes) else view_label + text
    return [item for item in (view, conclusion) if item]


def compact_report_insights(report, lang: str = "zh"):
    if not isinstance(report, dict):
        return report
    result = dict(report)
    result["insights"] = [
        {**item, "points": compact_core_points(item.get("points", []), lang)}
        for item in report.get("insights", [])
    ]
    return result
