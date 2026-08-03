#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"
start_log pattern_alert

exec 9>"$LOCK_DIR/pattern-alert.lock"
if ! flock -n 9; then
  echo "Another live pattern scan is still running; skip this interval."
  exit 0
fi

MAIL_ENV="${WINDRISE_MAIL_ENV:-/home/ubuntu/windrise/.config/kol_mail.env}"
RECIPIENTS="${WINDRISE_ALERT_RECIPIENTS:-/home/ubuntu/windrise/config/alert_recipients.json}"
if [ ! -s "$MAIL_ENV" ]; then
  echo "Mail configuration is missing: $MAIL_ENV"
  exit 3
fi

set -a
source "$MAIL_ENV"
set +a

SCAN="$LOCAL/output/pattern_live_scan.json"
STATE="/home/ubuntu/windrise/state/pattern_alert_state.json"
"$PY" "$LOCAL/pattern_live_scan.py" --output "$SCAN"
"$PY" "$LOCAL/pattern_alert_email.py" \
  --scan "$SCAN" \
  --state "$STATE" \
  --recipients "$RECIPIENTS" \
  --send

finish_log pattern_alert
