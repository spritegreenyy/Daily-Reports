#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KOL 自动建站流水线。

步骤:
1. 读取 automation/local/kol_24h.sqlite，调用 kol_digest.cli 生成结构化日摘要 kol_<YMD>.json
2. 将结构化摘要转换为日报站当前使用的 content_<YMD>.json
3. 批量把英文推文翻成中文，生成 kol_zh_<YMD>.json（失败时回退原文）
4. 调 kol_digest/scripts/build_web.py 输出 日报/<YMD>/KOL观点_<YMD>.html
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
KD = ROOT / "kol_digest"
OUT = KD / "output"
DB = HERE / "kol_24h.sqlite"
ACCOUNTS = ROOT / "datamux" / "kol_accounts_viewpoint_250.yaml"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(KD / "src"))

from kol_digest.digest import EnsoStatus, KolBlock, SectionDigest, TopicGroup, Viewpoint
from kol_digest.loader import Tweet
from kol_digest import report as kd_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--as-of", default="", help="历史补报的统计窗口截止时间 ISO-8601")
    args = parser.parse_args()

    load_dotenv(KD / ".env")
    OUT.mkdir(parents=True, exist_ok=True)

    if not DB.exists():
        raise SystemExit(f"缺少本地 KOL sqlite: {DB}")

    run_dump(args.date, args.hours, args.as_of)
    run_digest(args.date, args.hours, args.as_of)
    ymd = args.date.replace("-", "")

    digest_payload = read_json(OUT / f"kol_{ymd}.json")
    dump_payload = read_json(OUT / f"kol_tweets_{ymd}.json")

    sections = [section_from_dict(item) for item in digest_payload.get("sections", [])]
    tweets_by_section = tweets_by_section_from_dump(dump_payload)
    handle_eng = build_handle_engagement(tweets_by_section)

    content_payload = build_content_payload(
        report_date=args.date,
        digest_payload=digest_payload,
        sections=sections,
        tweets_by_section=tweets_by_section,
        handle_eng=handle_eng,
    )
    content_path = OUT / f"content_{ymd}.json"
    content_path.write_text(json.dumps(content_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {content_path}")

    zh_payload = build_translation_payload(dump_payload)
    zh_path = OUT / f"kol_zh_{ymd}.json"
    zh_path.write_text(json.dumps(zh_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {zh_path}")

    subprocess.run(
        [sys.executable, str(KD / "scripts" / "build_web.py"), args.date],
        cwd=str(ROOT),
        check=True,
    )
    return 0


def digest_command(report_date: str, hours: int, as_of: str) -> tuple[list[str], dict[str, str]]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{KD / 'src'}:{ROOT}{':' + env['PYTHONPATH'] if env.get('PYTHONPATH') else ''}"
    cmd = [
        sys.executable,
        "-m",
        "kol_digest.cli",
        "--db",
        str(DB),
        "--accounts-file",
        str(ACCOUNTS),
        "--hours",
        str(hours),
        "--date",
        report_date,
        "--output",
        str(OUT),
        "--no-pdf",
    ]
    if as_of:
        cmd.extend(["--end", as_of])
    return cmd, env


def run_dump(report_date: str, hours: int, as_of: str) -> None:
    cmd, env = digest_command(report_date, hours, as_of)
    cmd.append("--dump-only")
    subprocess.run(cmd, cwd=str(KD), env=env, check=True)


def run_digest(report_date: str, hours: int, as_of: str) -> None:
    cmd, env = digest_command(report_date, hours, as_of)
    subprocess.run(cmd, cwd=str(KD), env=env, check=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def section_from_dict(item: dict[str, Any]) -> SectionDigest:
    enso = item.get("enso_status")
    return SectionDigest(
        key=str(item.get("key") or ""),
        label=str(item.get("label") or ""),
        headline=str(item.get("headline") or ""),
        overview=str(item.get("overview") or ""),
        tweet_count=int(item.get("tweet_count") or 0),
        handles_count=int(item.get("handles_count") or 0),
        kol_blocks=[kol_block_from_dict(block) for block in item.get("kol_blocks", [])],
        topic_groups=[topic_group_from_dict(group) for group in item.get("topic_groups", [])],
        enso_status=enso_status_from_dict(enso) if isinstance(enso, dict) else None,
        fallback=bool(item.get("fallback", False)),
    )


def kol_block_from_dict(item: dict[str, Any]) -> KolBlock:
    return KolBlock(
        handle=str(item.get("handle") or ""),
        tier=int(item.get("tier") or 0),
        tags=list(item.get("tags") or []),
        views=[view_from_dict(view) for view in item.get("views", [])],
        tweet_count=int(item.get("tweet_count") or 0),
        top_engagement=int(item.get("top_engagement") or 0),
    )


def topic_group_from_dict(item: dict[str, Any]) -> TopicGroup:
    return TopicGroup(
        key=str(item.get("key") or ""),
        label=str(item.get("label") or ""),
        views=[view_from_dict(view) for view in item.get("views", [])],
        tweet_count=int(item.get("tweet_count") or 0),
    )


def enso_status_from_dict(item: dict[str, Any]) -> EnsoStatus:
    return EnsoStatus(
        headline=str(item.get("headline") or ""),
        views=[view_from_dict(view) for view in item.get("views", [])],
        fallback=bool(item.get("fallback", False)),
    )


def view_from_dict(item: dict[str, Any]) -> Viewpoint:
    return Viewpoint(
        handle=str(item.get("handle") or "").lstrip("@"),
        view=str(item.get("view") or ""),
        insight=str(item.get("insight") or ""),
        tweet_refs=list(item.get("tweet_refs") or []),
        published_at=str(item.get("published_at") or ""),
        url=str(item.get("url") or ""),
        engagement=int(item.get("engagement") or 0),
    )


def tweet_from_dict(item: dict[str, Any], section_key: str) -> Tweet:
    return Tweet(
        handle=str(item.get("handle") or "").lstrip("@"),
        category=str(item.get("category") or section_key),
        published_at=str(item.get("published_at") or ""),
        title=str(item.get("title") or ""),
        body=str(item.get("body") or ""),
        url=str(item.get("url") or ""),
        likes=int(item.get("likes") or 0),
        replies=int(item.get("replies") or 0),
        retweets=int(item.get("retweets") or 0),
        engagement=int(item.get("engagement") or 0),
        important=int(item.get("important") or 0),
        language=str(item.get("language") or ""),
        source_id=str(item.get("source_id") or ""),
        tags=list(item.get("tags") or []),
        tier=int(item.get("tier") or 0),
        primary_tag=str(item.get("primary_tag") or "other"),
    )


def tweets_by_section_from_dump(dump_payload: dict[str, Any]) -> dict[str, list[Tweet]]:
    out: dict[str, list[Tweet]] = {}
    for section in dump_payload.get("sections", []):
        key = str(section.get("key") or "")
        out[key] = [tweet_from_dict(item, key) for item in section.get("tweets", [])]
    return out


def build_handle_engagement(tweets_by_section: dict[str, list[Tweet]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for tweets in tweets_by_section.values():
        for tweet in tweets:
            key = tweet.handle.lower()
            out[key] = max(out.get(key, 0), int(tweet.engagement or 0))
    return out


def build_content_payload(
    *,
    report_date: str,
    digest_payload: dict[str, Any],
    sections: list[SectionDigest],
    tweets_by_section: dict[str, list[Tweet]],
    handle_eng: dict[str, int],
) -> dict[str, Any]:
    dashboard = kd_report._build_dashboard(sections, tweets_by_section, handle_eng)
    total_tweets = sum(len(v) for v in tweets_by_section.values())
    total_kols = len({tweet.handle.lower() for tweets in tweets_by_section.values() for tweet in tweets})
    local_generated = format_generated_at(digest_payload.get("generated_at"))
    return {
        "date": report_date,
        "title": "KOL 交易主线 · 可视化分类总结",
        "window": f"过去 {digest_payload.get('window_hours', 24)}h（截至北京时间 {local_generated}）",
        "subtitle_stat": (
            f"约 {total_kols} 位 KOL / {total_tweets} 条信号推文"
            " · 已过滤新闻搬运、纯数据搬运与无关灌水"
            " · 按板块→子领域分类 · 重点观点已高亮标注"
        ),
        "insights": [
            {"title": item["title"], "points": [kd_report._emph(point) for point in item["bullets"]]}
            for item in dashboard.get("core_insights", [])
        ],
        "unique": [
            [f"@{item['handle']}", item["view"], item["meaning"]]
            for item in dashboard.get("unique_views", [])
        ],
        "sections": [render_section_for_web(section) for section in sections],
    }


def format_generated_at(raw: Any) -> str:
    if not raw:
        return datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(raw)[:16].replace("T", " ")


def render_section_for_web(section: SectionDigest) -> list[Any]:
    section_name = section.label
    if section_name == "AI半导体科技":
        section_name = "AI半导体"

    groups: list[list[Any]] = []
    if section.enso_status and section.enso_status.views:
        rows = [render_row(view) for view in section.enso_status.views if kd_report._is_real_view(view)]
        if rows:
            groups.append(["厄尔尼诺现状", rows])

    if section.topic_groups:
        for group in section.topic_groups:
            rows = [render_row(view) for view in group.views if kd_report._is_real_view(view)]
            if rows:
                groups.append([group.label, rows])
    else:
        grouped = OrderedDict()
        for block in section.kol_blocks:
            for view in block.views:
                if not kd_report._is_real_view(view):
                    continue
                label = kd_report._topic_for_text(view.view, section.key, "")
                grouped.setdefault(label, []).append(render_row(view))
        for label, rows in grouped.items():
            if rows:
                groups.append([label, rows[:8]])

    return [section_name, groups]


def render_row(view: Viewpoint) -> list[str]:
    handle = f"@{view.handle}"
    identity = kd_report.HANDLE_IDENTITIES.get(view.handle, "")
    primary = kd_report._emph(kd_report._clean_view(view.view))
    insight = kd_report._clean_insight(view.insight)
    if insight:
        primary += f' <span style="color:#8fa0b3">交易含义：{kd_report._emph(insight)}</span>'
    return [handle, identity, primary]


def build_translation_payload(dump_payload: dict[str, Any]) -> dict[str, str]:
    selected: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for section in dump_payload.get("sections", []):
        for tweet in section.get("tweets", []):
            ref = short_ref(tweet.get("source_id"))
            if ref:
                selected.setdefault(ref, tweet)

    zh_map: dict[str, str] = {}
    pending: list[dict[str, str]] = []
    for ref, tweet in selected.items():
        body = str(tweet.get("body") or "").strip()
        if not body:
            continue
        if str(tweet.get("language") or "").lower() == "zh":
            zh_map[ref] = body
        else:
            pending.append({"ref": ref, "handle": str(tweet.get("handle") or ""), "body": body})

    if not pending:
        return zh_map

    base_url = os.environ.get("KOL_DIGEST_BASE_URL", "").strip()
    api_key = os.environ.get("KOL_DIGEST_API_KEY", "").strip()
    model = os.environ.get("KOL_DIGEST_MODEL", "").strip()
    if not (base_url and api_key and model):
        for item in pending:
            zh_map[item["ref"]] = item["body"]
        return zh_map

    for batch in batched(pending, 8):
        translated = {}
        try:
            translated = translate_batch(batch, base_url=base_url, api_key=api_key, model=model)
        except Exception as exc:
            print(f"translate batch failed: {exc}")
        for item in batch:
            text = translated.get(item["ref"], "").strip() or item["body"]
            zh_map[item["ref"]] = text
    return zh_map


def short_ref(source_id: Any) -> str:
    text = str(source_id or "").replace("tw_", "")
    return text[-6:] if text else ""


def batched(items: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def translate_batch(batch: list[dict[str, str]], *, base_url: str, api_key: str, model: str) -> dict[str, str]:
    prompt_rows = []
    for item in batch:
        prompt_rows.append(
            f"[{item['ref']}] @{item['handle']}\n{item['body']}"
        )
    prompt = (
        "你在为交易员日报翻译 KOL 推文。请把下面每条英文推文翻成自然、简洁、信息完整的中文。\n"
        "要求：\n"
        "1. 保留数字、百分比、价格、时间条件、方向判断、情绪和立场。\n"
        "2. 不要总结成标题，不要补充解释，不要删掉细节。\n"
        "3. 若原文已是中文，直接原样返回。\n"
        "4. 只输出严格 JSON：{\"items\":[{\"ref\":\"123456\",\"zh\":\"中文结果\"}]}。\n\n"
        "待翻译内容：\n" + "\n\n".join(prompt_rows)
    )
    result = call_openai_compatible(
        prompt=prompt,
        system_prompt="你是交易研究团队的双语编辑，只输出严格 JSON。",
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
    out: dict[str, str] = {}
    for item in result.get("items", []):
        ref = str(item.get("ref") or "").strip()
        zh = str(item.get("zh") or "").strip()
        if ref:
            out[ref] = zh
    return out


def call_openai_compatible(
    *,
    prompt: str,
    system_prompt: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 180.0,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
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
    return loads_json(content)


def loads_json(content: str) -> dict[str, Any]:
    clean = content.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean = "\n".join(lines).strip()
    return json.loads(clean)


if __name__ == "__main__":
    raise SystemExit(main())
