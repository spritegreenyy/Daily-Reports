from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from kol_digest.cli import main
from kol_digest.digest import build_rule_based_sections, classify_section_tweet
from kol_digest.loader import Tweet, load_accounts
from kol_digest.report import render_html


def _tweet(handle: str, tags: list[str], body: str, source_id: str, engagement: int = 100) -> Tweet:
    return Tweet(
        handle=handle,
        category=tags[0],
        primary_tag=tags[0],
        tags=tags,
        tier=1,
        source_id=source_id,
        published_at="2026-06-02T08:00:00Z",
        title=body[:80],
        body=body,
        url=f"https://x.com/{handle}/status/{source_id}",
        likes=engagement,
        replies=0,
        retweets=0,
        engagement=engagement,
        important=1 if engagement >= 100 else 0,
        language="en",
    )


def _sample_tweets() -> list[Tweet]:
    return [
        _tweet("MacroAlf", ["macro", "rates_fx", "framing"], "Fed rates and dollar liquidity remain the key macro risk.", "tw_macro_1", 300),
        _tweet("MacroAlf", ["macro", "rates_fx", "framing"], "Inflation is cooling but bond yields still matter for risk assets.", "tw_macro_2", 200),
        _tweet("MacroAlf", ["macro", "rates_fx", "framing"], "The growth impulse is slowing into the next CPI print.", "tw_macro_3", 150),
        _tweet("MacroAlf", ["macro", "rates_fx", "framing"], "Fourth macro note should be capped in the KOL block.", "tw_macro_4", 120),
        _tweet("BarakRavid", ["geopolitics", "middle_east", "journalist"], "Israel and Iran tensions are again driving Middle East risk.", "tw_geo_me", 280),
        _tweet("KofmanMichael", ["geopolitics", "russia", "defense"], "Russia and Ukraine battlefield dynamics remain attritional.", "tw_geo_ru", 240),
        _tweet("EvanFeigenbaum", ["geopolitics", "china_macro", "thinktank"], "US-China policy and Taiwan risk are central to Asia strategy.", "tw_geo_cn", 220),
        _tweet("JavierBlas", ["oil_energy", "commodities"], "Brent crude oil is supported by OPEC supply discipline.", "tw_oil", 260),
        _tweet("SStapczynski", ["nat_gas_lng", "journalist"], "LNG and natural gas balances are tightening into winter.", "tw_gas", 230),
        _tweet("AndyHomeMetals", ["metals_industrial", "commodities"], "Copper inventories keep the industrial metals market tight.", "tw_metals", 210),
        _tweet("ScottIrwinUI", ["agri_softs", "academic"], "Corn and wheat crop risk is rising with dry weather.", "tw_agri", 205),
        _tweet("BenNollWeather", ["weather_climate", "enso"], "El Nino has faded and La Nina watch remains important for weather risk.", "tw_enso", 270),
        _tweet("RyanMaue", ["weather_climate", "models"], "Weather models point to a more volatile hurricane setup.", "tw_weather", 180),
        _tweet("dylan522p", ["ai_semis", "semiconductors"], "Nvidia Blackwell demand keeps GPU supply tight.", "tw_nvda", 310),
        _tweet("LisaSu", ["semiconductors", "ai_semis", "official"], "AMD MI300 demand is expanding across AI workloads.", "tw_amd", 290),
        _tweet("karpathy", ["ai_semis", "ai_research"], "Inference latency and token cost are becoming the AI bottleneck.", "tw_infer", 250),
        _tweet("SemiAnalysis_", ["ai_semis", "semiconductors"], "CoWoS, HBM and advanced packaging remain the semiconductor constraint.", "tw_pack", 245),
    ]


def test_mixclean_accounts_are_valid():
    accounts = load_accounts("datamux/kol_accounts.yaml")
    handles = [a.handle.lower() for a in accounts]
    assert len(accounts) == 226
    assert len(handles) == len(set(handles))
    assert {a.tier for a in accounts} == {1, 2, 3}


