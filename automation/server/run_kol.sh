#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"
start_log kol
lock_pipeline
sync_repo

pulled=0
if [ "${WINDRISE_SKIP_PULL:-0}" = "1" ]; then
  test -s "$ROOT/kol_digest/output/kol_tweets_${YMD}.json"
  echo "Reusing the validated KOL pull for $TODAY."
  pulled=1
else
  for attempt in 1 2 3; do
    if "$PY" "$LOCAL/kol_pull.py" --hours 24; then
      pulled=1
      break
    fi
    echo "KOL pull retry $attempt/3"
    sleep 180
  done
fi
if [ "$pulled" -ne 1 ]; then
  echo "KOL pull failed; preserving the previous report."
  exit 2
fi

"$PY" "$LOCAL/kol_build.py" --date "$TODAY" --hours 24

DEST="$ROOT/日报/$YMD"
WEB="$DEST/KOL观点_${YMD}.html"
FOLLOWERS="$DEST/KOL粉丝_${YMD}.json"
test -s "$WEB"
test -s "$FOLLOWERS"
"$PY" - "$ROOT/kol_digest/output/kol_tweets_${YMD}.json" "$FOLLOWERS" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
count = sum(len(section.get("tweets", [])) for section in payload.get("sections", []))
if count < 8:
    raise SystemExit(f"KOL validation failed: only {count} tweets")
followers = json.load(open(sys.argv[2], encoding="utf-8"))
summary = followers.get("summary", {})
coverage = float(summary.get("coverage_pct") or 0)
if coverage < 50:
    raise SystemExit(f"KOL follower validation failed: only {coverage}% coverage")
print(f"KOL validation OK: {count} tweets · follower coverage {coverage}%")
PY

publish_report \
  "日报 $YMD: KOL观点交互版(云端自动)" \
  "$WEB" \
  "$DEST/KOL结构化指数_${YMD}.json" \
  "$DEST/KOL结构化指数_${YMD}.csv" \
  "$DEST/KOL大宗方向总指数_${YMD}.json" \
  "$DEST/KOL大宗方向总指数_${YMD}.csv" \
  "$FOLLOWERS" \
  "$ROOT/日报站/kol/index.html"
finish_log kol
