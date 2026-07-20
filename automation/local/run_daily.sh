#!/bin/bash
# 三日报本地每日流水线 v2 (2026-07-07): 目标 17:00 前全部可看。
# 16:05 起步: KOL抓取(后台) + 形态先出先推 → 席位到位即出潮汐v1(先不带成员明细)并推 →
# 逐席位(已提速)完成后重出潮汐v2(带成员下拉)静默更新。
set -u
LOCAL="$(cd "$(dirname "$0")" && pwd)"          # automation/local
ROOT="$(cd "$LOCAL/../.." && pwd)"              # JYWC海拓
PY=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
LOG="$LOCAL/logs/daily_$(date +%Y%m%d).log"
mkdir -p "$LOCAL/logs"
exec >>"$LOG" 2>&1
LOCK=/tmp/run_daily.runlock
if ! mkdir "$LOCK" 2>/dev/null; then echo "已有实例在跑, 退出"; exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
caffeinate -dimsu -w $$ &   # 运行期间阻止 Mac 休眠
echo "==== $(date '+%F %T') run_daily v2 start ===="
DOW=$(date +%u)
TODAY=$(date +%Y-%m-%d); YMD=$(echo "$TODAY" | tr -d '-')
notify() { /usr/bin/osascript -e "display notification \"$2\" with title \"$1\"" >/dev/null 2>&1 || true; }

push() {  # push <msg>
  cd "$ROOT"
  git add 日报 日报站 README.md .gitignore 2>/dev/null
  git diff --cached --quiet || git commit -m "$1" --quiet 2>/dev/null
  for a in 1 2 3; do
    if git pull --rebase --quiet 2>/dev/null && git push origin main --quiet 2>/dev/null; then
      echo "pushed: $1"
      cd "$LOCAL"
      return 0
    fi
    echo "push retry $a/3"
    [ "$a" -lt 3 ] && sleep 30
  done
  cd "$LOCAL"
  return 1
}

pull_kol() {
  for a in 1 2 3; do
    "$PY" "$LOCAL/kol_pull.py" && return 0
    echo "KOL pull retry $a/3"; sleep 180
  done
  return 1
}

publish_kol() {
  if "$PY" "$LOCAL/kol_build.py" --date "$TODAY"; then
    "$PY" "$ROOT/日报站/build_site.py"
    if push "日报 $YMD: KOL观点交互版(自动)"; then
      notify "✅ KOL 已上线" "日报站与 GitHub 已自动更新"
      return 0
    fi
    notify "⚠️ KOL 推送失败" "日报已在本地生成，GitHub 将在下次任务重试"
    return 1
  fi
  echo "KOL build failed, skip empty report"
  notify "⚠️ KOL 生成失败" "已保留上一期，稍后会自动重试"
  return 1
}

if [ "$DOW" -ge 6 ]; then
  echo "weekend: 只做 KOL"
  if pull_kol; then publish_kol; fi
  exit 0
fi

DEST="$ROOT/日报/$YMD"; mkdir -p "$DEST"

# ── 0) KOL 推文抓取扔后台(约30min, 与一切并行) ──
pull_kol > "$LOCAL/logs/kolpull_$YMD.log" 2>&1 &
KOLPID=$!

# ── 1) 形态: 不依赖席位, 最先出先推 (~16:20 上线) ──
"$PY" "$LOCAL/hourly_pattern_report.py"
cp "$LOCAL/output/hourly_pattern_report.pdf" "$DEST/期货形态_${YMD}.pdf" 2>/dev/null
"$PY" "$ROOT/日报站/make_pattern_web.py"
"$PY" "$ROOT/日报站/build_site.py"
push "日报 $YMD: 期货形态(自动)"

# ── 2) 席位分组: 重试到当天龙虎榜发布 ──
for a in $(seq 1 8); do
  "$PY" "$LOCAL/pull_cohorts.py"
  N=$("$PY" -c "
import json;d=json.load(open('$LOCAL/cohort_today.json'))
print(sum(1 for v in d if d[v].get('机构',{}).get('dates') and d[v]['机构']['dates'][-1]=='$TODAY'))")
  echo "pass $a: today_count=$N"
  [ "$N" -ge 50 ] && break
  [ "$a" -ge 4 ] && [ "$N" -eq 0 ] && { echo "今天无更新(节假日?), 停"; notify "⚠️ 席位数据今天没更新" "潮汐未生成(形态已出)"; exit 0; }
  sleep 300
done

# ── 3) 潮汐 v1: 立即出(成员明细自动等下一轮), 先推 (~16:50 上线) ──
"$PY" "$LOCAL/tide_report.py"
"$PY" "$LOCAL/tide_long.py"
cp "$LOCAL/output/期货资金潮汐_${YMD}_data.json" "$DEST/" 2>/dev/null
cp "$LOCAL/output/期货资金潮汐_长图_${YMD}.png" "$DEST/" 2>/dev/null
"$PY" "$ROOT/日报站/make_tide_web.py" "$DEST/期货资金潮汐_${YMD}_data.json"
"$PY" "$ROOT/日报站/build_site.py"
push "日报 $YMD: 资金潮汐(自动)"
notify "✅ 潮汐+形态已上线" "成员明细与KOL稍后自动补"

# ── 4) KOL 一抓完就发布，不再等待耗时的席位成员明细 ──
if wait $KOLPID 2>/dev/null; then publish_kol; fi

# ── 5) 逐席位(已提速~20min) → 潮汐 v2 带成员下拉, 静默更新 ──
"$PY" "$LOCAL/pull_brokers.py"
"$PY" "$LOCAL/tide_report.py"
cp "$LOCAL/output/期货资金潮汐_${YMD}_data.json" "$DEST/" 2>/dev/null
"$PY" "$ROOT/日报站/make_tide_web.py" "$DEST/期货资金潮汐_${YMD}_data.json"
push "日报 $YMD: 潮汐补席位成员明细(自动)"

echo "==== $(date '+%F %T') run_daily v2 done ===="
