"""Five-section KOL report synthesis via rules plus optional LLM."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Iterable

import httpx

from .loader import Tweet

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Viewpoint:
    handle: str
    view: str
    insight: str = ""
    tweet_refs: list[str] = field(default_factory=list)
    published_at: str = ""
    url: str = ""
    engagement: int = 0


@dataclass(slots=True)
class KolBlock:
    handle: str
    tier: int
    tags: list[str]
    views: list[Viewpoint] = field(default_factory=list)
    tweet_count: int = 0
    top_engagement: int = 0


@dataclass(slots=True)
class TopicGroup:
    key: str
    label: str
    views: list[Viewpoint] = field(default_factory=list)
    tweet_count: int = 0


@dataclass(slots=True)
class EnsoStatus:
    headline: str
    views: list[Viewpoint] = field(default_factory=list)
    fallback: bool = True


@dataclass(slots=True)
class SectionDigest:
    key: str
    label: str
    headline: str
    overview: str
    tweet_count: int = 0
    handles_count: int = 0
    kol_blocks: list[KolBlock] = field(default_factory=list)
    topic_groups: list[TopicGroup] = field(default_factory=list)
    enso_status: EnsoStatus | None = None
    fallback: bool = True


@dataclass(frozen=True, slots=True)
class TopicSpec:
    key: str
    label: str
    tags: frozenset[str] = frozenset()
    keywords: tuple[str, ...] = ()


SECTION_LABELS = {
    "macro": "宏观经济",
    "geopolitics": "地缘政治",
    "commodities": "大宗商品",
    "weather": "天气气候",
    "ai_semis": "AI半导体科技",
}
SECTION_ORDER = ["macro", "geopolitics", "commodities", "weather", "ai_semis"]
SECTION_TIE_PRIORITY = ["weather", "commodities", "ai_semis", "geopolitics", "macro"]

SECTION_TAGS = {
    "macro": {
        "macro", "central_banks", "rates_fx", "china_macro", "volatility",
        "equities", "credit", "data", "technical",
    },
    "geopolitics": {
        "geopolitics", "middle_east", "russia", "indo_pacific",
        "national_security", "defense", "sanctions_policy", "china_macro",
    },
    "commodities": {
        "commodities", "oil_energy", "nat_gas_lng", "metals_industrial",
        "precious_metals", "agri_softs", "shipping_freight", "power_carbon",
    },
    "weather": {
        "weather_climate", "enso", "climate_risk", "models", "seasonal",
        "hurricanes", "severe_weather",
    },
    "ai_semis": {
        "ai_semis", "technology", "semiconductors", "software", "ai_research",
        "developer", "engineering",
    },
}

SECTION_KEYWORDS = {
    "macro": (
        "fed", "inflation", "cpi", "rates", "yield", "dollar", "recession",
        "growth", "macro", "央行", "美联储", "通胀", "利率", "收益率", "美元",
    ),
    "geopolitics": (
        "iran", "israel", "gaza", "ukraine", "russia", "taiwan", "china",
        "middle east", "war", "nato", "sanction", "地缘", "中东", "俄乌",
        "乌克兰", "俄罗斯", "中美", "台湾", "制裁",
    ),
    "commodities": (
        "oil", "crude", "brent", "wti", "gas", "lng", "gold", "copper",
        "wheat", "corn", "soy", "commodity", "原油", "天然气", "黄金", "铜",
        "小麦", "玉米", "大宗",
    ),
    "weather": (
        "enso", "el nino", "la nina", "weather", "climate", "hurricane",
        "forecast", "厄尔尼诺", "拉尼娜", "天气", "气候", "飓风",
    ),
    "ai_semis": (
        "ai", "nvidia", "nvda", "amd", "gpu", "semiconductor", "inference",
        "packaging", "hbm", "tsmc", "英伟达", "半导体", "推理", "封装",
    ),
}

GEOPOLITICS_TOPICS = [
    TopicSpec(
        "middle_east",
        "中东",
        frozenset({"middle_east"}),
        (
            "middle east", "iran", "israel", "gaza", "hamas", "hezbollah",
            "hormuz", "red sea", "saudi", "qatar", "syria", "lebanon",
            "中东", "伊朗", "以色列", "加沙", "哈马斯", "霍尔木兹",
            "红海", "沙特", "卡塔尔", "叙利亚", "黎巴嫩",
        ),
    ),
    TopicSpec(
        "russia_ukraine",
        "俄乌",
        frozenset({"russia"}),
        (
            "russia", "ukraine", "moscow", "kyiv", "kiev", "kremlin", "putin",
            "zelensky", "nato", "crimea", "donbas", "俄乌", "俄罗斯",
            "乌克兰", "莫斯科", "基辅", "克里米亚", "北约",
        ),
    ),
    TopicSpec(
        "china_us",
        "中美",
        frozenset({"china_macro", "indo_pacific"}),
        (
            "china", "u.s.", "us-china", "sino", "taiwan", "beijing",
            "washington", "tariff", "export control", "indo-pacific", "中美",
            "中国", "美国", "台湾", "北京", "华盛顿", "关税", "出口管制",
        ),
    ),
    TopicSpec("other_geopolitics", "其他地缘"),
]

COMMODITY_TOPICS = [
    TopicSpec(
        "oil",
        "原油",
        frozenset({"oil_energy"}),
        ("oil", "crude", "brent", "wti", "opec", "shale", "refinery", "原油", "石油", "欧佩克"),
    ),
    TopicSpec(
        "nat_gas",
        "天然气",
        frozenset({"nat_gas_lng"}),
        ("gas", "nat gas", "natural gas", "lng", "henry hub", "ttf", "天然气", "液化天然气"),
    ),
    TopicSpec(
        "metals",
        "金属",
        frozenset({"metals_industrial", "precious_metals"}),
        (
            "gold", "silver", "copper", "aluminum", "aluminium", "lithium",
            "nickel", "metal", "黄金", "白银", "铜", "铝", "锂", "镍", "金属",
        ),
    ),
    TopicSpec(
        "agri",
        "农产品",
        frozenset({"agri_softs"}),
        (
            "corn", "wheat", "soy", "soybean", "grain", "sugar", "coffee",
            "cotton", "crop", "usda", "玉米", "小麦", "大豆", "谷物", "白糖",
            "咖啡", "棉花", "农产品",
        ),
    ),
    TopicSpec("other_commodities", "其他大宗", frozenset({"commodities"})),
]

AI_TOPICS = [
    TopicSpec(
        "nvidia",
        "英伟达",
        frozenset(),
        ("nvidia", "nvda", "blackwell", "cuda", "h100", "h200", "gb200", "gb300", "英伟达", "黄仁勋"),
    ),
    TopicSpec("amd", "AMD", frozenset(), ("amd", "mi300", "mi350", "instinct", "lisa su", "苏姿丰")),
    TopicSpec(
        "inference",
        "推理",
        frozenset({"ai_research", "developer"}),
        ("inference", "inferencing", "serving", "latency", "token", "edge ai", "reasoning", "推理", "时延"),
    ),
    TopicSpec(
        "packaging",
        "封装",
        frozenset({"semiconductors"}),
        ("packaging", "cowos", "hbm", "tsmc", "advanced packaging", "chiplet", "interposer", "封装", "台积电"),
    ),
    TopicSpec("other_ai_semis", "其他 AI / 半导体"),
]

TOPICS_BY_SECTION = {
    "geopolitics": GEOPOLITICS_TOPICS,
    "commodities": COMMODITY_TOPICS,
    "ai_semis": AI_TOPICS,
}

LLM_PROMPT = """你正在为 Codex 自动化日报生成链路提供结构化内容。最终成品会被程序渲染成中文可视化 PDF，面向交易员阅读。

