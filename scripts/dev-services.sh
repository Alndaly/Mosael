#!/usr/bin/env bash
# 把本地开发服务重建到**当前 HEAD**:官网(3100,生产构建)+ 云端(8000)。
#
# 维护者就用这两个服务测东西,所以**每次任务做完都要跑一次** —— 不跑的话他看到的还是
# 上一个提交的行为(踩过:改了 toast/列表,他刷新看到的还是旧的)。
#
#   scripts/dev-services.sh            # 官网 + 云端都重建
#   scripts/dev-services.sh web        # 只重建官网
#   scripts/dev-services.sh cloud      # 只重启云端(云端代码变了才需要)
#
# 云端的密钥(126 SMTP、官方号密码)放在 ~/.mosael-dev.env —— **不进仓库**。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEV_ENV="${MOSAEL_DEV_ENV:-$HOME/.mosael-dev.env}"
target="${1:-all}"

wait_port() { # $1=端口 $2=秒
  for _ in $(seq 1 "${2:-30}"); do
    if lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "端口 $1 没起来" >&2
  return 1
}

if [ "$target" = "all" ] || [ "$target" = "web" ]; then
  echo "== 官网:构建 + 重启 3100 =="
  cd "$ROOT/website"
  lsof -nP -iTCP:3100 -sTCP:LISTEN -t 2>/dev/null | xargs -r kill || true
  sleep 1
  npx next build >/tmp/mosael-web-build.log 2>&1 || { echo "构建失败,看 /tmp/mosael-web-build.log" >&2; exit 1; }
  nohup npx next start -p 3100 >/tmp/mosael-web.log 2>&1 &
  wait_port 3100 40
  echo " 3100 ✓"
fi

if [ "$target" = "all" ] || [ "$target" = "cloud" ]; then
  echo "== 云端:重启 8000(启动时会跑迁移)=="
  [ -f "$DEV_ENV" ] || { echo "缺 $DEV_ENV(126 SMTP 与官方号密码在那里)" >&2; exit 1; }
  lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | xargs -r kill || true
  sleep 1
  set -a; . "$DEV_ENV"; set +a
  cd "$ROOT/cloud"
  nohup uv run uvicorn cloud.main:app --host 127.0.0.1 --port 8000 >/tmp/mosael-cloud.log 2>&1 &
  wait_port 8000 40
  echo " 8000 ✓"
fi

echo "== 自检 =="
for p in /zh /zh/plugins /zh/workflows /zh/community; do
  printf "  %-16s " "$p"
  curl -sS -m 20 -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:3100$p" || echo "失败"
done
printf "  cloud health     "
curl -sS -m 10 "http://127.0.0.1:8000/api/cloud/v1/health" || true
echo
