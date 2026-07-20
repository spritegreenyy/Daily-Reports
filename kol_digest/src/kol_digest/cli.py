"""CLI: pull last-24h KOL tweets → DeepSeek synth → HTML + PDF."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .digest import synthesize_all
from .loader import group_by_category, load_accounts, load_recent_tweets, resolve_accounts_path
from .report import build_section_tweets, export_pdf, render_html, render_tweets_markdown, write_html

logger = logging.getLogger("kol_digest")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="kol-digest")
    parser.add_argument("--db", default=os.environ.get("KOL_DIGEST_DB") or "/root/.datamux/unified_news.sqlite")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--output", default=os.environ.get("KOL_DIGEST_OUTPUT") or "output")
    parser.add_argument(
        "--accounts-file",
        default=os.environ.get("KOL_DIGEST_ACCOUNTS_FILE") or "kol_accounts.yaml",
        help="mixclean KOL 名单路径 (默认自动查找 datamux/kol_accounts.yaml)",
    )
    parser.add_argument("--date", default="", help="报告日期 YYYY-MM-DD (默认今天)")
    parser.add_argument(
        "--end",
        default="",
        help="统计窗口截止时间 ISO-8601；历史补报时用于固定各自的 24h 窗口",
    )
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM，仅出列表")
    parser.add_argument("--no-pdf", action="store_true", help="只出 HTML / JSON，不出 PDF")
    parser.add_argument(
        "--dump-only",
        action="store_true",
        help="只导出规则过滤后的推文 (markdown + json)，不跑 LLM / HTML / PDF（无需 API）",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    db = Path(args.db)
    if not db.exists():
        logger.error("DB not found: %s", db)
        return 2

    report_date = args.date or datetime.now().strftime("%Y-%m-%d")
    logger.info("loading tweets from %s (hours=%d)", db, args.hours)

    accounts_path = resolve_accounts_path(args.accounts_file)
    accounts = load_accounts(accounts_path)
    logger.info("loaded %d active KOL accounts from %s", len(accounts), accounts_path)

    try:
        end_dt = datetime.fromisoformat(args.end.replace("Z", "+00:00")) if args.end else None
        if end_dt is not None and end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if end_dt is not None:
            end_dt = end_dt.astimezone(timezone.utc)
    except ValueError:
        logger.error("invalid --end value: %s", args.end)
        return 2

    tweets = load_recent_tweets(db, hours=args.hours, end_dt=end_dt, accounts=accounts)
    generated_at = (end_dt or datetime.now(timezone.utc)).isoformat()
    logger.info("got %d tweets", len(tweets))
    bundles = group_by_category(tweets)
    for b in bundles:
        logger.info("  %s: %d tweets / %d handles", b.category, len(b.tweets), b.handles_count)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = report_date.replace("-", "")

    if args.dump_only:
        md = render_tweets_markdown(tweets, report_date=report_date, window_hours=args.hours)
        md_path = out_dir / f"kol_tweets_{date_tag}.md"
        md_path.write_text(md, encoding="utf-8")
        logger.info("wrote %s", md_path)

        dump_payload = {
            "report_date": report_date,
            "generated_at": generated_at,
            "window_hours": args.hours,
            "accounts_file": str(accounts_path),
            "active_accounts_count": len(accounts),
            "sections": [
                {
                    "key": key, "label": label,
                    "tweet_count": len(sel),
                    "handles_count": len({t.handle for t in sel}),
                    "tweets": [t.to_dict() for t in sel],
                }
                for key, label, sel in build_section_tweets(tweets)
            ],
        }
        json_path = out_dir / f"kol_tweets_{date_tag}.json"
        json_path.write_text(json.dumps(dump_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("wrote %s", json_path)
        return 0

    sections = synthesize_all(tweets, use_llm=not args.no_llm)

    digest_payload = {
        "report_date": report_date,
        "generated_at": generated_at,
        "window_hours": args.hours,
        "accounts_file": str(accounts_path),
        "active_accounts_count": len(accounts),
        "sections": [dataclasses.asdict(s) for s in sections],
        "categories": [
            {
                "category": b.category, "label": b.label,
                "tweet_count": len(b.tweets), "handles_count": b.handles_count,
                "tweets": [t.to_dict() for t in b.tweets],
            }
            for b in bundles
        ],
    }
    json_path = out_dir / f"kol_{report_date.replace('-', '')}.json"
    json_path.write_text(json.dumps(digest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("wrote %s", json_path)

    html_str = render_html(sections, bundles, report_date=report_date, window_hours=args.hours)
    html_path = write_html(out_dir, html_str, report_date)
    logger.info("wrote %s", html_path)

    if not args.no_pdf:
        pdf_path = out_dir / f"kol_{report_date.replace('-', '')}.pdf"
        try:
            export_pdf(html_path, pdf_path)
            logger.info("wrote %s", pdf_path)
        except Exception as exc:
            logger.error("PDF export failed: %s", exc)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