任务：只针对“{label}”板块，从下面推文里提取**带个人判断 / 预测 / 情绪 / 立场**的观点，并输出严格 JSON。

筛选规则：
1. 判断标准：删掉这条如果损失的是“某人的看法”就留；若删掉后只损失“客观事实”就删。
2. 必删：
   - 新闻转发/快讯复述（BREAKING、JUST IN、per FT/CNBC/POLITICO/Reuters/Bloomberg 等）
   - 纯数据搬运（ADP、ISM、EIA库存、分国别进出口、表格数字、没有个人判断的统计）
   - 推广、闲聊、转链接、无实质内容（gm、感谢、点赞式回复、播客宣传等）
3. 只保留“像老师手写纪要一样有棱角”的内容：独特判断、方向偏好、风险提示、时间条件、价位条件、多空分歧、反向变量。
4. 同一位 KOL 只保留 1 条信息量最大的观点。

写作要求：
1. 输出中文，不要照抄英文原文，不要做新闻标题式概括。
2. `view` 是给最终 PDF 的“逐条一句话精炼观点”，要求：
   - 30~140字
   - 必须具体，保留关键数字/百分比/价位/数量/时间条件
   - 像这样写：`秘鲁沿岸 El Niño Costero 快速增强，Niño 1+2逼近+3°C，与1997年同期相似；预计两周内扩展至厄瓜多尔。`
   - 不要写成统一模板，不要出现“这条观点聚焦…”“核心在于…”这种空话
