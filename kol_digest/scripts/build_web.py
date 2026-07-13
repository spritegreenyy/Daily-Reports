#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 KOL 交易观点交互网页(独立可打开 HTML)。"""
import json
import os
import re
import sys

ROOT = "/Users/yinyue/Downloads/JYWC海拓"
KD = ROOT + "/kol_digest"
OUT = KD + "/output"
TMPL = KD + "/scripts/kol_web_template.html"

TW_BOARD = {
    "macro": ("宏观经济", "Macro", "#5b8def", "宏观", "Macro"),
    "geopolitics": ("地缘政治", "Geopolitics", "#ec6f57", "地缘", "Geo"),
    "commodities": ("大宗商品", "Commodities", "#e0952f", "大宗", "Cmdty"),
    "weather": ("天气气候", "Weather", "#33bfad", "天气", "Weather"),
    "ai_semis": ("AI半导体", "AI & Semis", "#b18ef0", "AI", "AI"),
}
REP_BOARD = {
    "宏观经济": "#5b8def", "地缘政治": "#ec6f57", "大宗商品": "#e0952f", "股票": "#3fb36a",
    "AI半导体": "#b18ef0", "AI半导体科技": "#b18ef0", "AI / 半导体": "#b18ef0", "天气气候": "#33bfad"
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
    ("天气气候", "Weather"), ("AI半导体科技", "AI & Semis"), ("AI半导体", "AI & Semis"),
    ("AI / 半导体", "AI / Semis"), ("厄尔尼诺现状", "El Nino status"),
    ("微软", "Microsoft"), ("英伟达", "Nvidia"), ("特朗普", "Trump"), ("伊朗", "Iran"),
    ("股价", "share price"), ("估值", "valuation"), ("并购", "M&A"), ("预期", "expectations"),
    ("回调", "pullback"), ("融资", "financing"), ("合并", "merge"), ("关系紧张", "relationship is strained"),
    ("大规模股债融资", "large equity-and-debt financing"), ("真实估值", "fair value"),
    ("可能", "may"), ("强化", "reinforces"), ("长期需求叙事", "long-term demand narrative"),
    ("短期", "short term"), ("透支预期", "fully priced in"), ("需警惕", "watch for"), ("获利回吐", "profit taking"),
    ("市场", "market"), ("资本流动", "capital flows"), ("周期性", "cyclical"), ("领导地位轮换", "leadership rotates"),
    ("价差", "valuation gap"), ("最终会收窄", "eventually narrows"),
    ("在我看来", "in my view"), ("积累区域", "accumulation zone"), ("接近", "approaching"),
    ("支撑线", "support line"), ("如果", "if"), ("将", "will"), ("真是遗憾", "is a shame"),
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


def translate_report_en(rep: dict) -> dict:
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


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else None
    if not date:
        print("用法: build_web.py YYYY-MM-DD")
        return 2

    ymd = date.replace("-", "")
    tw = json.load(open(f"{OUT}/kol_tweets_{ymd}.json", encoding="utf-8"))
    rep_raw = json.load(open(f"{OUT}/content_{ymd}.json", encoding="utf-8"))
    zhp = f"{OUT}/kol_zh_{ymd}.json"
    zh = json.load(open(zhp, encoding="utf-8")) if os.path.exists(zhp) else {}

    tweets, kols, dropped = [], set(), 0
    for sec in tw["sections"]:
        bk = sec["key"] if sec["key"] in TW_BOARD else "macro"
        for item in sec["tweets"]:
            sid = item["source_id"].replace("tw_", "")[-6:]
            src_lang = item.get("language", "en")
            body_en = (item.get("body") or "").strip()
            if src_lang == "zh":
                body_zh = body_en
            elif sid in zh and zh[sid].strip():
                body_zh = zh[sid].strip()
            else:
                body_zh = body_en
                if not body_zh:
                    dropped += 1
                    continue
            if not body_en:
                body_en = translate_text_en(body_zh)
            kols.add(item["handle"])
            tags = [x for x in item.get("tags", []) if x != "viewpoint"][:3]
            tweets.append({
                "h": item["handle"], "tier": item.get("tier", 2), "b": bk,
                "t": item.get("published_at", "")[:16].replace("T", " "),
                "x_zh": body_zh, "x_en": body_en, "u": item.get("url", ""),
                "lk": item.get("likes", 0), "rt": item.get("retweets", 0), "rp": item.get("replies", 0),
                "eng": item.get("engagement", 0), "lang": src_lang, "tags": tags
            })

    meta = {
        "date": date, "n_tweets": len(tweets), "n_kols": len(kols), "n_accounts": tw.get("active_accounts_count", 0),
        "generated": tw.get("generated_at", "")[:16].replace("T", " "),
        "title_zh": rep_raw.get("title", ""), "title_en": translate_text_en(rep_raw.get("title", "")),
        "window_zh": rep_raw.get("window", ""), "window_en": translate_text_en(rep_raw.get("window", "")),
        "subtitle_zh": rep_raw.get("subtitle_stat", "") + "　·　英文推优先译中，缺失时保留原文",
        "subtitle_en": translate_text_en(rep_raw.get("subtitle_stat", "") + "　·　英文推优先译中，缺失时保留原文"),
    }
    report_zh = {"insights": rep_raw.get("insights", []), "unique": rep_raw.get("unique", []), "sections": rep_raw.get("sections", [])}
    report_en = translate_report_en(report_zh)
    data = {date: {"meta": meta, "report_zh": report_zh, "report_en": report_en, "tweets": tweets}}
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
