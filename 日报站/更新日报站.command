#!/bin/zsh
# 双击即可：重扫 日报/ → 更新本地日报台 → 生成打包文件 → 提交并推送到 git 仓库
cd "$(dirname "$0")"

python3 build_site.py && python3 build_bundle.py || { echo "生成失败"; read -k1; exit 1; }
open index.html
open -R 发送包/日报台_最新.html

# git 同步（仓库和远程都配置好之后才会生效，否则静默跳过）
cd ..
if git rev-parse --is-inside-work-tree &>/dev/null; then
  git pull --rebase --quiet 2>/dev/null
  git add 日报 日报站 README.md .gitignore
  if git commit -m "日报 $(date +%Y%m%d)" --quiet 2>/dev/null; then
    echo "已提交到本地仓库"
  fi
  if git remote get-url origin &>/dev/null; then
    git push --quiet && echo "已推送到远程仓库"
  fi
fi