3. `insight` 是单独一句“交易含义 / 不确定性 / 反向变量”，要求：
   - 18~60字
   - 点明为什么值得交易员看
   - 可以写“给 El Niño 交易再加一层不确定性”“若利率不跟随回落，这条多头逻辑会被削弱”
4. `headline` 要像板块总括句，有定性，不要空泛。
5. `overview` 要写成本板块 80~180 字中文总结，强调交易主线、分歧和风险。
6. 不要发明推文里没有的信息。

输出结构：
{{
  "headline": "本板块一句话总括",
  "overview": "本板块中文综述",
  "kol_blocks": [
    {{"handle": "MacroAlf", "views": [
      {{"handle": "MacroAlf", "view": "一句话精炼观点", "insight": "一句交易含义", "tweet_refs": ["tw_..."]}}
    ]}}
  ],
  "topic_groups": [
    {{"key": "固定分组key", "label": "固定分组名", "views": [
      {{"handle": "...", "view": "一句话精炼观点", "insight": "一句交易含义", "tweet_refs": ["tw_..."]}}
    ]}}
  ],
  "enso_status": {{"headline": "厄尔尼诺现状一句话", "views": [
    {{"handle": "...", "view": "一句话精炼观点", "insight": "一句交易含义", "tweet_refs": ["tw_..."]}}
  ]}}
}}

字段约束：
- `handle` 必须写账号，不带 @ 也可以，程序会补。
- `view` 才是最终报告里逐条显示的主句，必须尽量像人工纪要。
- `insight` 是附加的交易含义，不要重复 `view`。
- `tweet_refs` 尽量保留输入里的 ref。

本板块固定分组：
{topic_labels}

