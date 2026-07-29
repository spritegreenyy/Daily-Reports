#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"
start_log tide
lock_pipeline
sync_repo

fresh=0
for attempt in 1 2 3; do
  "$PY" "$LOCAL/pull_cohorts.py"
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
  echo "Cohort freshness attempt $attempt/3: $fresh varieties"
  if [ "$fresh" -ge 50 ]; then
    break
  fi
  sleep 600
done

if [ "$fresh" -lt 50 ]; then
  echo "Current-day cohort data is incomplete; preserving the previous report."
  exit 2
fi

"$PY" "$LOCAL/pull_brokers.py"
"$PY" "$LOCAL/tide_report.py"
"$PY" "$LOCAL/tide_long.py"

DEST="$ROOT/日报/$YMD"
mkdir -p "$DEST"
DATA_FILE="$LOCAL/output/期货资金潮汐_${YMD}_data.json"
LONG_IMAGE="$LOCAL/output/期货资金潮汐_长图_${YMD}.png"
cp "$DATA_FILE" "$DEST/"
if [ -s "$LONG_IMAGE" ]; then
  cp "$LONG_IMAGE" "$DEST/"
fi
"$PY" "$ROOT/日报站/make_tide_web.py" "$DEST/期货资金潮汐_${YMD}_data.json"

WEB="$DEST/期货资金潮汐_${YMD}_交互.html"
test -s "$WEB"
"$PY" - "$DEST/期货资金潮汐_${YMD}_data.json" "$TODAY" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("date") != sys.argv[2] or len(payload.get("rows", [])) < 40:
    raise SystemExit(
        f"Tide validation failed: date={payload.get('date')} rows={len(payload.get('rows', []))}"
    )
print(f"Tide validation OK: {len(payload.get('rows', []))} rows")
PY

paths=(
  "$DEST/期货资金潮汐_${YMD}_data.json"
  "$WEB"
  "$ROOT/日报站/资金潮汐/index.html"
)
if [ -s "$DEST/期货资金潮汐_长图_${YMD}.png" ]; then
  paths+=("$DEST/期货资金潮汐_长图_${YMD}.png")
fi
publish_report "日报 $YMD: 资金潮汐(云端自动)" "${paths[@]}"
finish_log tide
