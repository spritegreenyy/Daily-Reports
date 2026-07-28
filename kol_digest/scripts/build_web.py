#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 KOL 交易观点交互网页(独立可打开 HTML)。"""
import csv
import html as html_lib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "automation", "local"))

from kol_emphasis import compact_report_insights, strip_numeric_emphasis
from kol_composite import build_composite_history, load_price_series, run_price_backtests
from kol_indices import build_index_history, match_asset_keys

ROOT = "/Users/yinyue/Downloads/JYWC海拓"
KD = ROOT + "/kol_digest"
OUT = KD + "/output"
TMPL = KD + "/scripts/kol_web_template.html"

TW_BOARD = {
    "macro": ("宏观经济", "Macro", "#5b8def", "宏观", "Macro"),
    "geopolitics": ("地缘政治", "Geopolitics", "#ec6f57", "地缘", "Geo"),
    "commodities": ("大宗商品", "Commodities", "#e0952f", "大宗", "Cmdty"),
    "softs": ("软商品", "Soft Commodities", "#df6f91", "软商品", "Softs"),
    "weather": ("天气气候", "Weather", "#33bfad", "天气", "Weather"),
    "ai_semis": ("AI半导体", "AI & Semis", "#b18ef0", "AI", "AI"),
}
REP_BOARD = {
    "宏观经济": "#5b8def", "地缘政治": "#ec6f57", "大宗商品": "#e0952f", "股票": "#3fb36a",
    "AI半导体": "#b18ef0", "AI半导体科技": "#b18ef0", "AI / 半导体": "#b18ef0", "天气气候": "#33bfad", "软商品": "#df6f91"
}
PRICE_SYMBOLS = {
    "crude": "SC0",
    "gold": "AU0",
    "copper": "CU0",
    "soy_oil": "Y0",
}

EN_MAP = [
    ("KOL 交易主线 · 可视化分类总结", "KOL Trading Themes · Visual Summary"),
    ("过去 ", "Past "), ("截至北京时间 ", "as of Beijing time "), ("约 ", "About "),
    (" 位 KOL / ", " KOLs / "), (" 条信号推文", " signal tweets"),
    (" · 已过滤新闻搬运、纯数据搬运与无关灌水", " · reposted news, raw data forwarding, and irrelevant chatter filtered out"),
    (" · 按板块→子领域分类 · 重点观点已高亮标注", " · grouped by sector -> sub-theme · key views highlighted"),
    ("英文推优先译中，缺失时保留原文", "English tweets are translated into Chinese first; if unavailable, original text is kept"),
    ("最高热度", "Top engagement"), ("交易含义", "Trading implication"), ("关键数据", "Key data"),
    ("互动", "Engagement"), ("来自", "from"), ("板块", "sector"),
    ("宏观经济", "Macro"), ("地缘政治", "Geopolitics"), ("大宗商品", "Commodities"),
    ("软商品", "Soft Commodities"), ("谷物油籽", "Grains & Oilseeds"),
    ("天气气候", "Weather"), ("AI半导体科技", "AI & Semis"), ("AI半导体", "AI & Semis"),
    ("AI / 半导体", "AI / Semis"), ("厄尔尼诺现状", "El Nino status"),
]


def translate_text_en(text: str) -> str:
    if not text:
        return ""
    out = str(text)
    for zh, en in sorted(EN_MAP, key=lambda x: len(x[0]), reverse=True):
        out = out.replace(zh, en)
    out = (out.replace("：", ": ").replace("，", ", ").replace("。", ". ")
              .replace("；", "; ").replace("（", " (").replace("）", ")")
              .replace("、", ", ").replace("　·　", " · ").replace("·", " · "))
    out = re.sub(r"\s+", " ", out).strip()
    return out


def openai_cfg():
    base_url = os.environ.get("KOL_DIGEST_BASE_URL", "").strip()
    api_key = os.environ.get("KOL_DIGEST_API_KEY", "").strip()
    model = os.environ.get("KOL_DIGEST_MODEL", "").strip()
    return base_url, api_key, model


def extract_json(text: str):
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"(\{.*\})", text, re.S)
        if not m:
            raise
        return json.loads(m.group(1))


