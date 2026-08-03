#!/usr/bin/env python3
"""Detect newly identified 4-hour patterns and email enabled subscribers once."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_SCAN = HERE / "output" / "pattern_live_scan.json"
DEFAULT_STATE = HERE / "output" / "pattern_alert_state.json"
DEFAULT_RECIPIENTS = HERE / "kol_alert_recipients.json"
DEFAULT_OUTPUT = HERE / "output" / "pattern_alert_email"


def load_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def load_recipients(path: Path) -> list[dict[str, str]]:
    rows = []
    for row in load_json(path, {}).get("recipients", []):
        channels = row.get("alerts") or {}
        email_addr = str(row.get("email") or "").strip()
        if row.get("enabled", True) and channels.get("pattern", True) and "@" in email_addr:
            rows.append({"email": email_addr, "name": str(row.get("name") or "").strip()})
    if not rows:
        raise ValueError("No pattern-alert subscriber is enabled")
    return rows


def flatten(scan: dict[str, Any], min_confidence: float) -> list[dict[str, Any]]:
    rows = []
    for product in scan.get("products", []):
        for item in product.get("structures", []):
            if float(item.get("confidence") or 0) < min_confidence:
                continue
            rows.append({
                "name": product.get("name", ""),
                "code": product.get("code", ""),
                "asof": product.get("asof", ""),
                "latest": product.get("latest"),
                "pattern": item.get("pattern", ""),
                "pattern_cn": item.get("pattern_cn", ""),
                "state": item.get("state", ""),
                "start": item.get("start", ""),
                "end": item.get("end", ""),
                "confidence": float(item.get("confidence") or 0),
                "upper": item.get("upper"),
                "lower": item.get("lower"),
                "direction": item.get("direction", ""),
                "direction_en": item.get("direction_en", ""),
                "reminder": item.get("reminder", ""),
            })
    return rows


def start_distance(left: str, right: str) -> float:
    try:
        a = datetime.strptime("2000-" + left, "%Y-%m-%d %H:%M")
        b = datetime.strptime("2000-" + right, "%Y-%m-%d %H:%M")
        return abs((a - b).total_seconds())
    except ValueError:
        return float("inf")


def prior_match(current: dict[str, Any], previous: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row for row in previous
        if row.get("code") == current.get("code")
        and row.get("pattern") == current.get("pattern")
        and start_distance(str(row.get("start") or ""), str(current.get("start") or "")) <= 48 * 3600
    ]
    return min(candidates, key=lambda row: start_distance(str(row.get("start") or ""), str(current.get("start") or ""))) if candidates else None


def detect(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    for row in current:
        old = prior_match(row, previous)
        if old is None:
            events.append({**row, "event": "new"})
        elif old.get("state") == "形成中" and row.get("state") != "形成中":
            events.append({**row, "event": "confirmed"})
    return sorted(events, key=lambda row: (row.get("event") == "confirmed", row.get("confidence", 0)), reverse=True)


def build_html(generated: str, events: list[dict[str, Any]]) -> str:
    cards = []
    for index, row in enumerate(events, 1):
        label = "突破确认" if row["event"] == "confirmed" else "新形态"
        cards.append(f"""
        <div style="background:#16212e;border:1px solid #2b3d50;border-left:4px solid #e7b24d;border-radius:11px;padding:15px 17px;margin:0 0 11px">
          <div style="color:#e7b24d;font-size:10px;font-weight:800;letter-spacing:1px">ALERT {index:02d} · {label}</div>
          <div style="color:#fff;font-size:18px;font-weight:800;margin-top:7px">{html.escape(row['name'])} · {html.escape(row['pattern_cn'])}</div>
          <div style="color:#cbd7e4;font-size:13px;line-height:1.6;margin-top:6px">{html.escape(row['direction'])}</div>
          <div style="color:#8194a7;font-size:11px;line-height:1.6;margin-top:7px">置信度 {row['confidence']:.3f} · 上轨 {row['upper']:,.0f} / 下轨 {row['lower']:,.0f} · 数据至 {html.escape(row['asof'])}</div>
          <div style="color:#64778b;font-size:10px;margin-top:7px">{html.escape(row['direction_en'])}</div>
        </div>""")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Windrise Pattern Alert</title></head>
<body style="margin:0;background:#0e1620;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif"><div style="max-width:650px;margin:auto;padding:26px 14px">
<div style="color:#e7b24d;font:700 24px Georgia,serif">Windrise 风起</div><h1 style="color:#fff;font-size:22px;margin:7px 0 3px">期货形态实时提醒</h1><div style="color:#768a9e;font-size:11px;margin-bottom:17px">{html.escape(generated)} · 仅首次出现或状态升级时发送</div>
{''.join(cards)}<div style="color:#64778b;font-size:10px;line-height:1.7;margin-top:14px">形态识别是条件化研究线索，不代表收益概率，不构成投资建议。</div></div></body></html>"""


def message_for(recipient: dict[str, str], generated: str, events: list[dict[str, Any]], body: str) -> EmailMessage:
    message = EmailMessage()
    sender = os.environ.get("KOL_MAIL_FROM") or os.environ.get("SMTP_USER") or "windrise@localhost"
    message["From"] = sender
    message["To"] = recipient["email"]
    confirmed = sum(row["event"] == "confirmed" for row in events)
    message["Subject"] = f"Windrise形态Alert · 新增{len(events)}项 · 确认突破{confirmed}项"
    message.set_content(f"{recipient.get('name') or recipient['email']}，你好：\n\n识别到{len(events)}项新形态变化，其中{confirmed}项为突破确认。\n扫描时间：{generated}\n")
    message.add_alternative(body, subtype="html")
    return message


def send(message: EmailMessage) -> None:
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not host or not user or not password:
        raise RuntimeError("SMTP_HOST / SMTP_USER / SMTP_PASSWORD is not configured")
    port = int(os.environ.get("SMTP_PORT", "465"))
    if os.environ.get("SMTP_SSL", "1") != "0":
        with smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context()) as smtp:
            smtp.login(user, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, password)
            smtp.send_message(message)


def save_state(path: Path, generated: str, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"updated": generated, "structures": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", type=Path, default=DEFAULT_SCAN)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--recipients", type=Path, default=DEFAULT_RECIPIENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-confidence", type=float, default=float(os.environ.get("PATTERN_ALERT_MIN_CONFIDENCE", "0.60")))
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--alert-on-first-run", action="store_true")
    args = parser.parse_args()

    scan = load_json(args.scan, {})
    generated = str(scan.get("generated") or datetime.now().astimezone().isoformat(timespec="seconds"))
    current = flatten(scan, args.min_confidence)
    previous_payload = load_json(args.state, {})
    previous = previous_payload.get("structures", [])
    first_run = not args.state.is_file()
    events = detect(current, previous) if (previous or args.alert_on_first_run) else []

    args.output.mkdir(parents=True, exist_ok=True)
    preview = args.output / "pattern_alert_latest.html"
    preview.write_text(build_html(generated, events), encoding="utf-8")
    sent = []
    if events and args.send:
        body = preview.read_text(encoding="utf-8")
        for recipient in load_recipients(args.recipients):
            message = message_for(recipient, generated, events, body)
            send(message)
            sent.append(recipient["email"])
    save_state(args.state, generated, current)
    print(json.dumps({"first_run": first_run, "structures": len(current), "events": len(events), "sent": sent, "preview": str(preview)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
