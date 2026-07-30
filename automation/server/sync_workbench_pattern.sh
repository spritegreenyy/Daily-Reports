#!/usr/bin/env bash
set -Eeuo pipefail

WORKBENCH_ROOT="${WORKBENCH_ROOT:-/home/ubuntu/windrise/Daily-Workbench}"
DEPLOY_KEY="/home/ubuntu/.ssh/daily_workbench_deploy"
REMOTE="git@github.com:YuangZou/Daily-Workbench.git"
TARGET="daily-pattern/index.html"
TODAY="$(TZ=Asia/Shanghai date +%Y%m%d)"
export GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

if [ ! -d "$WORKBENCH_ROOT/.git" ]; then
  git clone "$REMOTE" "$WORKBENCH_ROOT"
fi

cd "$WORKBENCH_ROOT"
git pull --rebase origin main
if [ -n "$(git status --porcelain)" ]; then
  echo "Workbench clone is not clean; refusing to modify shared files."
  exit 2
fi

python3 - "$TARGET" "$TODAY" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
version = sys.argv[2]
text = path.read_text(encoding="utf-8")
updated, count = re.subn(r"(\?v=)\d{8}", rf"\g<1>{version}", text)
if count != 2:
    raise SystemExit(f"Expected exactly two cache versions, found {count}")
path.write_text(updated, encoding="utf-8")
PY

changed="$(git status --porcelain | sed -E 's/^...//')"
if [ "$changed" != "$TARGET" ]; then
  echo "Safety check failed; changed paths: $changed"
  exit 3
fi

git add -- "$TARGET"
staged="$(git diff --cached --name-only)"
if [ "$staged" != "$TARGET" ]; then
  echo "Safety check failed; staged paths: $staged"
  exit 3
fi

if git diff --cached --quiet; then
  echo "Workbench pattern cache version is already current."
  exit 0
fi

git commit -m "chore: refresh daily-pattern cache $TODAY"
git pull --rebase origin main
git push origin main