待处理推文：
{tweets_block}
"""


def synthesize_all(
    tweets: Iterable[Tweet],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    use_llm: bool = True,
) -> list[SectionDigest]:
    tweet_list = list(tweets)
    sections = build_rule_based_sections(tweet_list)
    if not use_llm:
        return sections

    provider = os.environ.get("KOL_DIGEST_PROVIDER", "").strip().lower()
    use_cli = provider in ("claude_cli", "claude-cli", "cli")

    api_key = api_key or os.environ.get("KOL_DIGEST_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""
    # CLI mode runs the local `claude` binary on the Max subscription — no API key required.
    if not use_cli and not api_key:
        return sections

    base_url = base_url or os.environ.get("KOL_DIGEST_BASE_URL") or "https://api.minimax.chat/v1"
    default_model = "sonnet" if use_cli else "MiniMax-M2.7"
    model = model or os.environ.get("KOL_DIGEST_MODEL") or default_model
    refined: list[SectionDigest] = []
    for section in sections:
        section_tweets = select_section_tweets(section.key, tweet_list)
        if not section_tweets:
            refined.append(section)
            continue
        try:
            if use_cli:
                result = _call_claude_cli(_prompt_for_section(section, section_tweets), model=model)
            else:
                result = _call_llm(
                    _prompt_for_section(section, section_tweets),
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                )
            refined.append(_merge_llm_section(section, result))
        except Exception as exc:
            logger.warning("LLM synthesis failed for %s: %s", section.key, exc)
            refined.append(section)
    return refined


def build_rule_based_sections(tweets: Iterable[Tweet]) -> list[SectionDigest]:
    tweet_list = list(tweets)
    sections: list[SectionDigest] = []
    for key in SECTION_ORDER:
        section_tweets = select_section_tweets(key, tweet_list)
        if key == "macro":
            sections.append(_build_kol_section(key, section_tweets))
        elif key == "weather":
            sections.append(_build_weather_section(section_tweets))
        else:
            sections.append(_build_topic_section(key, section_tweets, TOPICS_BY_SECTION[key]))
    return sections


def select_section_tweets(key: str, tweets: Iterable[Tweet]) -> list[Tweet]:
    selected = [
        t for t in tweets
        if classify_section_tweet(t) == key and _is_signal_tweet(t)
    ]
    return _dedupe_similar_by_handle(_sort_tweets(selected))


def classify_section_tweet(tweet: Tweet) -> str | None:
    """Assign one section, preferring the account's primary research domain."""
    primary = str(tweet.primary_tag or tweet.category or "").lower()
    for key in SECTION_TIE_PRIORITY:
        if primary in SECTION_TAGS[key]:
            return key

    tag_set = {tag.lower() for tag in tweet.tags}
    text = f"{tweet.title} {tweet.body}".lower()
    scores = {}
    for key in SECTION_ORDER:
        tag_hits = len(tag_set.intersection(SECTION_TAGS[key]))
        keyword_hits = sum(1 for keyword in SECTION_KEYWORDS[key] if keyword.lower() in text)
        scores[key] = 3 * tag_hits + keyword_hits
    best = max(scores.values(), default=0)
    if best <= 0:
        return None
    return next(key for key in SECTION_TIE_PRIORITY if scores[key] == best)


def _build_kol_section(key: str, tweets: list[Tweet]) -> SectionDigest:
    label = SECTION_LABELS[key]
    blocks = _build_kol_blocks(tweets)
    return SectionDigest(
        key=key,
        label=label,
        headline=_headline(label, tweets),
        overview=_overview(label, tweets, "按 KOL 汇总，每位 KOL 只保留 1 条核心观点，过滤短时情绪和重复内容。"),
        tweet_count=len(tweets),
        handles_count=len({t.handle for t in tweets}),
        kol_blocks=blocks,
        fallback=True,
    )


def _build_weather_section(tweets: list[Tweet]) -> SectionDigest:
    label = SECTION_LABELS["weather"]
    enso_tweets = [
        t for t in tweets
        if _matches(t, tags={"enso"}, keywords=("enso", "el nino", "la nina", "厄尔尼诺", "拉尼娜"))
    ]
    enso_source = enso_tweets or tweets[:5]
    enso_status = EnsoStatus(
        headline=_enso_headline(enso_source),
        views=_viewpoints_from_tweets(enso_source, per_handle=1, limit=5),
        fallback=True,
    )
    return SectionDigest(
        key="weather",
        label=label,
        headline=_headline(label, tweets),
        overview=_overview(label, tweets, "顶部单独归纳厄尔尼诺现状，下方按 KOL 汇总天气/气候观点，每人只保留 1 条。"),
        tweet_count=len(tweets),
        handles_count=len({t.handle for t in tweets}),
        kol_blocks=_build_kol_blocks(tweets),
        enso_status=enso_status,
        fallback=True,
    )


def _build_topic_section(key: str, tweets: list[Tweet], specs: list[TopicSpec]) -> SectionDigest:
    label = SECTION_LABELS[key]
    groups = _build_topic_groups(tweets, specs)
    return SectionDigest(
        key=key,
        label=label,
        headline=_headline(label, tweets),
        overview=_overview(label, tweets, "观点按固定主题分组，并在每条观点上标明 KOL；每人只保留 1 条以体现观点多样性。"),
        tweet_count=len(tweets),
        handles_count=len({t.handle for t in tweets}),
        topic_groups=groups,
        fallback=True,
    )


