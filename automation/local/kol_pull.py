#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KOL 推文本地一次性拉取(2026-07-07, 服务器重装后迁移)。
直接调 datamux 的 TwitterMonitorSource(Playwright + 本机 ~/.x_cookies.json)抓
tier1/2/3 全部 KOL 近 24h 推文 → 写本地 sqlite(news_items, 与原服务器库同 schema)
→ 调 kol_digest.cli --dump-only 导出 output/kol_tweets_<YMD>.{json,md}。
之后由 kol_build.py 自动做摘要、译中与建站。
用法: python3 kol_pull.py [--hours 24]
"""
import argparse, sqlite3, sys, subprocess
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))                    # import datamux.*
ACCOUNTS = str(ROOT / "datamux/kol_accounts_viewpoint_250.yaml")
COOKIES = str(Path.home() / ".x_cookies.json")
DB = HERE / "kol_24h.sqlite"
KD = ROOT / "kol_digest"

DDL = """
CREATE TABLE IF NOT EXISTS news_items (
  source TEXT, source_id TEXT PRIMARY KEY, title TEXT, body TEXT, url TEXT,
  author TEXT, published_at TEXT, language TEXT, news_type TEXT,
  important INTEGER, raw_json TEXT
);
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    args = ap.parse_args()

    from datamux.sources.news.twitter_monitor import TwitterMonitorSource

    all_items = []
    for tier in (1, 2, 3):
        src = TwitterMonitorSource(accounts_file=ACCOUNTS, tier=tier,
                                   name_suffix=f"t{tier}", cookies_file=COOKIES,
                                   max_tweets_per_account=10)
        r = src._fetch_sync(None)      # 一次性抓取, 不用游标
        print(f"tier{tier}: {len(r.items)} 条")
        all_items += r.items

    if not all_items:
        print("KOL 抓取结果为 0，保留上次数据库并停止发布", file=sys.stderr)
        return 2

    con = sqlite3.connect(DB)
    con.executescript(DDL)
    con.execute("DELETE FROM news_items")
    for it in all_items:
        con.execute(
            "INSERT OR REPLACE INTO news_items(source,source_id,title,body,url,author,"
            "published_at,language,news_type,important,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (it["source"], it["source_id"], it["title"], it["body"], it["url"], it["author"],
             it["published_at"], it["language"], it["news_type"], it["important"], it["raw_json"]))
    con.commit(); con.close()
    print(f"sqlite: {len(all_items)} 条 -> {DB}")

    date = datetime.now().strftime("%Y-%m-%d")
    env = {"PYTHONPATH": str(KD / "src")}
    import os
    env = {**os.environ, **env}
    rc = subprocess.run([sys.executable, "-m", "kol_digest.cli",
                         "--db", str(DB), "--accounts-file", ACCOUNTS,
                         "--hours", str(args.hours), "--date", date,
                         "--dump-only", "--output", str(KD / "output")],
                        env=env).returncode
    print("kol_digest dump rc=", rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
