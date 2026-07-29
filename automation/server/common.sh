#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${WINDRISE_ROOT:-/home/ubuntu/windrise/Daily-Reports}"
PY="${WINDRISE_PYTHON:-/home/ubuntu/windrise/venv/bin/python}"
LOCAL="$ROOT/automation/local"
LOG_DIR="/home/ubuntu/windrise/logs"
LOCK_DIR="/home/ubuntu/windrise/locks"
DEPLOY_KEY="/home/ubuntu/.ssh/daily_reports_deploy"

export TZ=Asia/Shanghai
export PYTHONUNBUFFERED=1
export MPLCONFIGDIR="/home/ubuntu/windrise/.matplotlib"
export GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

mkdir -p "$LOG_DIR" "$LOCK_DIR" "$MPLCONFIGDIR"

TODAY="$(date +%F)"
YMD="${TODAY//-/}"

start_log() {
  local task="$1"
  exec > >(tee -a "$LOG_DIR/${task}_${YMD}.log") 2>&1
  echo "==== $(date '+%F %T %Z') $task start ===="
}

lock_pipeline() {
  exec 9>"$LOCK_DIR/pipeline.lock"
  flock -w 10800 9
}

sync_repo() {
  cd "$ROOT"
  git pull --rebase origin main
}

publish_report() {
  local message="$1"
  shift
  cd "$ROOT"
  "$PY" "$ROOT/日报站/build_site.py"
  git add -- "$@" "$ROOT/日报站/index.html"
  if git diff --cached --quiet; then
    echo "No report changes to publish."
    return 0
  fi
  git commit -m "$message"
  for attempt in 1 2 3; do
    if git pull --rebase origin main && git push origin main; then
      echo "Published: $message"
      return 0
    fi
    echo "Publish retry $attempt/3"
    sleep 30
  done
  return 1
}

finish_log() {
  local task="$1"
  echo "==== $(date '+%F %T %Z') $task done ===="
}