def _build_topic_groups(tweets: list[Tweet], specs: list[TopicSpec]) -> list[TopicGroup]:
    assigned: set[str] = set()
    used_handles: set[str] = set()
    groups: list[TopicGroup] = []
    for spec in specs:
        if spec.key.startswith("other_"):
            candidates = [
                t for t in tweets
                if _tweet_key(t) not in assigned and t.handle.lower() not in used_handles
            ]
        else:
            candidates = [
                t for t in tweets
                if (
                    _tweet_key(t) not in assigned
                    and t.handle.lower() not in used_handles
                    and _matches(t, tags=spec.tags, keywords=spec.keywords)
                )
            ]
        candidates = _sort_tweets(candidates)
        for t in candidates:
            assigned.add(_tweet_key(t))
            used_handles.add(t.handle.lower())
        groups.append(
            TopicGroup(
                key=spec.key,
                label=spec.label,
                views=_viewpoints_from_tweets(candidates, per_handle=1, limit=12),
                tweet_count=len(candidates),
            )
        )
    return groups


def _build_kol_blocks(tweets: list[Tweet], max_views_per_handle: int = 1) -> list[KolBlock]:
    by_handle: dict[str, list[Tweet]] = {}
    for t in tweets:
        by_handle.setdefault(t.handle, []).append(t)
    blocks: list[KolBlock] = []
    for handle, items in by_handle.items():
        sorted_items = _sort_tweets(items)
        top = sorted_items[0]
        blocks.append(
            KolBlock(
                handle=handle,
                tier=top.tier,
                tags=top.tags,
                views=[_viewpoint_from_tweet(t) for t in sorted_items[:max_views_per_handle]],
                tweet_count=len(items),
                top_engagement=top.engagement,
            )
        )
    blocks.sort(key=lambda b: (b.tier or 99, -b.top_engagement, b.handle.lower()))
    return blocks


def _viewpoints_from_tweets(tweets: list[Tweet], *, per_handle: int, limit: int) -> list[Viewpoint]:
    counts: dict[str, int] = {}
    views: list[Viewpoint] = []
    for t in _sort_tweets(tweets):
        if counts.get(t.handle, 0) >= per_handle:
            continue
        views.append(_viewpoint_from_tweet(t))
        counts[t.handle] = counts.get(t.handle, 0) + 1
        if len(views) >= limit:
            break
    return views


def _viewpoint_from_tweet(t: Tweet) -> Viewpoint:
    return Viewpoint(
        handle=t.handle,
        view=_trim(t.body or t.title, 280),
        tweet_refs=[t.source_id] if t.source_id else [],
        published_at=t.published_at,
        url=t.url,
        engagement=t.engagement,
    )


def _headline(label: str, tweets: list[Tweet]) -> str:
    if not tweets:
        return f"{label}：暂无入库推文"
    handles = len({t.handle for t in tweets})
    return f"{label}：{handles} 位 KOL / {len(tweets)} 条推文"


def _overview(label: str, tweets: list[Tweet], suffix: str) -> str:
    if not tweets:
        return f"过去窗口内，{label}板块暂无 mixclean KOL 入库推文。"
    handles_count = len({t.handle.lower() for t in tweets})
    top_handles = []
    seen = set()
    for t in _sort_tweets(tweets):
        if t.handle.lower() not in seen:
            top_handles.append(f"@{t.handle}")
            seen.add(t.handle.lower())
        if len(top_handles) >= 5:
            break
    return f"过去窗口内，{label}板块覆盖 {handles_count} 位 KOL，主要发声：" + "、".join(top_handles) + f"。{suffix}"


def _enso_headline(tweets: list[Tweet]) -> str:
    if not tweets:
        return "暂无足够 KOL 推文判断厄尔尼诺现状。"
    return "基于 weather/enso KOL 推文整理，厄尔尼诺现状以近期模型和海温信号为准。"


def _sort_tweets(tweets: Iterable[Tweet]) -> list[Tweet]:
    return sorted(tweets, key=lambda t: (t.important, t.engagement, t.published_at), reverse=True)


def _tweet_key(t: Tweet) -> str:
    return t.source_id or f"{t.handle}:{t.published_at}:{hash(t.body)}"


