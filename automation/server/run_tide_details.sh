#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"
start_log tide_details
lock_pipeline
sync_repo

fresh="$("$PY" - "$LOCAL/cohort_today.json" "$TODAY" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
today = sys.argv[2]
print(sum(
    1 for row in data.values()
    if row.get("机构", {}).get("dates")
    and row["机构"]["dates"][-1] == today
))
PY
)"
if [ "$fresh" -lt 50 ]; then
  echo "Current-day cohort cache is incomplete; preserving the main report."
  exit 2
fi

"$PY" "$LOCAL/pull_brokers.py" --scope priority
"$PY" "$LOCAL/tide_report.py"

DEST="$ROOT/日报/$YMD"
mkdir -p "$DEST"
DATA_FILE="$LOCAL/output/期货资金潮汐_${YMD}_data.json"
cp "$DATA_FILE" "$DEST/"
"$PY" "$ROOT/日报站/make_tide_web.py" "$DEST/期货资金潮汐_${YMD}_data.json"

WEB="$DEST/期货资金潮汐_${YMD}_交互.html"
test -s "$WEB"
"$PY" - "$DEST/期货资金潮汐_${YMD}_data.json" "$TODAY" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("date") != sys.argv[2] or len(payload.get("rows", [])) < 40:
    raise SystemExit("Tide detail refresh validation failed")
print(f"Tide detail refresh OK: {len(payload.get('rows', []))} rows")
PY

publish_report \
  "日报 $YMD: 资金潮汐席位明细(云端自动)" \
  "$WEB" \
  "$ROOT/日报站/资金潮汐/index.html"
finish_log tide_details
