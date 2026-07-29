#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"
start_log pattern
lock_pipeline
sync_repo

"$PY" "$LOCAL/four_hour_multi_product_prototype.py" --date "$TODAY"

RESULT="$LOCAL/output/多品种4小时形态扫描_本地试验.json"
REPORT="$ROOT/日报/$YMD/期货形态_$YMD.html"
"$PY" - "$RESULT" "$TODAY" <<'PY'
import json
import sys

path, today = sys.argv[1:3]
payload = json.load(open(path, encoding="utf-8"))
products = payload.get("products", [])
fresh = sum(
    1 for row in products
    if str(row.get("asof", "")).startswith(today)
    and str(row.get("asof", ""))[11:16] >= "15:00"
)
if len(products) < 12 or fresh < 12 or len(payload.get("errors", [])) > 3:
    raise SystemExit(
        f"Pattern freshness check failed: products={len(products)} fresh={fresh} "
        f"errors={len(payload.get('errors', []))}"
    )
print(f"Pattern freshness OK: products={len(products)} fresh={fresh}")
PY

test -s "$REPORT"
publish_report \
  "日报 $YMD: 4h多结构期货形态(云端自动)" \
  "$REPORT" \
  "$ROOT/日报站/形态/index.html"
finish_log pattern