def _matches(t: Tweet, *, tags: Iterable[str] = (), keywords: Iterable[str] = ()) -> bool:
    tag_set = {tag.lower() for tag in t.tags}
    wanted_tags = {tag.lower() for tag in tags}
    if wanted_tags and tag_set.intersection(wanted_tags):
        return True
    text = f"{t.title} {t.body}".lower()
    return any(kw.lower() in text for kw in keywords)


LOW_SIGNAL_PATTERNS = (
    "apply through", "we're hiring", "we are hiring", "hiring", "job opening",
    "newsletter", "subscribe", "podcast", "episode", "watch here", "listen here",
    "new video is up", "good morning", "congrats", "congratulations", "thank you",
    "thanks for having me", "my time at", "slide deck", "snapshot from",
)

NEWS_RELAY_PATTERNS = (
    "breaking:", "just in:", "per ft", "per cnbc", "per politico", "per wsj",
    "according to", "via reuters", "via bloomberg", "headline:", "statement from",
)
DATA_DUMP_PATTERNS = (
    "eia crude", "api crude", "ism prices", "adp employment", "imports from",
    "exports to", "inventory was", "inventory were", "table:", "chart:",
)
OPINION_MARKERS = (
    "i think", "i believe", "i expect", "i suspect", "my base case", "my view",
    "i'm bullish", "i am bullish", "i'm bearish", "i am bearish", "feels like",
    "looks like", "should", "could", "likely", "unlikely", "risk is", "setup is",
    "priced for", "market is", "positioning", "consensus", "underpriced", "overpriced",
    "remain the key", "remain key", "still matter", "is supported", "is expanding",
    "becoming the", "remain the constraint", "risk is rising", "driving", "central to",
    "我认为", "我觉得", "预期", "判断", "看多", "看空", "偏多", "偏空", "风险在于", "交易上",
)


def _is_signal_tweet(t: Tweet) -> bool:
    text = re.sub(r"\s+", " ", f"{t.title} {t.body}".strip()).lower()
    if len(text) < 45 and not t.important:
        return False
    if any(pattern in text for pattern in LOW_SIGNAL_PATTERNS):
        return False
    if any(pattern in text for pattern in NEWS_RELAY_PATTERNS):
        return False
    if any(pattern in text for pattern in DATA_DUMP_PATTERNS) and not any(marker in text for marker in OPINION_MARKERS):
        return False
    if text.count("http") >= 2 and len(text) < 140:
        return False
    # High-engagement domain posts often carry a useful market view without
    # using the fixed stance vocabulary below. Keep them after hard-noise checks.
    if t.important and len(text) >= 45:
        return True
    if re.fullmatch(r"[@\w\s,.!?:;%$+-]+", text) and not any(marker in text for marker in OPINION_MARKERS):
        return False
    if not any(marker in text for marker in OPINION_MARKERS):
        future_or_stance = sum(1 for token in (" will ", " would ", " above ", " below ", " bullish", " bearish", " risk ", " squeeze ", " slowdown ") if token in f" {text} ")
        if future_or_stance == 0:
            return False
    return True


def _dedupe_similar_by_handle(tweets: list[Tweet]) -> list[Tweet]:
    seen: dict[str, set[str]] = {}
    result: list[Tweet] = []
    for tweet in tweets:
        handle_key = tweet.handle.lower()
        signature = _similarity_signature(tweet.body or tweet.title)
        signatures = seen.setdefault(handle_key, set())
        if signature in signatures:
            continue
        signatures.add(signature)
        result.append(tweet)
    return result


def _similarity_signature(text: str) -> str:
    words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "are", "was",
        "you", "your", "have", "has", "but", "not", "will", "they", "their",
    }
    kept = [w for w in words if len(w) > 2 and w not in stop]
    return " ".join(kept[:18])


