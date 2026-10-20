# MosaelCloud 账号服务

独立于本地 Mosael 的账号服务:邮箱 + 验证码 + 密码注册、密码 / 验证码两种登录、HttpOnly
cookie 会话、设备码绑定。设计、部署与取舍见
[`docs/CLOUD_ACCOUNTS.md`](../docs/CLOUD_ACCOUNTS.md)。

## 本地跑起来

```bash
cd cloud
uv sync

# 开发:SQLite + http,cookie 不带 Secure;官网在 :3000
# 验证码要发信:Mailpit 在 :1025 时只填 CLOUD_SMTP_HOST 即可(无认证默认不 STARTTLS)。
CLOUD_COOKIE_SECURE=false \
CLOUD_PUBLIC_URL=http://localhost:3000 \
CLOUD_SMTP_HOST=localhost:1025 \
  uv run uvicorn cloud.main:app --host 127.0.0.1 --port 8901 --reload
```

**没配 `CLOUD_SMTP_HOST` 时发码接口会明确回 `503 mail_not_configured`**,不会假装发出;
测试注入假 sender,不连外网。

数据目录默认 `./cloud-data`(库文件 `cloud.db`)。接口前缀 `/api/cloud/v1`,
健康检查 `GET /api/cloud/v1/health`。官网开发时 `next.config.ts` 会把 `/api/cloud/v1/*`
同源反代到这里(见 `website/.env.example` 的 `CLOUD_API_URL`)。

## 测试

```bash
cd cloud
uv run pytest -q     # 每个用例一个临时 SQLite 库,不连外网
uv run ruff check
```

CI 不启动这个服务;它只跑上面的 pytest。

## 生产

- `CLOUD_DATABASE_URL=postgresql+psycopg://…`
- `CLOUD_PUBLIC_URL=https://mosael.com`
- `CLOUD_COOKIE_SECURE=true`
- 反向代理与官网同源(见 docs 里的 Caddy 片段),不要开 CORS。
- 表结构由 `Base.metadata.create_all` 在启动时创建;这是新服务,还没有需要演进的历史数据。
  一旦线上有真实数据,表结构变化就改用迁移。

## 配置

| 环境变量 | 缺省 | 说明 |
| --- | --- | --- |
| `CLOUD_DATA_DIR` | `./cloud-data` | SQLite 与运行数据 |
| `CLOUD_DATABASE_URL` | 空 → 数据目录里的 SQLite | 生产用 Postgres |
| `CLOUD_PUBLIC_URL` | `http://localhost:3000` | 官网原点:设备授权页、同源校验 |
| `CLOUD_COOKIE_SECURE` | `true` | 本地 http 开发设 `false` |
| `CLOUD_SESSION_TTL_DAYS` | `30` | 登录会话有效期 |
| `CLOUD_DEVICE_CODE_TTL_SECONDS` | `600` | 设备码有效期 |
| `CLOUD_DEVICE_POLL_INTERVAL_SECONDS` | `5` | 桌面端轮询间隔 |
| `CLOUD_PASSWORD_MIN_LENGTH` | `8` | 密码下限 |
| `CLOUD_SMTP_HOST` | 空(未配置发信) | 可写 `host:port`;空则发码接口 503 |
| `CLOUD_SMTP_PORT` | `587` | host 里没写端口时用它 |
| `CLOUD_SMTP_TLS` | 有用户名时 `starttls`,否则 `none` | `starttls` / `ssl` / `none` |
| `CLOUD_SMTP_USERNAME` | 空 | 有用户名才登录 |
| `CLOUD_SMTP_PASSWORD` | 空 | 只交给 SMTP,不进日志 |
| `CLOUD_SMTP_FROM` | `no-reply@mosael.com` | 发件人 |
