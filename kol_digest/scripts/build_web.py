#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 KOL 交易观点交互网页(独立可打开 HTML)。"""
import csv
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "automation", "local"))

from kol_emphasis import strip_numeric_emphasis
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


def export_indices(report_date, ymd, index_history):
    daily = [row for row in index_history.get("daily", []) if row.get("date", "") <= report_date]
    report_dir = os.path.join(ROOT, "日报", ymd)
    os.makedirs(report_dir, exist_ok=True)
    export = {"as_of": report_date, "method": index_history.get("method", {}), "daily": daily}
    save_json(os.path.join(report_dir, f"KOL结构化指数_{ymd}.json"), export)
    csv_path = os.path.join(report_dir, f"KOL结构化指数_{ymd}.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "date", "asset", "score", "mentions", "signal_tweets", "kols", "bullish", "bearish"
        ], lineterminator="\n")
        writer.writeheader()
        for row in daily:
            for asset, values in row.get("assets", {}).items():
                writer.writerow({"date": row["date"], "asset": asset, **{
                    key: values.get(key) for key in writer.fieldnames if key not in {"date", "asset"}
                }})


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
    export_indices(date, ymd, index_history)

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

    meta = {
        "date": date, "n_tweets": len(tweets), "n_kols": len(kols), "n_accounts": tw.get("active_accounts_count", 0),
        "generated": tw.get("generated_at", "")[:16].replace("T", " "),
        "title_zh": rep_raw.get("title", ""), "title_en": translate_text_en(rep_raw.get("title", "")),
        "window_zh": rep_raw.get("window", ""), "window_en": translate_text_en(rep_raw.get("window", "")),
        "subtitle_zh": rep_raw.get("subtitle_stat", "") + "　·　英文推优先译中，缺失时保留原文",
        "subtitle_en": translate_text_en(rep_raw.get("subtitle_stat", "") + "　·　英文推优先译中，缺失时保留原文"),
    }
    report_zh = strip_numeric_emphasis({"insights": rep_raw.get("insights", []), "unique": rep_raw.get("unique", []), "sections": rep_raw.get("sections", [])})
    report_en = strip_numeric_emphasis(load_json_if_exists(content_en_path))
    if not report_en and base_url and api_key and model:
        try:
            report_en = translate_report_en_ai(report_zh, base_url=base_url, api_key=api_key, model=model)
            save_json(content_en_path, report_en)
        except Exception as exc:
            print(f"translate report zh->en failed: {exc}")
    if not report_en:
        report_en = translate_report_en_fallback(report_zh)

    history_series = {
        key: [
            {"date": row["date"], **row["assets"][key]}
            for row in index_history.get("daily", [])[-30:]
        ]
        for key in ("energy", "metals", "grains", "softs")
    }
    current_indices = index_by_date.get(date, {"date": date, "assets": {}})
    data = {date: {
        "meta": meta, "report_zh": report_zh, "report_en": report_en, "tweets": tweets,
        "indices": current_indices.get("assets", {}), "index_history": history_series,
        "index_method": index_history.get("method", {}),
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