def _auto_insight(view: str) -> str:
    """Build a short Chinese investment insight when the LLM omits one."""
    if not view:
        return ""
    text = view.strip()
    if len(text) < 30:
        return ""
    for prefix in ("BREAKING: ", "JUST IN: ", "NEW: ", "UPDATE: ", "Thread: ", "1/ ", "2/ ", "3/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    lower = text.lower()
    if any(word in lower for word in ("fed", "inflation", "yield", "rate", "cpi", "dollar")):
        return "洞见：这条观点提示宏观定价的边际变量正在变化，重点关注利率、通胀和美元路径对资产的传导。"
    if any(word in lower for word in ("oil", "crude", "gas", "lng", "gold", "copper", "commodity")):
        return "洞见：这条观点的核心在于供需、库存或风险溢价变化，需关注其对相关商品价格方向的影响。"
    if any(word in lower for word in ("ai", "nvidia", "semiconductor", "gpu", "hbm", "tsmc")):
        return "洞见：这条观点反映 AI/半导体产业链的预期变化，重点看需求、算力供给和受益环节。"
    if any(word in lower for word in ("war", "iran", "israel", "russia", "ukraine", "china", "taiwan")):
        return "洞见：这条观点强调地缘风险的边际变化，需关注其对能源、避险资产和风险偏好的外溢影响。"
    return "洞见：这条观点保留的价值不在情绪本身，而在其提示了后续需要跟踪的市场变量或事件线索。"


def _trim(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "..."


def _format_tweets_for_prompt(tweets: list[Tweet], max_count: int = 35) -> str:
    rows = []
    for i, t in enumerate(tweets[:max_count], 1):
        body = _trim(t.body, 420)
        rows.append(
            f"[{i:02d}] ref={t.source_id or i} @{t.handle} tier={t.tier} "
            f"tags={','.join(t.tags)} engagement={t.engagement} time={t.published_at}\n"
            f"{body}"
        )
    return "\n".join(rows)


def _prompt_for_section(section: SectionDigest, tweets: list[Tweet]) -> str:
    if section.key == "macro":
        topic_labels = "宏观经济板块不按主题分组，只输出 kol_blocks；每个 KOL 只输出 1 条 view。"
    elif section.key == "weather":
        topic_labels = "天气气候板块必须输出 enso_status，并输出 kol_blocks；每个 KOL 只输出 1 条 view。"
    else:
        topic_labels = "\n".join(f"- {g.key}: {g.label}" for g in section.topic_groups)
    return LLM_PROMPT.format(
        label=section.label,
        topic_labels=topic_labels,
        tweets_block=_format_tweets_for_prompt(tweets),
    )


SYSTEM_PROMPT = (
    "你是 Codex 工作流中的中文交易纪要生成器。你的输出会被程序直接渲染成 PDF，"
    "所以只输出严格 JSON，并优先保留具体判断、数字、时间条件和交易含义。"
)


def _is_anthropic(base_url: str, model: str) -> bool:
    return "anthropic" in base_url.lower() or model.lower().startswith("claude")


def _call_llm(prompt: str, *, base_url: str, api_key: str, model: str, timeout: float = 120.0) -> dict:
    if _is_anthropic(base_url, model):
        return _call_anthropic(prompt, base_url=base_url, api_key=api_key, model=model, timeout=timeout)
    return _call_openai_compatible(prompt, base_url=base_url, api_key=api_key, model=model, timeout=timeout)


def _call_openai_compatible(prompt: str, *, base_url: str, api_key: str, model: str, timeout: float) -> dict:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return _loads_json(content)


def _call_claude_cli(prompt: str, *, model: str, timeout: float = 240.0) -> dict:
    # Drive the local Claude Code binary (Max subscription) instead of a paid API.
    full = SYSTEM_PROMPT + "\n\n" + prompt
    cmd = ["claude", "-p", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    # Use a long-lived subscription token (`claude setup-token`) and avoid any
    # ANTHROPIC_BASE_URL / API key that would misroute the subprocess to a paid API.
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")}
    proc = subprocess.run(cmd, input=full, capture_output=True, text=True, timeout=timeout, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"claude cli failed ({proc.returncode}): {proc.stderr.strip()[:500]}")
    out = proc.stdout.strip()
    content = out
    try:
        envelope = json.loads(out)
        if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
            content = envelope["result"]
    except json.JSONDecodeError:
        pass
    return _loads_json(content)


def _call_anthropic(prompt: str, *, base_url: str, api_key: str, model: str, timeout: float) -> dict:
    # Anthropic native Messages API (different shape + auth from OpenAI).
    root = base_url.rstrip("/")
    if not root.endswith("/v1"):
        root = "https://api.anthropic.com/v1"
    url = root + "/messages"
    payload = {
        "model": model,
        "max_tokens": 8000,
        "temperature": 0.2,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    content = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    )
    return _loads_json(content)


def _loads_json(content: str) -> dict:
    clean = content.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    return json.loads(clean)


def _merge_llm_section(section: SectionDigest, result: dict) -> SectionDigest:
    section.headline = str(result.get("headline") or section.headline).strip()
    section.overview = str(result.get("overview") or section.overview).strip()
    section.fallback = False

    if section.kol_blocks:
        llm_blocks = _sanitize_kol_blocks(result.get("kol_blocks"), section.kol_blocks)
        if llm_blocks:
            section.kol_blocks = llm_blocks

    if section.topic_groups:
        llm_groups = _sanitize_topic_groups(result.get("topic_groups"), section.topic_groups)
        if llm_groups:
            section.topic_groups = llm_groups

    if section.enso_status is not None and isinstance(result.get("enso_status"), dict):
        enso = result["enso_status"]
        section.enso_status.headline = str(enso.get("headline") or section.enso_status.headline).strip()
        views = _sanitize_views(enso.get("views"))
        if views:
            section.enso_status.views = views
        section.enso_status.fallback = False
    return section


def _sanitize_kol_blocks(raw: object, fallback: list[KolBlock]) -> list[KolBlock]:
    if not isinstance(raw, list):
        return []
    fallback_map = {b.handle.lower(): b for b in fallback}
    refined: dict[str, KolBlock] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        handle = str(item.get("handle") or "").lstrip("@").strip()
        if not handle:
            continue
        base = fallback_map.get(handle.lower())
        views = _sanitize_views(item.get("views"))[:1]
        if not views:
            continue
        block = KolBlock(
            handle=base.handle if base else handle,
            tier=base.tier if base else 0,
            tags=base.tags if base else [],
            views=views,
            tweet_count=base.tweet_count if base else len(views),
            top_engagement=base.top_engagement if base else 0,
        )
        refined[block.handle.lower()] = block
    if not refined:
        return []
    blocks = [refined.get(b.handle.lower(), b) for b in fallback]
    extra = [b for key, b in refined.items() if key not in fallback_map]
    return blocks + extra


def _sanitize_topic_groups(raw: object, fallback: list[TopicGroup]) -> list[TopicGroup]:
    fallback_by_key = {g.key: g for g in fallback}
    raw_by_key = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("key"):
                raw_by_key[str(item["key"])] = item
    groups: list[TopicGroup] = []
    used_handles: set[str] = set()
    for base in fallback:
        item = raw_by_key.get(base.key, {})
        views = _sanitize_views(item.get("views")) if isinstance(item, dict) else []
        if not views:
            views = base.views
        unique_views = []
        for view in views:
            handle_key = view.handle.lower()
            if handle_key in used_handles:
                continue
            used_handles.add(handle_key)
            unique_views.append(view)
        groups.append(
            TopicGroup(
                key=base.key,
                label=base.label,
                views=unique_views,
                tweet_count=base.tweet_count,
            )
        )
    return groups


def _sanitize_views(raw: object) -> list[Viewpoint]:
    if not isinstance(raw, list):
        return []
    views: list[Viewpoint] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        handle = str(item.get("handle") or "").lstrip("@").strip()
        view = str(item.get("view") or item.get("summary") or "").strip()
        raw_insight = item.get("insight")
        # raw_insight can be None (key missing), "" (explicit empty), or a string
        if raw_insight is None or str(raw_insight).strip() in ("", "None"):
            insight = _auto_insight(view)
        else:
            insight = str(raw_insight).strip()
        refs_raw = item.get("tweet_refs") or []
        refs = [str(r) for r in refs_raw] if isinstance(refs_raw, list) else [str(refs_raw)]
        if handle and view:
            views.append(Viewpoint(handle=handle, view=view, insight=insight, tweet_refs=refs))
    return views