def call_openai_compatible(*, prompt: str, system_prompt: str, base_url: str, api_key: str, model: str):
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"]
    return extract_json(content)


def batched(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def translate_batch_to_en(batch, *, base_url: str, api_key: str, model: str):
    prompt_rows = [f"[{item['ref']}]\n{item['text']}" for item in batch]
    prompt = (
        "You are translating trader-daily content from Chinese into natural professional English.\n"
        "Requirements:\n"
        "1. Preserve numbers, tickers, @handles, percentages, prices, and directional meaning.\n"
        "2. Keep any HTML tags and attributes unchanged.\n"
        "3. Translate the full text faithfully; do not summarize.\n"
        "4. Output strict JSON only: {\"items\":[{\"ref\":\"id\",\"en\":\"...\"}]}\n\n"
        "Texts:\n" + "\n\n".join(prompt_rows)
    )
    result = call_openai_compatible(
        prompt=prompt,
        system_prompt="You are a bilingual markets editor. Output strict JSON only.",
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
    out = {}
    for item in result.get("items", []):
        ref = str(item.get("ref") or "").strip()
        en = str(item.get("en") or "").strip()
        if ref:
            out[ref] = en
    return out


def translate_report_en_fallback(rep: dict) -> dict:
    return {
        "insights": [
            {"title": translate_text_en(item.get("title", "")),
             "points": [translate_text_en(point) for point in item.get("points", [])]}
            for item in rep.get("insights", [])
        ],
        "unique": [
            [u[0], translate_text_en(u[1]), translate_text_en(u[2])]
            for u in rep.get("unique", [])
        ],
        "sections": [
            [translate_text_en(pair[0]), [
                [translate_text_en(sub[0]), [
                    [row[0], translate_text_en(row[1]), translate_text_en(row[2])]
                    for row in sub[1]
                ]]
                for sub in pair[1]
            ]]
            for pair in rep.get("sections", [])
        ],
    }


def translate_report_en_ai(rep: dict, *, base_url: str, api_key: str, model: str) -> dict:
    prompt = (
        "Translate the following Chinese trading-report JSON into natural English.\n"
        "Requirements:\n"
        "1. Keep the same JSON schema and array structure.\n"
        "2. Preserve @handles, numbers, percentages, prices, tickers, and HTML tags exactly.\n"
        "3. Translate all user-facing Chinese, including section titles, subsection titles, and viewpoint body text.\n"
        "4. Output strict JSON only.\n\n"
        + json.dumps(rep, ensure_ascii=False)
    )
    return call_openai_compatible(
        prompt=prompt,
        system_prompt="You are a bilingual sell-side editor. Output strict JSON only.",
        base_url=base_url,
        api_key=api_key,
        model=model,
    )


def load_json_if_exists(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clean_event_title(value, limit):
    text = re.sub(r"<[^>]+>", "", html_lib.unescape(str(value or "")))
    text = re.sub(r"^(最高热度|Top engagement|Hottest)\s*[·:：-]\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def event_label_from_insight(item, limit):
    title = clean_event_title(item.get("title", ""), limit)
    generic = {
        "宏观经济", "地缘政治", "大宗商品", "软商品", "中东", "贵金属",
        "Macro", "Geopolitics", "Commodities", "Soft Commodities",
        "Middle East", "Precious Metals",
    }
    if title not in generic:
        return title
    points = item.get("points") or []
    if not points:
        return title
    point = clean_event_title(points[0], limit)
    point = re.sub(r"^@[\w_]+(?:（[^）]*）|\([^)]*\))?\s*[:：]\s*", "", point)
    point = re.sub(r"^(核心观点|交易观点|Core view)\s*[:：]\s*", "", point, flags=re.I)
    return clean_event_title(f"{title} · {point}", limit)


def load_event_labels():
    labels = {}
    for name in sorted(os.listdir(OUT)):
        match = re.fullmatch(r"content_(\d{8})\.json", name)
        if not match:
            continue
        ymd = match.group(1)
        date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
        zh = load_json_if_exists(os.path.join(OUT, name)) or {}
        en = load_json_if_exists(os.path.join(OUT, f"content_en_{ymd}.json")) or {}
        zh_items = zh.get("insights") or []
        en_items = en.get("insights") or []
        zh_title = event_label_from_insight(zh_items[0], 34) if zh_items else ""
        en_title = event_label_from_insight(en_items[0], 68) if en_items else ""
        if zh_title:
            labels[date] = {"zh": zh_title, "en": en_title or translate_text_en(zh_title)}
    return labels


def fetch_price_history(report_date):
    cache_path = os.path.join(OUT, "kol_price_history.json")
    cache = load_json_if_exists(cache_path) or {}
    series = cache.get("series", {}) if isinstance(cache, dict) else {}
    should_fetch = cache.get("updated") != report_date or not series
    if should_fetch:
        try:
            import akshare as ak

            fresh = load_price_series(
                lambda symbol: ak.futures_zh_daily_sina(symbol=symbol),
                PRICE_SYMBOLS,
            )
            if fresh:
                series.update(fresh)
                save_json(cache_path, {"updated": report_date, "series": series})
        except Exception as exc:
            print(f"price history refresh failed, using cache: {exc}")
    return series


def section_row_count(section):
    return sum(len(group[1]) for group in section[1]) if len(section) > 1 else 0


def normalize_report(payload, lang):
    base = {
        "insights": payload.get("insights", []),
        "unique": payload.get("unique", []),
        "sections": payload.get("sections", []),
    }
    if lang == "zh":
        base = strip_numeric_emphasis(base)
    return compact_report_insights(base, lang)


def fill_recent_section_fallbacks(report, lang, report_date, max_days=7):
    """Fill only empty visual sections with dated, already-generated prior views."""
    current_dt = datetime.strptime(report_date, "%Y-%m-%d")
    sections = json.loads(json.dumps(report.get("sections", []), ensure_ascii=False))
    empty_names = {section[0] for section in sections if section_row_count(section) == 0}
    if not empty_names:
        return {**report, "sections": sections}, []

    used = {}
    prefix = "最近有效" if lang == "zh" else "Latest valid"
    pattern = "content_????????.json" if lang == "zh" else "content_en_????????.json"
    for path in sorted(Path(OUT).glob(pattern), reverse=True):
        ymd = path.stem[-8:]
        candidate_dt = datetime.strptime(ymd, "%Y%m%d")
        age = (current_dt - candidate_dt).days
        if age <= 0 or age > max_days:
            continue
        payload = load_json_if_exists(path) or {}
        prior = normalize_report(payload, lang)
        for section in prior.get("sections", []):
            name = section[0]
            if name not in empty_names or section_row_count(section) == 0:
                continue
            dated_groups = [
                [f"{prefix} · {ymd[4:6]}-{ymd[6:]} · {group[0]}", group[1]]
                for group in section[1]
                if group[1]
            ]
            if dated_groups:
                for target in sections:
                    if target[0] == name:
                        target[1] = dated_groups
                        break
                used[name] = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
                empty_names.remove(name)
        if not empty_names:
            break
    return {**report, "sections": sections}, used


def export_indices(report_date, ymd, index_history, composite_history, backtests):
    daily = [row for row in index_history.get("daily", []) if row.get("date", "") <= report_date]
    composite_daily = [
        row for row in composite_history.get("daily", []) if row.get("date", "") <= report_date
    ]
    report_dir = os.path.join(ROOT, "日报", ymd)
    os.makedirs(report_dir, exist_ok=True)
    export = {"as_of": report_date, "method": index_history.get("method", {}), "daily": daily}
    save_json(os.path.join(report_dir, f"KOL结构化指数_{ymd}.json"), export)
    csv_path = os.path.join(report_dir, f"KOL结构化指数_{ymd}.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "date", "asset", "score", "raw_score", "confidence", "status", "source",
            "mentions", "signal_tweets", "kols", "bullish", "bearish"
        ], lineterminator="\n")
        writer.writeheader()
        for row in daily:
            for asset, values in row.get("assets", {}).items():
                writer.writerow({"date": row["date"], "asset": asset, "source": row.get("source", ""), **{
                    key: values.get(key) for key in writer.fieldnames if key not in {"date", "asset", "source"}
                }})
    composite_export = {
        "as_of": report_date,
        "method": composite_history.get("method", {}),
        "daily": composite_daily,
        "price_backtests": backtests,
    }
    save_json(os.path.join(report_dir, f"KOL大宗方向总指数_{ymd}.json"), composite_export)
    composite_csv = os.path.join(report_dir, f"KOL大宗方向总指数_{ymd}.csv")
    with open(composite_csv, "w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "date", "score", "energy_contribution", "metals_contribution",
            "grains_contribution", "softs_contribution", "change_5d", "change_20d",
            "coverage", "attention", "disagreement", "mentions",
            "directional_samples", "bullish", "bearish", "event_zh",
        ]
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in composite_daily:
            contributions = row.get("contributions", {})
            writer.writerow({
                **{key: row.get(key) for key in fields},
                "energy_contribution": contributions.get("energy"),
                "metals_contribution": contributions.get("metals"),
                "grains_contribution": contributions.get("grains"),
                "softs_contribution": contributions.get("softs"),
            })


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else None
    if not date:
        print("用法: build_web.py YYYY-MM-DD")
        return 2

    ymd = date.replace("-", "")
    tw = json.load(open(f"{OUT}/kol_tweets_{ymd}.json", encoding="utf-8"))
    rep_raw = json.load(open(f"{OUT}/content_{ymd}.json", encoding="utf-8"))
    zhp = f"{OUT}/kol_zh_{ymd}.json"
    zh = load_json_if_exists(zhp) or {}
    enp = f"{OUT}/kol_en_{ymd}.json"
    en_cache = load_json_if_exists(enp) or {}
    content_en_path = f"{OUT}/content_en_{ymd}.json"

    base_url, api_key, model = openai_cfg()
    index_history = build_index_history(OUT)
    index_by_date = {row["date"]: row for row in index_history.get("daily", [])}
    composite_history = build_composite_history(index_history, load_event_labels())
    price_series = fetch_price_history(date)
    backtests = run_price_backtests(composite_history.get("daily", []), price_series)
    export_indices(date, ymd, index_history, composite_history, backtests)

    pending_en = []
    tweets, kols, dropped = [], set(), 0
    for sec in tw["sections"]:
        bk = sec["key"] if sec["key"] in TW_BOARD else "macro"
        for item in sec["tweets"]:
            sid = item["source_id"].replace("tw_", "")[-6:]
            src_lang = item.get("language", "en")
            body_src = (item.get("body") or "").strip()
            if src_lang == "zh":
                body_zh = body_src
            elif sid in zh and zh[sid].strip():
                body_zh = zh[sid].strip()
            else:
                body_zh = body_src
                if not body_zh:
                    dropped += 1
                    continue

            body_en = body_src if src_lang != "zh" else en_cache.get(sid, "").strip()
            if src_lang == "zh" and not body_en:
                pending_en.append({"ref": sid, "text": body_zh})
            elif not body_en:
                body_en = translate_text_en(body_zh)

            asset_keys = match_asset_keys(body_src)
            if "softs" in asset_keys:
                bk = "softs"
            else:
                bk = sec["key"] if sec["key"] in TW_BOARD else "macro"
            kols.add(item["handle"])
            tags = [x for x in item.get("tags", []) if x != "viewpoint"][:3]
            tweets.append({
                "sid": sid,
                "h": item["handle"], "tier": item.get("tier", 2), "b": bk,
                "t": item.get("published_at", "")[:16].replace("T", " "),
                "x_zh": body_zh, "x_en": body_en, "u": item.get("url", ""),
                "lk": item.get("likes", 0), "rt": item.get("retweets", 0), "rp": item.get("replies", 0),
                "eng": item.get("engagement", 0), "lang": src_lang, "tags": tags
            })

    if pending_en and base_url and api_key and model:
        for batch in batched(pending_en, 8):
            try:
                en_map = translate_batch_to_en(batch, base_url=base_url, api_key=api_key, model=model)
                en_cache.update(en_map)
            except Exception as exc:
                print(f"translate zh->en batch failed: {exc}")
    if pending_en:
        save_json(enp, en_cache)
    for t in tweets:
        if not t["x_en"]:
            t["x_en"] = en_cache.get(t["sid"], "").strip() or translate_text_en(t["x_zh"])
        t.pop("sid", None)

    signal_stat_zh = rep_raw.get("subtitle_stat", "")
    signal_stat_en = translate_text_en(signal_stat_zh)
    meta = {
        "date": date, "n_tweets": len(tweets), "n_kols": len(kols), "n_accounts": tw.get("active_accounts_count", 0),
        "generated": tw.get("generated_at", "")[:16].replace("T", " "),
        "title_zh": rep_raw.get("title", ""), "title_en": translate_text_en(rep_raw.get("title", "")),
        "window_zh": rep_raw.get("window", ""), "window_en": translate_text_en(rep_raw.get("window", "")),
        "subtitle_zh": (
            f"完整推文流 {len(tweets)} 条 / {len(kols)} 位 KOL　·　"
            f"核心方向筛选：{signal_stat_zh}　·　英文推优先译中，缺失时保留原文"
        ),
        "subtitle_en": (
            f"Full stream: {len(tweets)} tweets / {len(kols)} KOLs · "
            f"Core directional filter: {signal_stat_en} · "
            "English tweets are translated into Chinese first; if unavailable, the original is kept"
        ),
    }
    report_zh = normalize_report(rep_raw, "zh")
    report_en = compact_report_insights(strip_numeric_emphasis(load_json_if_exists(content_en_path)), "en")
    if not report_en and base_url and api_key and model:
        try:
            report_en = compact_report_insights(
                translate_report_en_ai(report_zh, base_url=base_url, api_key=api_key, model=model), "en"
            )
            save_json(content_en_path, report_en)
        except Exception as exc:
            print(f"translate report zh->en failed: {exc}")
    if not report_en:
        report_en = compact_report_insights(translate_report_en_fallback(report_zh), "en")
    report_zh, fallback_zh = fill_recent_section_fallbacks(report_zh, "zh", date)
    report_en, fallback_en = fill_recent_section_fallbacks(report_en, "en", date)
    if fallback_zh:
        meta["subtitle_zh"] += "　·　空板块显示近7日最近有效观点，并标注原日期"
        meta["subtitle_en"] += " · Empty sections show the latest valid view from the prior 7 days, with its date"

    history_series = {
        key: [
            {"date": row["date"], **row["assets"][key]}
            for row in index_history.get("daily", [])[-30:]
        ]
        for key in ("energy", "metals", "grains", "softs")
    }
    current_indices = index_by_date.get(date, {"date": date, "assets": {}})
    composite_daily = [
        row for row in composite_history.get("daily", []) if row.get("date", "") <= date
    ]
    current_composite = next(
        (row for row in reversed(composite_daily) if row.get("date") == date),
        composite_daily[-1] if composite_daily else {},
    )
    data = {date: {
        "meta": meta, "report_zh": report_zh, "report_en": report_en, "tweets": tweets,
        "indices": current_indices.get("assets", {}), "index_history": history_series,
        "index_method": index_history.get("method", {}),
        "composite": current_composite,
        "composite_history": composite_daily[-60:],
        "composite_method": composite_history.get("method", {}),
        "backtests": backtests,
    }}
    boards = {
        k: {"label_zh": v[0], "label_en": v[1], "color": v[2], "short_zh": v[3], "short_en": v[4]}
        for k, v in TW_BOARD.items()
    }
    payload = json.dumps({"data": data, "boards": boards, "repColors": REP_BOARD, "dates": [date]}, ensure_ascii=False)

    tmpl = open(TMPL, encoding="utf-8").read()
    html = tmpl.replace("__PAYLOAD__", payload).replace("__DATE__", date)
    dst_dir = f"{ROOT}/日报/{ymd}"
    os.makedirs(dst_dir, exist_ok=True)
    dst = f"{dst_dir}/KOL观点_{ymd}.html"
    open(dst, "w", encoding="utf-8").write(html)
    print(f"OK · 保留{len(tweets)}条 过滤{dropped}条 · {len(kols)}位KOL · -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
