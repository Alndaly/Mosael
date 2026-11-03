#!/bin/sh
# 让当前 clone 使用仓库里的 .githooks。`pnpm install` 的 prepare 会自动跑这一条。
set -eu

root=$(git rev-parse --show-toplevel)
cd "$root"
git config core.hooksPath .githooks
chmod +x .githooks/commit-msg scripts/check_commit_message.py
echo "git hooks installed: core.hooksPath=.githooks"
