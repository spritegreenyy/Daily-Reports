"""HTML / PDF rendering for the visual KOL trading digest."""

from __future__ import annotations

import html
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .digest import (
    SECTION_LABELS,
    SECTION_ORDER,
    SectionDigest,
    Viewpoint,
    _tweet_key,
    select_section_tweets,
)
from .loader import CategoryBundle, Tweet

logger = logging.getLogger(__name__)

PAGE_PNG_SUFFIX = "_page1.png"

SECTION_LETTERS = ["B", "C", "D", "E", "F", "G", "H"]

SECTION_LABEL_CN = {
    "macro": "宏观经济",
    "geopolitics": "地缘政治",
    "commodities": "大宗商品",
    "weather": "天气气候",
    "ai_semis": "AI / 半导体",
}

STATUS_STYLE = {
    "偏多关注": ("bullish", "#2e7d6b"),
    "分化": ("mixed", "#5a6b85"),
    "谨慎": ("cautious", "#b5751d"),
    "紧张升级": ("stress", "#a23b2e"),
}

HANDLE_IDENTITIES = {
    "BenNollWeather": "ENSO 专家",
    "webberweather": "ENSO / 热带",
    "RARohde": "Berkeley Earth",
    "commoditywx": "商品 / 农业 / 能源天气",
    "afreedma": "气候政策",
    "climateguyw": "气候研究",
    "BenBajarin": "科技产业分析",
    "unusual_whales": "市场流",
    "danielnewmanUV": "科技 / 企业战略",
    "firstadopter": "科技观察",
    "gdb": "OpenAI 总裁",
    "SemiAnalysis_": "半导体研究",
    "JavierBlas": "能源记者 (BBG)",
    "ericnuttall": "能源基金 (Ninepoint)",
    "hkuppy": "对冲基金",
    "anaslahajji": "能源研究",
    "Ole_S_Hansen": "盛宝银行 商品策略",
    "PickeringEnergy": "能源研究",
    "HFI_Research": "能源研究",
    "TaviCosta": "宏观策略 (Crescat)",
    "Convertbond": "债券 / 信用",
    "RaoulGMI": "全球宏观",
    "LynAldenContact": "宏观 (Lyn Alden)",
    "WarrenPies": "宏观策略",
    "LukeGromen": "全球宏观",
    "elerianm": "宏观经济学家",
    "BobEUnlimited": "宏观研究",
    "michaelkantro": "宏观策略 (Piper Sandler)",
    "pbockvar": "宏观策略",
    "ianbremmer": "地缘政治 (Eurasia Group)",
    "BarakRavid": "中东记者 (Axios)",
    "tparsi": "伊朗问题专家",
    "vali_nasr": "中东学者",
    "yarotrof": "俄乌战地记者",
    "PhillipsPOBrien": "战略研究",
    "michaeldweiss": "俄乌问题专家",
    "BonnieGlaser": "中美 / 台海",
    "GoddessofGrain": "农业 / 粮食",
    "Weather_West": "美西天气",
    "McClellanOsc": "技术分析",
    "cristianoamon": "高通 CEO",
}

TOPIC_LIBRARY = {
    "原油 / 馏分油": ("oil", "brent", "wti", "opec", "crude", "diesel", "馏分油", "原油", "布伦特", "油价", "石油", "能源股"),
    "贵金属": ("gold", "silver", "黄金", "白银"),
    "美联储 / 利率": ("fed", "rates", "yield", "cpi", "pce", "inflation", "treasury", "美联储", "利率", "收益率", "通胀"),
    "AI 算力 / GPU": ("nvidia", "nvda", "gpu", "blackwell", "hbm", "英伟达", "tsmc", "台积电"),
    "AI 软件 / 推理": ("inference", "推理", "codex", "claude", "agent", "llm", "应用层"),
    "美股 / 资金流": ("nasdaq", "spx", "sp500", "纳斯达克", "标普", "soxx", "broadcom", "estimate"),
    "天然气 / LNG": ("lng", "natural gas", "ttf", "henry hub", "天然气"),
    "工业金属": ("copper", "aluminum", "lithium", "nickel", "铜", "铝", "锂", "镍"),
    "比特币 / 加密": ("bitcoin", "btc", "crypto", "比特币"),
    "中东 / 伊朗": ("iran", "israel", "middle east", "hormuz", "gaza", "hezbollah", "伊朗", "以色列", "霍尔木兹", "中东"),
    "俄乌": ("russia", "ukraine", "kyiv", "moscow", "俄乌", "俄罗斯", "乌克兰"),
    "中国 / 中美": ("china", "tariff", "taiwan", "export control", "中美", "中国", "台湾", "关税"),
    "天气 / 厄尔尼诺": ("enso", "la nina", "el nino", "hurricane", "climate", "weather", "拉尼娜", "厄尔尼诺", "飓风"),
}

BULLISH_WORDS = (
    "bullish", "constructive", "upside", " buy ", "accumulate", "squeeze",
    "reaccelerate", "tight", "supportive", "oversold", "rally",
    "看多", "做多", "看涨", "上行", "偏多", "利多", "买点", "走强", "突破", "支撑",
    "底部", "飙升", "暴涨", "上涨", "反弹", "回升", "受益", "利好", "新高",
    "引爆", "短缺", "断供", "枯竭", "供应紧", "紧缩", "买入机会", "做多窗口", "补涨",
    "看好", "唯一出路",
)
BEARISH_WORDS = (
    "bearish", "downside", " short ", "sell ", "fade", "recession", "slowdown",
    "negative", "risk-off", "overvalued", "crowded",
    "看空", "做空", "看跌", "下行", "利空", "回落", "警惕", "回调", "走弱", "跌破",
    "崩盘", "抛售", "恐慌", "承压", "下跌", "暴跌", "新低", "高估", "证伪", "失效",
    "踩踏", "投降", "外流", "脱节", "证伪", "估值修正", "破灭",
)