def test_rule_based_sections_match_requested_report_shape():
    sections = build_rule_based_sections(_sample_tweets())
    by_key = {s.key: s for s in sections}
    assert list(by_key) == ["macro", "geopolitics", "commodities", "weather", "ai_semis"]

    macro = by_key["macro"]
    macroalf = next(block for block in macro.kol_blocks if block.handle == "MacroAlf")
    assert len(macroalf.views) == 1

    assert [g.label for g in by_key["geopolitics"].topic_groups[:3]] == ["中东", "俄乌", "中美"]
    assert [g.label for g in by_key["commodities"].topic_groups[:4]] == ["原油", "天然气", "金属", "农产品"]
    assert by_key["weather"].enso_status is not None
    assert len(by_key["weather"].enso_status.views) >= 1
    assert [g.label for g in by_key["ai_semis"].topic_groups[:4]] == ["英伟达", "AMD", "推理", "封装"]


def test_primary_domain_prevents_cross_topic_section_stealing():
    technical_commodity = _tweet(
        "PeterLBrandt",
        ["commodities", "technical", "trader"],
        "Crude oil could break higher after this technical consolidation.",
        "tw_technical_commodity",
    )
    geopolitical_oil = _tweet(
        "JavierBlas",
        ["commodities", "oil_energy", "supply_demand"],
        "Middle East disruption could keep crude oil supported.",
        "tw_geopolitical_oil",
    )
    assert classify_section_tweet(technical_commodity) == "commodities"
    assert classify_section_tweet(geopolitical_oil) == "commodities"


def test_html_contains_required_blocks():
    sections = build_rule_based_sections(_sample_tweets())
    from kol_digest.loader import group_by_category
    html = render_html(sections, group_by_category(_sample_tweets()), report_date="2026-06-02", window_hours=24)
    for text in ["宏观经济", "地缘政治", "大宗商品", "天气气候", "AI半导体科技", "交易主线", "讨论热度排序", "最大分歧", "独到 / 有启发性的观点"]:
        assert text in html


def test_cli_smoke_outputs_sections_json_and_html(tmp_path):
    db = tmp_path / "tweets.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            language TEXT NOT NULL DEFAULT 'en',
            news_type TEXT NOT NULL DEFAULT 'other',
            important INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT,
            fetched_at TEXT NOT NULL,
            analysis_status TEXT NOT NULL DEFAULT 'pending',
            claimed_at TEXT,
            claim_token TEXT,
            analysis_json TEXT,
            analysis_model TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    now = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for t in _sample_tweets():
        con.execute(
            """
            INSERT INTO news_items
            (source, source_id, title, body, url, author, published_at, language,
             news_type, important, raw_json, fetched_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "twitter_x",
                t.source_id,
                t.title,
                t.body,
                t.url,
                f"@{t.handle}",
                now,
                "en",
                t.primary_tag,
                t.important,
                json.dumps({"likes": t.likes, "replies": 0, "retweets": 0}),
                now,
                now,
                now,
            ),
        )
    con.commit()
    con.close()

    out = tmp_path / "out"
    code = main([
        "--db", str(db),
        "--output", str(out),
        "--date", "2026-06-02",
        "--no-llm",
        "--no-pdf",
        "--accounts-file", "datamux/kol_accounts.yaml",
    ])
    assert code == 0
    payload = json.loads((out / "kol_20260602.json").read_text(encoding="utf-8"))
    assert "sections" in payload
    assert "digests" not in payload
    assert sum(section["tweet_count"] for section in payload["sections"]) > 0
    assert {s["key"] for s in payload["sections"]} == {"macro", "geopolitics", "commodities", "weather", "ai_semis"}
    html = (out / "kol_20260602.html").read_text(encoding="utf-8")
    assert "厄尔尼诺现状" in html
