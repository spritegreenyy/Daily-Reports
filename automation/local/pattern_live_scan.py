#!/usr/bin/env python3
"""Run a lightweight live 4-hour pattern scan without rendering charts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from four_hour_multi_product_prototype import (
    PRODUCTS,
    choose_candidates,
    compress_bars,
    deadline,
    fetch_hourly,
    serialize,
)

HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "output" / "pattern_live_scan.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = []
    errors = []
    for name, code in PRODUCTS:
        try:
            with deadline(30):
                hourly = fetch_hourly(code).tail(260)
            frame = compress_bars(hourly, 4)
            rows.append(serialize(name, code, frame, choose_candidates(frame)))
        except Exception as exc:
            errors.append({"name": name, "code": code, "error": str(exc)})

    payload = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "timeframe": "4h",
        "products": rows,
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"output": str(args.output), "products": len(rows), "errors": errors}, ensure_ascii=False))
    return 0 if len(rows) >= 12 else 2


if __name__ == "__main__":
    raise SystemExit(main())