WARNING_MARKERS = (
    "war", "missile", "sanction", "blockade", "shutdown", "shortage",
    "战争", "导弹", "封锁", "制裁", "升级", "停运", "短缺", "断供", "枯竭", "停摆", "动荡", "重启",
)
CONDITION_MARKERS = (
    "若", "一旦", "上破", "跌破", "触发", "unless", " if ", " above ", " below ", "突破",
)
NON_CONSENSUS_MARKERS = (
    "反直觉", "非共识", "被忽视", "定价错误", "underappreciated", "mispriced", "underpriced",
    "consensus", "non-consensus", "priced in", "矛盾",
)
SENTIMENT_SHIFT_MARKERS = (
    "情绪", "悲观", "乐观", "超买", "超卖", "sentiment", "crowded",
    "oversold", "overbought", "狂热", "极值", "投降",
)

NUMBER_RE = re.compile(
    r"(\$?\d+(?:\.\d+)?(?:k|m|b)?%?|\b\d+(?:\.\d+)?\s?(?:bp|bps|mb/d|m b/d|mm|mn|bn|k|x)\b)",
    re.IGNORECASE,
)
CHINESE_RE = re.compile(r"[一-鿿]")


@dataclass(slots=True)
class TopicHeat:
    title: str
    count: int


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def render_html(
    sections: list[SectionDigest],
    bundles: list[CategoryBundle],
    *,
    report_date: str,
    window_hours: int,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    tweets = _collect_filtered_tweets(sections, bundles)
    section_tweets = {section.key: select_section_tweets(section.key, tweets) for section in sections}
    handle_eng = _build_handle_engagement(bundles)
    dashboard = _build_dashboard(sections, section_tweets, handle_eng)
    detail_html = "\n".join(
        _render_detail_section(section, SECTION_LETTERS[i] if i < len(SECTION_LETTERS) else "X")
        for i, section in enumerate(sections)
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>KOL总结_可视化版_{html.escape(report_date.replace('-', ''))}</title>
  <style>{_css()}</style>
</head>
<body>
  <main class="report">
    {_render_masthead(report_date, generated_at, window_hours, len(tweets), dashboard["topics"])}
    {_render_dashboard(dashboard)}
    {detail_html}
    <footer class="footnote">免责声明：本报告仅基于公开社交媒体观点做结构化整理与研究展示，不构成投资建议。</footer>
  </main>
</body>
</html>"""


def build_section_tweets(tweets: list[Tweet]) -> list[tuple[str, str, list[Tweet]]]:
    """Rule-filtered tweets per fixed section, each tweet assigned to one section only."""
    assigned: set[str] = set()
    result: list[tuple[str, str, list[Tweet]]] = []
    for key in SECTION_ORDER:
        selected = []
        for t in select_section_tweets(key, tweets):
            tk = _tweet_key(t)
            if tk in assigned:
                continue
            assigned.add(tk)
            selected.append(t)
        result.append((key, SECTION_LABELS[key], selected))
    return result


def render_tweets_markdown(tweets: list[Tweet], *, report_date: str, window_hours: int) -> str:
    sections = build_section_tweets(tweets)
    total = sum(len(sel) for _, _, sel in sections)
    handles = len({t.handle for _, _, sel in sections for t in sel})
    lines = [
        f"# KOL 推文摘要 · {report_date}",
        "",
        f"> 过去 {window_hours}h（截至北京时间 {report_date} 17:00）｜共 {handles} 位 KOL / "
        f"{total} 条信号推文。已按规则过滤掉新闻转发、纯数据搬运、招聘/推广等噪音，并按板块归类，每条推文只归入一个板块。",
        "",
    ]
    for _key, label, sel in sections:
        sec_handles = len({t.handle for t in sel})
        lines.append(f"## {label}（{len(sel)} 条 / {sec_handles} 位 KOL）")
        lines.append("")
        if not sel:
            lines.append("_本板块过去窗口内无信号推文。_")
            lines.append("")
            continue
        for t in sel:
            when = (t.published_at or "")[:16].replace("T", " ")
            tier = f"tier{t.tier}" if t.tier else "tier-"
            lines.append(f"### @{t.handle} · {tier} · 👍{t.engagement} · {when}")
            body = re.sub(r"\s*\n\s*", " ", (t.body or t.title or "").strip())
            lines.append(body)
            if t.url:
                lines.append(f"🔗 {t.url}")
            lines.append("")
    return "\n".join(lines)


def write_html(output_dir: str | Path, html_str: str, report_date: str) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"kol_{report_date.replace('-', '')}.html"
    path.write_text(html_str, encoding="utf-8")
    return path


def export_pdf(html_path: str | Path, pdf_path: str | Path) -> None:
    html_file = Path(html_path).resolve()
    pdf_file = Path(pdf_path).resolve()
    # 优先用浏览器内核（Chrome/Chromium）渲染：对 grid/flex 支持完整、与浏览器所见一致、
    # 不会出现右侧截断或空白页。WeasyPrint 仅作为没有浏览器时的兜底。
    if _export_with_system_chrome(html_file, pdf_file):
        _render_first_page_png(pdf_file)
        return
    if _export_with_weasyprint(html_file, pdf_file):
        _render_first_page_png(pdf_file)
        return
    raise RuntimeError("浏览器与 WeasyPrint PDF 导出均不可用，无法生成 PDF。")


def _export_with_weasyprint(html_file: Path, pdf_file: Path) -> bool:
    try:
        from weasyprint import HTML
    except Exception as exc:
        logger.warning("WeasyPrint unavailable: %s", exc)
        return False
    try:
        HTML(filename=str(html_file)).write_pdf(str(pdf_file))
        return pdf_file.exists()
    except Exception as exc:
        logger.warning("WeasyPrint export failed: %s", exc)
        return False


def _render_first_page_png(pdf_file: Path) -> Path | None:
    png_path = pdf_file.with_name(pdf_file.stem + PAGE_PNG_SUFFIX)
    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(str(pdf_file), first_page=1, last_page=1, fmt="png")
        if not pages:
            logger.warning("Self-check skipped: no pages rendered from %s", pdf_file)
            return None
        pages[0].save(png_path, "PNG")
        logger.info("wrote %s", png_path)
        return png_path
    except Exception as exc:
        logger.warning("PDF self-check PNG render skipped: %s", exc)
        return None


def _export_with_system_chrome(html_file: Path, pdf_file: Path) -> bool:
    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    ]
    browser = next((p for p in candidates if p.exists()), None)
    if browser is None:
        return False
    with tempfile.TemporaryDirectory(prefix="kol_digest_pdf_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        safe_html = tmp_path / "report.html"
        safe_pdf = tmp_path / "report.pdf"
        user_data_dir = tmp_path / "chrome-profile"
        shutil.copyfile(html_file, safe_html)
        cmd = [
            str(browser),
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",      # 去掉浏览器自带的日期/网址/页码页眉
            "--print-to-pdf-no-header",    # 旧版浏览器的同义开关
            f"--user-data-dir={user_data_dir}",
            f"--print-to-pdf={safe_pdf}",
            safe_html.as_uri(),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not safe_pdf.exists():
            return False
        shutil.copyfile(safe_pdf, pdf_file)
    return pdf_file.exists()


# ---------------------------------------------------------------------------
# Data prep
# ---------------------------------------------------------------------------

def _collect_filtered_tweets(sections: list[SectionDigest], bundles: list[CategoryBundle]) -> list[Tweet]:
    all_tweets = [tweet for bundle in bundles for tweet in bundle.tweets]
    keep_keys = {
        key
        for section in sections
        for key in (_tweet_signature(tweet) for tweet in select_section_tweets(section.key, all_tweets))
    }
    deduped = []
    seen = set()
    for tweet in all_tweets:
        sig = _tweet_signature(tweet)
        if sig in keep_keys and sig not in seen:
            deduped.append(tweet)
            seen.add(sig)
    return sorted(deduped, key=lambda item: (item.engagement, item.published_at), reverse=True)


def _tweet_signature(tweet: Tweet) -> str:
    return tweet.source_id or f"{tweet.handle}:{tweet.published_at}:{tweet.body[:80]}"


def _build_handle_engagement(bundles: list[CategoryBundle]) -> dict[str, int]:
    by_handle: dict[str, int] = {}
    for bundle in bundles:
        for tweet in bundle.tweets:
            key = tweet.handle.lower()
            by_handle[key] = max(by_handle.get(key, 0), tweet.engagement)
    return by_handle


@dataclass(slots=True)
class _ViewItem:
    view: Viewpoint
    tier: int
    group_label: str
    section_key: str
    engagement: int


def _iter_views(sections: list[SectionDigest], handle_eng: dict[str, int]) -> list[_ViewItem]:
    items: list[_ViewItem] = []
    for section in sections:
        for block in section.kol_blocks:
            for v in block.views:
                if not _is_real_view(v):
                    continue
                items.append(_ViewItem(v, block.tier, "", section.key, handle_eng.get(v.handle.lower(), 0)))
        for group in section.topic_groups:
            for v in group.views:
                if not _is_real_view(v):
                    continue
                items.append(_ViewItem(v, 0, group.label, section.key, handle_eng.get(v.handle.lower(), 0)))
        if section.enso_status:
            for v in section.enso_status.views:
                if not _is_real_view(v):
                    continue
                items.append(_ViewItem(v, 0, "厄尔尼诺现状", section.key, handle_eng.get(v.handle.lower(), 0)))
    return items


def _is_real_view(v: Viewpoint) -> bool:
    text = (v.view or "").strip()
    if len(text) < 25:
        return False
    if not CHINESE_RE.search(text):
        return False
    return True


def _build_dashboard(
    sections: list[SectionDigest],
    section_tweets: dict[str, list[Tweet]],
    handle_eng: dict[str, int],
) -> dict:
    all_tweets = [tweet for tweets in section_tweets.values() for tweet in tweets]
    views = _iter_views(sections, handle_eng)
    topic_heat = _build_topic_heat(views)
    statuses = [_build_status(section, section_tweets.get(section.key, []), views) for section in sections]
    divergence = _build_divergence_card(views)
    unique_views = _build_unique_views(views)
    core_insights = _build_core_insights(views, divergence, unique_views)
    return {
        "core_insights": core_insights,
        "topics": topic_heat,
        "statuses": statuses,
        "divergence": divergence,
        "unique_views": unique_views,
    }


def _build_core_insights(
    views: list[_ViewItem],
    divergence: dict,
    unique_views: list[dict],
) -> list[dict]:
    """Build 5 dashboard cards from the highest-quality LLM views."""

    scored = sorted(
        ((v, _quality_score(v)) for v in views),
        key=lambda x: -x[1],
    )
    pool = [(v, s) for v, s in scored if s > 0]

    selected: list[dict] = []
    used_handles: set[str] = set()
    used_labels: set[str] = set()

    def add(view_item: _ViewItem, label: str) -> None:
        if view_item.view.handle.lower() in used_handles:
            return
        used_handles.add(view_item.view.handle.lower())
        used_labels.add(label)
        topic = _topic_for_text(view_item.view.view, view_item.section_key, view_item.group_label)
        selected.append({
            "title": f"{label} · {topic}",
            "bullets": _build_insight_bullets(view_item),
        })

    # 1. 最高热度 — top engagement view that has Chinese content
    eng_sorted = sorted(views, key=lambda v: (v.engagement, _quality_score(v)), reverse=True)
    for v in eng_sorted:
        if v.view.handle.lower() in used_handles:
            continue
        add(v, "最高热度")
        if "最高热度" in used_labels:
            break

    # 2. 最大分歧 — bull side from divergence card
    if divergence.get("topic") and divergence.get("bull_view"):
        v = divergence["bull_view"]
        if v.view.handle.lower() not in used_handles:
            add(v, "最大分歧")

    # 3. 高度警惕 — view with warning markers (war/sanction/shortage)
    for v, _ in pool:
        if v.view.handle.lower() in used_handles:
            continue
        text = (v.view.view + " " + (v.view.insight or "")).lower()
        zh = v.view.view + " " + (v.view.insight or "")
        if any(m in text for m in WARNING_MARKERS) or any(m in zh for m in WARNING_MARKERS):
            add(v, "高度警惕")
            break

    # 4. 反向变量 — conditional / non-consensus view
    for v, _ in pool:
        if v.view.handle.lower() in used_handles:
            continue
        text = v.view.view + " " + (v.view.insight or "")
        if any(m in text for m in CONDITION_MARKERS) or any(m in text for m in NON_CONSENSUS_MARKERS):
            add(v, "反向变量")
            break

    # 5. 情绪偏移 — sentiment/positioning view
    for v, _ in pool:
        if v.view.handle.lower() in used_handles:
            continue
        text = v.view.view + " " + (v.view.insight or "")
        if any(m in text for m in SENTIMENT_SHIFT_MARKERS):
            add(v, "情绪偏移")
            break

    # Fill any remaining slots from the top of the quality pool with neutral label.
    fallback_labels = ["独到观点", "高启发观点", "结构变化", "需跟踪", "需观察"]
    for v, _ in pool:
        if len(selected) >= 5:
            break
        if v.view.handle.lower() in used_handles:
            continue
        label = next((lbl for lbl in fallback_labels if lbl not in used_labels), "高启发观点")
        add(v, label)

    return selected[:5]


def _build_insight_bullets(item: _ViewItem) -> list[str]:
    v = item.view
    bullets: list[str] = []
    bullets.append(f"@{v.handle}{_identity_suffix(v.handle)}：{_clean_view(v.view)}")
    insight = _clean_insight(v.insight)
    if insight:
        bullets.append(f"交易含义：{insight}")
    nums = _extract_numbers(v.view + " " + (v.insight or ""))
    if nums:
        bullets.append("关键数据：" + "、".join(nums[:4]))
    if item.engagement >= 50:
        bullets.append(f"互动 {item.engagement}+ · 来自{_section_label_cn(item.section_key)}板块")
    return bullets


def _quality_score(item: _ViewItem) -> int:
    score = 0
    text = item.view.view or ""
    if not text or len(text) < 30:
        return 0
    if not CHINESE_RE.search(text):
        return 0
    if item.view.insight and CHINESE_RE.search(item.view.insight) and len(item.view.insight) > 12:
        score += 3
    if NUMBER_RE.search(text):
        score += 2
    blob = (text + " " + (item.view.insight or "")).lower()
    if any(m.lower() in blob for m in NON_CONSENSUS_MARKERS):
        score += 2
    if any(m in text for m in CONDITION_MARKERS):
        score += 1
    if any(w in blob for w in BULLISH_WORDS) or any(w in blob for w in BEARISH_WORDS):
        score += 1
    if item.tier == 1:
        score += 2
    elif item.tier == 2:
        score += 1
    score += min(2, item.engagement // 200)
    if 60 <= len(text) <= 220:
        score += 1
    return score


def _build_topic_heat(views: list[_ViewItem]) -> list[TopicHeat]:
    counts: dict[str, int] = {key: 0 for key in TOPIC_LIBRARY}
    seen_handles: dict[str, set[str]] = {key: set() for key in TOPIC_LIBRARY}
    for item in views:
        text_lower = (item.view.view + " " + (item.view.insight or "")).lower()
        text_zh = item.view.view + " " + (item.view.insight or "")
        handle_key = item.view.handle.lower()
        for label, keywords in TOPIC_LIBRARY.items():
            if any(k.lower() in text_lower or k in text_zh for k in keywords):
                counts[label] += 1
                seen_handles[label].add(handle_key)
    topics = []
    for label, count in counts.items():
        if count == 0:
            continue
        # weight slightly toward unique-handle coverage
        weighted = count + len(seen_handles[label]) // 2
        topics.append(TopicHeat(title=label, count=weighted))
    topics.sort(key=lambda item: item.count, reverse=True)
    return topics[:5]


def _build_status(section: SectionDigest, tweets: list[Tweet], views: list[_ViewItem]) -> dict:
    status = _infer_section_status(section, views)
    note = f"{len(tweets)} 条原始观点 / {len({t.handle for t in tweets})} 位 KOL"
    return {"label": section.label, "status": status, "note": note}


def _infer_section_status(section: SectionDigest, views: list[_ViewItem]) -> str:
    section_views = [v for v in views if v.section_key == section.key]
    if not section_views:
        return "分化"
    pos = neg = warn = 0
    for item in section_views:
        text = item.view.view + " " + (item.view.insight or "")
        lower = text.lower()
        if any(m in text for m in WARNING_MARKERS) or any(m.lower() in lower for m in WARNING_MARKERS):
            warn += 1
        if any(w in text for w in BULLISH_WORDS) or any(w in lower for w in BULLISH_WORDS):
            pos += 1
        if any(w in text for w in BEARISH_WORDS) or any(w in lower for w in BEARISH_WORDS):
            neg += 1
    if section.key == "geopolitics" and warn >= 2:
        return "紧张升级"
    if pos and neg and abs(pos - neg) <= max(2, len(section_views) // 4):
        return "分化"
    if pos > neg + 1:
        return "偏多关注"
    if neg > pos + 1:
        return "谨慎"
    return "分化"


def _split_topic_views(views: list[_ViewItem], keywords: tuple) -> tuple[list, list, list]:
    """Return (matching_topic_views, bull_items, bear_items) for a single topic.

    Aggregates stance per handle so a KOL never appears on both sides; if a KOL's
    views are mixed, that handle is dropped (counts as no-stance).
    """
    matching: list[tuple[_ViewItem, int]] = []
    by_handle: dict[str, list[tuple[_ViewItem, int]]] = {}
    for item in views:
        text_lower = (item.view.view + " " + (item.view.insight or "")).lower()
        text_zh = item.view.view + " " + (item.view.insight or "")
        if any(k.lower() in text_lower or k in text_zh for k in keywords):
            stance = _stance_for_view(item)
            matching.append((item, stance))
            by_handle.setdefault(item.view.handle.lower(), []).append((item, stance))
    bull_items: list[_ViewItem] = []
    bear_items: list[_ViewItem] = []
    for handle_key, entries in by_handle.items():
        agg = sum(st for _, st in entries)
        if agg == 0:
            continue
        # pick the most stance-aligned, longest view as representative
        entries.sort(key=lambda e: ((1 if (agg > 0 and e[1] > 0) or (agg < 0 and e[1] < 0) else 0), len(e[0].view.view)), reverse=True)
        best = entries[0][0]
        if agg > 0:
            bull_items.append(best)
        else:
            bear_items.append(best)
    return matching, bull_items, bear_items


def _build_divergence_card(views: list[_ViewItem]) -> dict:
    """Pick the highest-priority topic that has at least one bull view and one bear view."""

    empty = {
        "topic": "",
        "bulls": [],
        "bears": [],
        "reverse_vars": [],
        "shadow": "",
        "bull_view": None,
        "bear_view": None,
    }
    candidates = []
    relaxed = []
    for label, keywords in TOPIC_LIBRARY.items():
        topic_views, bull_items, bear_items = _split_topic_views(views, keywords)
        if bull_items and bear_items:
            total = len(bull_items) + len(bear_items)
            if total >= 3:
                candidates.append((label, topic_views, bull_items, bear_items))
            else:
                relaxed.append((label, topic_views, bull_items, bear_items))
    pool = candidates or relaxed
    if not pool:
        return empty
    label, topic_views, bull_items, bear_items = pool[0]
    return {
        "topic": label,
        "bulls": [_view_take(item) for item in bull_items[:3]],
        "bears": [_view_take(item) for item in bear_items[:3]],
        "reverse_vars": _extract_reverse_vars(topic_views),
        "shadow": _build_shadow_line(topic_views, label),
        "bull_view": bull_items[0] if bull_items else None,
        "bear_view": bear_items[0] if bear_items else None,
    }


def _unique_by_handle(items: list[_ViewItem]) -> list[_ViewItem]:
    seen = set()
    out = []
    for it in items:
        h = it.view.handle.lower()
        if h in seen:
            continue
        seen.add(h)
        out.append(it)
    return out


def _stance_for_view(item: _ViewItem) -> int:
    text = item.view.view + " " + (item.view.insight or "")
    lower = text.lower()
    pos = sum(1 for w in BULLISH_WORDS if w in text or w in lower)
    neg = sum(1 for w in BEARISH_WORDS if w in text or w in lower)
    return pos - neg


def _view_take(item: _ViewItem) -> str:
    text = item.view.view.strip().rstrip("。")
    return f"@{item.view.handle}{_identity_suffix(item.view.handle)}：{_trim(text, 100)}"


def _extract_reverse_vars(topic_views: list[tuple]) -> list[str]:
    out = []
    seen = set()
    for item, _ in topic_views:
        text = item.view.view + " " + (item.view.insight or "")
        for pat in (
            r"若[^，。；,;]{4,40}",
            r"一旦[^，。；,;]{4,40}",
            r"除非[^，。；,;]{4,40}",
            r"只要[^，。；,;]{4,40}",
        ):
            for m in re.findall(pat, text):
                key = m[:18]
                if key in seen:
                    continue
                seen.add(key)
                out.append(_trim(m.strip("。；，,;").strip(), 60))
                if len(out) >= 3:
                    return out
    return out


def _build_shadow_line(topic_views: list[tuple], label: str) -> str:
    if not topic_views:
        return ""
    nums: list[str] = []
    for item, _ in topic_views[:3]:
        nums.extend(_extract_numbers(item.view.view + " " + (item.view.insight or "")))
    nums = list(dict.fromkeys(nums))[:3]
    if nums:
        return f"标的缩影：{label} 讨论里出现的关键数值 {'、'.join(nums)}。"
    return ""


def _build_unique_views(views: list[_ViewItem]) -> list[dict]:
    picked: list[dict] = []
    seen_handles = set()
    scored: list[tuple[int, _ViewItem]] = []
    for item in views:
        text = item.view.view + " " + (item.view.insight or "")
        text_lower = text.lower()
        score = 0
        if any(m in text for m in CONDITION_MARKERS):
            score += 3
        if any(m.lower() in text_lower for m in NON_CONSENSUS_MARKERS):
            score += 3
        if any(m in text for m in NON_CONSENSUS_MARKERS):
            score += 2
        if NUMBER_RE.search(item.view.view) and len(item.view.view) >= 60:
            score += 1
        if score == 0:
            continue
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    for _, item in scored:
        h = item.view.handle.lower()
        if h in seen_handles:
            continue
        seen_handles.add(h)
        meaning = _clean_insight(item.view.insight) or "提供独立非共识框架，可作为下一步交易跟踪锚点。"
        picked.append({
            "handle": item.view.handle,
            "view": _clean_view(item.view.view),
            "meaning": meaning,
        })
        if len(picked) >= 4:
            break
    return picked


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _render_masthead(report_date: str, generated_at: str, window_hours: int, total_tweets: int, topics: list[TopicHeat]) -> str:
    hot = " / ".join(f"{item.title} {item.count}" for item in topics[:3]) if topics else "暂无高热主题"
    return f"""<header class="masthead">
  <div class="kicker">KOL TRADING DIGEST · 过去 {window_hours} 小时观点筛选版</div>
  <h1>交易主线 · 可视化分类总结</h1>
  <div class="meta">
    <span>报告日期 {html.escape(report_date)}</span>
    <span>生成时间 {html.escape(generated_at)}</span>
    <span>观点线索 {total_tweets} 条</span>
  </div>
  <div class="submeta">主线聚焦：{html.escape(hot)}</div>
</header>"""


def _render_dashboard(dashboard: dict) -> str:
    return f"""
<section class="section-block">
  <h2 class="section-h"><span class="section-num">A</span>交易主线 · 速览仪表盘</h2>
  <div class="dashboard-grid">
    <section class="panel panel-wide">
      <h3>1. 本日核心交易启示 · {len(dashboard['core_insights'])} 条</h3>
      {_render_core_insights(dashboard['core_insights'])}
    </section>
    <section class="panel">
      <h3>2. 讨论热度排序</h3>
      {_render_topic_heat(dashboard['topics'])}
    </section>
    <section class="panel">
      <h3>3. 板块情绪速览</h3>
      {_render_statuses(dashboard['statuses'])}
    </section>
    <section class="panel panel-wide">
      <h3>4. 最大分歧 · 多空对照卡</h3>
      {_render_divergence(dashboard['divergence'])}
    </section>
    <section class="panel panel-wide">
      <h3>5. 独到 / 有启发性的观点</h3>
      {_render_unique_views(dashboard['unique_views'])}
    </section>
  </div>
</section>"""


def _render_core_insights(insights: list[dict]) -> str:
    if not insights:
        return '<p class="empty">今日 LLM 提炼的观点不足以填满 5 条核心启示。</p>'
    cards = []
    for idx, item in enumerate(insights, 1):
        bullets = "".join(f"<li>{_emph(point)}</li>" for point in item["bullets"])
        cards.append(
            f"""<article class="insight-card">
  <div class="insight-title"><span class="insight-dot">{idx}</span>{html.escape(item['title'])}</div>
  <ul>{bullets}</ul>
</article>"""
        )
    return "".join(cards)


def _render_topic_heat(topics: list[TopicHeat]) -> str:
    if not topics:
        return '<p class="empty">暂无足够热度分布。</p>'
    top = max(item.count for item in topics) or 1
    rows = []
    for item in topics[:5]:
        width = max(20, int(item.count / top * 100))
        rows.append(
            f"""<div class="heat-row">
  <span class="heat-label">{html.escape(item.title)}</span>
  <div class="heat-bar-wrap"><span class="heat-bar" style="width:{width}%"></span></div>
  <span class="heat-value">{item.count}</span>
</div>"""
        )
    return "".join(rows)


def _render_statuses(statuses: list[dict]) -> str:
    badges = []
    for item in statuses:
        cls = STATUS_STYLE.get(item["status"], ("mixed", "#5a6b85"))[0]
        badges.append(
            f"""<div class="status-card {cls}">
  <div class="status-label">{html.escape(item['label'])}</div>
  <div class="status-badge">{html.escape(item['status'])}</div>
  <div class="status-note">{html.escape(item['note'])}</div>
</div>"""
        )
    return "".join(badges)


def _render_divergence(divergence: dict) -> str:
    if not divergence.get("topic"):
        return '<p class="empty">暂无足够明确的多空分歧。</p>'
    bull = "".join(f"<li>{_emph(item)}</li>" for item in divergence["bulls"])
    bear = "".join(f"<li>{_emph(item)}</li>" for item in divergence["bears"])
    if divergence["reverse_vars"]:
        reverse = "".join(f"<li>{_emph(item)}</li>" for item in divergence["reverse_vars"])
        reverse_box = f"""<div class="reverse-box">
  <div class="div-title">关键反向变量（来自原文条件句）</div>
  <ul>{reverse}</ul>
</div>"""
    else:
        reverse_box = ""
    shadow = f'<div class="stock-shadow">{html.escape(divergence["shadow"])}</div>' if divergence.get("shadow") else ""
    return f"""<div class="divergence-head">{html.escape(divergence['topic'])}</div>
<div class="divergence-grid">
  <div class="divergence-col">
    <div class="div-title">看多派</div>
    <ul>{bull}</ul>
  </div>
  <div class="divergence-col">
    <div class="div-title">看空派</div>
    <ul>{bear}</ul>
  </div>
</div>
{reverse_box}
{shadow}"""


def _render_unique_views(items: list[dict]) -> str:
    if not items:
        return '<p class="empty">暂无满足"独到/可证伪"标准的观点。</p>'
    cards = []
    for item in items:
        cards.append(
            f"""<article class="unique-card">
  <div class="unique-handle">@{html.escape(item['handle'])}{_identity_suffix(item['handle'])}</div>
  <div class="unique-view">{_emph(item['view'])}</div>
  <div class="unique-trade">交易含义：{_emph(item['meaning'])}</div>
</article>"""
        )
    return "".join(cards)


def _render_detail_section(section: SectionDigest, idx_letter: str) -> str:
    lines: list[str] = []
    seen_handles: set[str] = set()
    if section.enso_status and section.enso_status.views:
        if section.enso_status.headline:
            lines.append(f'<li class="topic-head">[厄尔尼诺现状] {html.escape(section.enso_status.headline)}</li>')
        for v in section.enso_status.views:
            if not _is_real_view(v):
                continue
            key = v.handle.lower()
            if key in seen_handles:
                continue
            seen_handles.add(key)
            lines.append(_render_view_li(v))
    for block in section.kol_blocks:
        for v in block.views:
            if not _is_real_view(v):
                continue
            key = v.handle.lower()
            if key in seen_handles:
                continue
            seen_handles.add(key)
            lines.append(_render_view_li(v))
    for group in section.topic_groups:
        group_views = [v for v in group.views if _is_real_view(v) and v.handle.lower() not in seen_handles]
        if not group_views:
            continue
        lines.append(f'<li class="topic-head">[{html.escape(group.label)}]</li>')
        for v in group_views[:8]:
            seen_handles.add(v.handle.lower())
            lines.append(_render_view_li(v))
    if not lines:
        lines.append('<li class="empty">今日该板块未提炼出有效中文观点。</li>')
    summary = section.headline
    if section.overview and section.overview != section.headline:
        summary = f"{section.headline} · {section.overview}"
    return f"""<section class="section-block">
  <h2 class="section-h"><span class="section-num">{html.escape(idx_letter)}</span>{html.escape(section.label)}</h2>
  <div class="section-summary">{html.escape(summary)}</div>
  <ul class="detail-list">{''.join(lines)}</ul>
</section>"""


def _render_view_li(v: Viewpoint) -> str:
    primary = _clean_view(v.view)
    insight = _clean_insight(v.insight)
    secondary_html = ""
    if insight:
        secondary_html = f'<div class="detail-secondary">交易含义：{_emph(insight)}</div>'
    return f"""<li>
  <div><span class="detail-handle">@{html.escape(v.handle)}{_identity_suffix(v.handle)}</span>{_emph(primary)}</div>
  {secondary_html}
</li>"""


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

def _identity_suffix(handle: str) -> str:
    label = HANDLE_IDENTITIES.get(handle)
    return f"（{label}）" if label else ""


_EMPH_RE = re.compile(
    r'(\$[A-Za-z]{1,6}'                                  # 股票代码 $MU $NVDA
    r'|[+\-]?\$?\d[\d,]*(?:\.\d+)?%?'                    # 数字 / $金额 / 百分比
    r'(?:\s?(?:万亿|亿|万|个百分点|bps|pt|bbl|桶/日|桶|美元|°C|MM|B|K|倍))?'  # 常见单位
    r')'
)


def _emph(text: str) -> str:
    """先转义，再把关键数据（数字/金额/百分比/$代码）加粗，作为统一的“强调”。"""
    esc = html.escape(text or "")
    return _EMPH_RE.sub(r'<b class="em">\1</b>', esc)


def _clean_view(text: str) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    clean = clean.rstrip("。；;")
    return clean + "。" if clean else ""


def _clean_insight(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"\s+", " ", text.strip())
    clean = re.sub(r"^(交易含义|洞见)[：:]\s*", "", clean)
    clean = clean.rstrip("。；;").strip()
    return clean


def _extract_numbers(text: str) -> list[str]:
    seen: list[str] = []
    for match in NUMBER_RE.findall(text or ""):
        cleaned = re.sub(r"\s+", "", match)
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


def _topic_for_text(text: str, section_key: str, group_label: str) -> str:
    if group_label and group_label != "厄尔尼诺现状":
        return group_label
    text_lower = (text or "").lower()
    text_zh = text or ""
    for title, keywords in TOPIC_LIBRARY.items():
        if any(k.lower() in text_lower or k in text_zh for k in keywords):
            return title
    return _section_label_cn(section_key)


def _section_label_cn(section_key: str) -> str:
    return SECTION_LABEL_CN.get(section_key, section_key)


def _trim(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _css() -> str:
    return r'''
@page {
  size: A4;
  margin: 13mm 12mm 16mm;
  @bottom-center {
    content: counter(page);
    font-size: 9pt;
    color: #5a6b85;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #ffffff; color: #1b2a4a; }
body {
  font-family: "Noto Sans CJK SC", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 10.5pt;
  line-height: 1.62;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.report { padding: 10px 6px 20px; }
/* 防止两栏网格里的长串撑破右边界 */
.dashboard-grid > *, .divergence-grid > *, .heat-row > * { min-width: 0; }
ul, li { overflow-wrap: anywhere; word-break: break-word; }
/* 强调：统一深蓝加粗，不用红字 */
.em { font-weight: 700; color: #1b2a4a; }
.masthead { border-bottom: 2px solid #1b2a4a; padding-bottom: 12px; margin-bottom: 14px; }
.kicker { color: #5a6b85; font-size: 9pt; letter-spacing: 0.08em; font-weight: 600; }
.masthead h1 { margin: 6px 0 8px; font-size: 24pt; line-height: 1.15; color: #1b2a4a; }
.meta, .submeta { color: #5a6b85; font-size: 9.5pt; display: flex; gap: 14px; flex-wrap: wrap; }
.submeta { margin-top: 5px; }
.section-block { margin-top: 16px; }
.section-h {
  margin: 0 0 10px;
  font-size: 14pt;
  color: #1b2a4a;
  display: flex;
  align-items: center;
  gap: 10px;
}
.section-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: #1b2a4a;
  color: #fff;
  font-size: 9.5pt;
  font-weight: 700;
}
.dashboard-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.panel {
  border: 1px solid #d9dfeb;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fbfcfe;
}
.panel-wide { grid-column: span 2; }
.panel h3 { margin: 0 0 8px; font-size: 11.5pt; color: #1b2a4a; }
.insight-card { margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #e2e8f0; }
.insight-card:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: 0; }
.insight-title { font-weight: 700; color: #1b2a4a; margin-bottom: 5px; }
.insight-dot {
  display: inline-flex; width: 20px; height: 20px; margin-right: 6px;
  border-radius: 999px; background: #1b2a4a; color: #fff; align-items: center; justify-content: center;
  font-size: 9pt; font-weight: 700;
}
.insight-card ul { margin: 0; padding-left: 20px; }
.insight-card li { margin-bottom: 3px; color: #263750; }
.heat-row { display: grid; grid-template-columns: 110px 1fr 28px; gap: 8px; align-items: center; margin: 7px 0; }
.heat-label, .heat-value { font-size: 9.5pt; color: #1b2a4a; }
.heat-bar-wrap { height: 10px; background: #e8edf5; border-radius: 999px; overflow: hidden; }
.heat-bar { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #2d4d86, #1b2a4a); }
.status-card { border: 1px solid #dde4ef; border-radius: 10px; padding: 8px 10px; margin-bottom: 8px; background: #fff; break-inside: avoid; }
.status-label { font-weight: 700; margin-bottom: 4px; }
.status-badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 9pt; font-weight: 700; margin-bottom: 4px; }
.status-note { color: #5a6b85; font-size: 9pt; }
.bullish .status-badge { background: rgba(46,125,107,0.14); color: #2e7d6b; }
.mixed .status-badge { background: rgba(90,107,133,0.14); color: #5a6b85; }
.cautious .status-badge { background: rgba(181,117,29,0.14); color: #b5751d; }
.stress .status-badge { background: rgba(162,59,46,0.14); color: #a23b2e; }
.divergence-head { font-size: 11pt; font-weight: 700; color: #1b2a4a; margin-bottom: 8px; }
.divergence-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.divergence-col, .reverse-box {
  border: 1px solid #e2e8f0; border-radius: 10px; padding: 8px 10px; background: #fff;
}
.reverse-box { margin-top: 8px; }
.div-title { font-weight: 700; margin-bottom: 5px; color: #1b2a4a; }
.divergence-col ul, .reverse-box ul { margin: 0; padding-left: 18px; }
.stock-shadow { margin-top: 8px; color: #5a6b85; font-size: 9.5pt; }
.unique-card {
  border: 1px solid #dce8e3; border-left: 5px solid #2e7d6b; border-radius: 8px; background: #fff;
  padding: 8px 10px; margin-bottom: 8px;
}
.unique-handle { font-weight: 700; color: #1b2a4a; margin-bottom: 3px; }
.unique-view { color: #24364f; margin-bottom: 4px; }
.unique-trade { color: #2e7d6b; font-size: 9pt; }
.section-summary {
  border: 1px solid #d9dfeb; border-radius: 10px; padding: 8px 10px; background: #fbfcfe;
  color: #3a4b65; font-size: 9.8pt; margin-bottom: 8px;
}
.detail-list { margin: 0; padding-left: 20px; }
.detail-list li { margin-bottom: 6px; color: #24364f; break-inside: avoid; }
.detail-list li.topic-head {
  list-style: none; margin-left: -16px; margin-top: 6px; padding: 3px 0 2px;
  color: #1b2a4a; font-weight: 700; font-size: 10pt; letter-spacing: 0.04em;
  border-bottom: 1px dashed #c8d3e3;
}
.detail-handle { color: #1b2a4a; font-weight: 700; margin-right: 4px; }
.detail-secondary { color: #5a6b85; font-size: 9.4pt; margin-top: 2px; padding-left: 2px; }
.empty { color: #7b889b; }
.footnote {
  margin-top: 18px; padding-top: 10px; border-top: 1px solid #d9dfeb;
  color: #6a7890; font-size: 8.8pt;
}
'''
