#!/bin/sh
# 过期数据清理(compose 里的 cleanup 服务,默认每小时跑一次)。
#
# **只删 expires_at 已经过去的短期数据**:验证码、浏览器会话、OAuth 中间态。
# 用户、设备、设备码、绑定这些长期数据一行都不碰;也不要顺手加 DELETE 别的表 ——
# 这张清单是维护者明确要求的三张表,删多了是不可逆的事故。
#
# 时间列都是不带时区的 UTC(见 cloud/src/cloud/models.py 的 now()),所以比较时显式
# 换算到 UTC,不受容器 / 数据库会话时区影响。

set -eu

interval="${CLEANUP_INTERVAL_SECONDS:-3600}"
case "$interval" in
  ''|*[!0-9]*)
    echo "CLEANUP_INTERVAL_SECONDS 必须是正整数秒,收到: $interval" >&2
    exit 1
    ;;
esac

echo "cleanup: 每 ${interval} 秒删除一次过期的 cloud_email_codes / cloud_phone_codes / cloud_sessions / cloud_oauth_states / cloud_mfa_tickets"

while :; do
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] deleting expired rows"
  psql -v ON_ERROR_STOP=1 -X <<'SQL'
DELETE FROM cloud_email_codes  WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
DELETE FROM cloud_phone_codes  WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
DELETE FROM cloud_sessions     WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
DELETE FROM cloud_oauth_states WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
DELETE FROM cloud_mfa_tickets  WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
SQL
  sleep "$interval"
done
