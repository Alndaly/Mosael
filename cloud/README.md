# MosaelCloud 账号服务

独立于本地 Mosael 的账号服务:邮箱 + 验证码 + 密码注册、密码 / 验证码两种登录、
**GitHub / Google 第三方登录(授权码 + PKCE)**、HttpOnly cookie 会话、设备码绑定,
以及社区分享第①笔:**身份(昵称 / 短名 / 头像种子)+ 分享 + 点赞 / 收藏 / 评论**,注册即登录。
设计、部署与取舍见 [`docs/CLOUD_ACCOUNTS.md`](../docs/CLOUD_ACCOUNTS.md)。

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

第三方登录同理:**没配 `CLOUD_GITHUB_CLIENT_ID/SECRET` 或 `CLOUD_GOOGLE_CLIENT_ID/SECRET`
就当作没启用**,`/oauth/{provider}/start` 会 302 回官网并带 `oauth_error=oauth_not_configured`,
官网也不渲染那颗按钮。本地想试真的第三方授权时,把两个 OAuth 应用的回调地址填成:

```
http://localhost:3000/api/cloud/v1/oauth/github/callback
http://localhost:3000/api/cloud/v1/oauth/google/callback
```

回调地址**只由 `CLOUD_PUBLIC_URL` 推出**,所以它必须和用户在浏览器里访问的 Origin 一致。

数据目录默认 `./cloud-data`(库文件 `cloud.db`)。接口前缀 `/api/cloud/v1`,
健康检查 `GET /api/cloud/v1/health`。官网开发时 `next.config.ts` 会把 `/api/cloud/v1/*`
同源反代到这里(见 `website/.env.example` 的 `CLOUD_API_URL`)。

## 社区分享接口(P1)

**前缀 `/api/cloud/v1`。读接口公开;写接口要 session,发布 / 评论还要求已设置 `display_name`
(没有 → `409 identity_required`,提示用户先起名字)。公开响应里只有
`{display_name, handle, avatar_seed}` 三列身份,email 永不出现在公开响应里。**

```
GET    /me                        → {user} | 401
PUT    /me                        body {display_name?, handle?} → {user};冲突 409 / 校验 422
POST   /shares                    body {kind,title,summary?,payload,license?} → {share} (201)
                                  kind 只能是 workflow|board(否则 422);payload > 2 MB → 413
GET    /shares                    ?q=&kind=&sort=new|hot&limit=&cursor= → {items,next_cursor}
GET    /shares/{id}               → {share}(不含 payload)
GET    /shares/{id}/payload       → {payload}
POST   /shares/{id}/download      → {payload},downloads + 1
DELETE /shares/{id}               → 204(作者软删;非作者 404)
POST/DELETE /shares/{id}/like     → 204(幂等)
POST/DELETE /shares/{id}/favorite → 204(幂等)
GET    /shares/{id}/comments      ?limit=&cursor= → {items,next_cursor}
POST   /shares/{id}/comments      body {body} → {comment} (201)
DELETE /shares/{id}/comments/{cid} → 204(仅评论本人)
GET    /users/{handle}/shares     → {items,next_cursor}
```

`/me` 是**本人**形状:除身份三列外还带 `id` / `email` / `email_verified_at` / `created_at`
(只有本人看得到);公开列表 / 详情 / 评论里的 `author` 只有三列。

`share` 的公开形状固定为
`{id,kind,title,summary,bytes,license,created_at,author,stats,liked_by_me,favorited_by_me}`;
`stats = {downloads,likes,favorites,comments}`;游客的 `liked_by_me` / `favorited_by_me` 是 false。
`payload` 只在 `/payload` 与 `/download` 单独取。

## 测试

```bash
cd cloud
uv run pytest -q     # 每个用例一个临时 SQLite 库,不连外网
uv run ruff check
```

CI 不启动这个服务;它只跑上面的 pytest。OAuth 测试注入
`tests/conftest.py` 里的 `FakeOAuthProvider`(会像真 provider 一样校验 PKCE 与 redirect_uri),
**不连 GitHub / Google**。

## 生产

- `CLOUD_DATABASE_URL=postgresql+psycopg://…`
- `CLOUD_PUBLIC_URL=https://mosael.com`
- `CLOUD_COOKIE_SECURE=true`
- `CLOUD_GITHUB_CLIENT_ID` / `CLOUD_GITHUB_CLIENT_SECRET`(可选)
- `CLOUD_GOOGLE_CLIENT_ID` / `CLOUD_GOOGLE_CLIENT_SECRET`(可选)
- 反向代理与官网同源(见 docs 里的 Caddy 片段),不要开 CORS。
- **表结构只由 `migrations/`(`alembic.ini`)演进,启动时自动升到 head**;没有 `create_all`
  那条平行路径。表结构变化 = 改 `models.py` + 写一条新迁移,旧数据不写兼容分支。
- 部署升级:镜像会带上 `migrations/`,启动即升级;也可以显式跑
  `uv run python -m cloud.cli migrate`。**从 create_all 时代升级的已有库**先一次性
  `uv run python -m cloud.cli stamp 0001`(它已经具备 0001 的全部表),再 `migrate`。
- 社区分享第①笔的迁移是 `migrations/versions/0002_identity_and_community.py`:
  只给 `cloud_users` 加 `display_name` / `handle` / `avatar_seed` 三列,再建分享与互动四表。
  已有账号保持"没有身份"的状态(三列为空),写接口会让用户自己起名 —— **不替旧数据猜昵称**。
- 登录仍是原来的规则:`cloud_users.password_hash` 可空(第三方登录建的账号没有密码)。

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
| `CLOUD_GITHUB_CLIENT_ID` / `_SECRET` | 空(未启用) | GitHub OAuth App 凭据;空则入口报"没启用" |
| `CLOUD_GOOGLE_CLIENT_ID` / `_SECRET` | 空(未启用) | Google OAuth 客户端凭据;空则入口报"没启用" |
| `CLOUD_OAUTH_STATE_TTL_SECONDS` | `600` | 一次 OAuth 登录的 state / nonce 有效期 |

### 第三方 OAuth 应用的填法

| provider | 回调地址(生产) | 申请的 scope |
| --- | --- | --- |
| GitHub | `https://mosael.com/api/cloud/v1/oauth/github/callback` | `read:user user:email`(要读 `/user/emails` 的 `verified`) |
| Google | `https://mosael.com/api/cloud/v1/oauth/google/callback` | `openid email profile`(读 userinfo 的 `email_verified`) |

本地开发把域名换成 `http://localhost:3000` 即可(官网同源反代到 Cloud,与生产 Caddy 等价)。
