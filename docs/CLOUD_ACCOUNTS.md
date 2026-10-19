# MosaelCloud 账号与桌面端绑定(第一期)

这一期只做两件事:**MosaelCloud 有自己的一套账号**、**桌面端能把它绑到某个本地用户身上**。
分享、社区、同步、钱包、模型网关都不在这一期,也不预先加字段。

设计方向来自 [ADR 0039](adr/0039-mosael-cloud.md)(Cloud 是独立产品边界),但它当时设想的是
"重新接社区服务的设备授权";这一期按维护者的新方向改成**一套独立的 Cloud 账号**,不复用
`community/` 的数据库,也不把云端身份塞进本地 `backend/` 的 `users` 表。

## 两套身份

| | 本地 Mosael | MosaelCloud |
| --- | --- | --- |
| 谁在用 | 这台机器 / 这个部署 | 官网 + 桌面端绑定的云端账号 |
| 身份表 | `backend` 的 `users`(用户名 + 密码) | `cloud/` 的 `cloud_users`(邮箱 + 密码) |
| 登录 | 本地后端签的会话(`auth_sessions`) | Cloud 的 HttpOnly cookie(`cloud_sessions`) |
| 桌面端关系 | 本地账号照旧登录、照旧用 | 只是**附加**在某个本地用户上的一条绑定 |

**互不污染**:Cloud 不知道本地 `users` / `workspaces` / `auth_sessions`;本地 `users` 也不因为
绑定多一列。绑定关系只存在本地新表 `cloud_bindings` 里,指着"这个本地用户 ↔ 那个云端账号"。
两边的测试分别用两个真实 SQLite 文件钉住这条边界(见 `cloud/tests/test_identity_isolation.py`
与 `backend/tests/test_cloud_binding.py`)。

## 目录与部署形态

```
cloud/                      新的后端模块(FastAPI + SQLAlchemy),不属于 backend/
  src/cloud/                账号、会话、设备码、设备
  tests/                    SQLite 临时库,不连外网
website/                    官网:注册 / 登录 / 账号三页 + 同源反代
backend/                    本地后端:cloud_bindings 新表 + /api/cloud/binding/*
frontend/src/features/      桌面端设置页里的「绑定 MosaelCloud」入口
```

**为什么放 `cloud/` 而不是 `backend/`**:`backend/` 是跑在用户自己电脑上的本地服务端,它的
`users`、工作区、素材、插件都属于这台机器;MosaelCloud 是维护者部署的公网账号服务,数据库、
合规边界、发布节奏都不同。放进 `backend/` 会让"本地账号"和"云端账号"在同一个进程、同一个库
里长出互相引用的可能,而这正是这一期要避免的。也不并进 `community/`:社区服务是另一个产品
(工作流 / 插件市场 / 画板分享,ADR 0026),桌面端接入已被移除,和"账号 + 绑定"的最小面不一致。

### 本地开发

```bash
cd cloud
uv sync
CLOUD_COOKIE_SECURE=false CLOUD_PUBLIC_URL=http://localhost:3000 \
  uv run uvicorn cloud.main:app --host 127.0.0.1 --port 8901 --reload
```

官网 `pnpm dev`(:3000)的 `next.config.ts` 会把 `/api/cloud/v1/*` 同源反代到
`CLOUD_API_URL`(默认 `http://127.0.0.1:8901`)。本地后端要设 `MOSAEL_CLOUD_URL=
http://127.0.0.1:8901/api/cloud/v1` 才能发起绑定。

### 生产

Cloud 是一个独立进程:PostgreSQL(`CLOUD_DATABASE_URL=postgresql+psycopg://…`)、
`CLOUD_PUBLIC_URL=https://mosael.com`、`CLOUD_COOKIE_SECURE=true`。Caddy 把
`/api/cloud/*` 同源转给 Cloud,其余转给官网:

```
handle /api/cloud/* { reverse_proxy cloud:8000 }
handle              { reverse_proxy website:3000 }
```

**为什么同域反代而不是跨域 + CORS**:会话在 HttpOnly cookie 里,同源时它是第一方 cookie;
跨域就得 `SameSite=None`,把 CSRF 面放大,还要维护一份 CORS 白名单。同源之后 Cloud 只需要
认识官网这一个 Origin,浏览器端也没有任何 token 要存。CI 不启动 Cloud 服务,只跑它的 pytest。

**`CLOUD_PUBLIC_URL` 必须就是用户实际访问的那个 Origin**(例如用户从 `www.mosael.com` 进站,
这里也写 `https://www.mosael.com`)。它同时决定 cookie 的站点与写请求的同源校验;写错的表现
是"登录成功但一保存就说来自别的网站"。

## 接口(`/api/cloud/v1`)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/signup` | 邮箱 + 密码注册;**不自动登录** |
| POST | `/login` | 登录,Set-Cookie 会话 |
| POST | `/logout` | 撤销当前会话 |
| GET | `/me` | 当前云端账号 |
| DELETE | `/me` | 删号(会话 / 设备 / 设备码级联删除) |
| POST | `/device/code` | 桌面端取 `{device_code, user_code, expires_in, interval}` |
| POST | `/device/approve` | 已登录的官网确认 `{user_code}` |
| POST | `/device/token` | 桌面端轮询;未确认 428,确认后一次性发凭据 |
| GET | `/devices` | 这个账号绑定的设备(官网账号页) |
| DELETE | `/device/{id}` | 云端撤销某台设备 |
| GET | `/device/me` | Bearer 设备凭据认自己(给后续同步 / 分享留的接口) |

失败一律 `{error, message: {en, zh}}`;错误码稳定,文案中英各一份。

## 密码、会话、CSRF

- **密码**:`argon2-cffi` 的 `PasswordHasher`(argon2id),用库的缺省参数。没有自己写 KDF、
  没有明文、没有可逆加密。测试直接读库断言是 `$argon2id$…` 且能验回去、推不回明文。
- **会话**:256 位随机 token(`secrets.token_urlsafe(32)`),库里只存 sha256。cookie 是
  `HttpOnly; Secure(生产); SameSite=Lax; Path=/api/cloud/v1`。登出删这一行;过期在读取时
  即删。没有把 token 返回给 JS。
- **CSRF**:SameSite=Lax + 写请求的 Origin/Referer 同源校验 + `Sec-Fetch-Site: cross-site`
  直接拒绝。设备码两个入口(`/device/code`、`/device/token`)是给本机进程的,不走 cookie,
  因此不受这道闸约束。缺少 Origin 的非浏览器调用放行 —— 浏览器一定会带,缺头等于"不是浏览器"。
- **设备凭据**:这一期选**长期 opaque token**(随机 256 位、只存哈希、按人可撤销、删号即失效),
  而不是短期 access + refresh:桌面端这一期只需要"存下来",refresh 轮换要配一套客户端刷新
  逻辑,现在用不上。代价是它比短期令牌值钱,所以有撤销、有删号级联、且从不进渲染层 / 日志。

## 绑定完整时序

```
桌面端(渲染层)        本地后端(用户自己的)              MosaelCloud                官网(已登录)
 点「绑定」  ───────▶ POST /api/cloud/binding/start ──▶ POST /device/code
            ◀──────── {user_code, device_code, …} ◀──── {device_code, user_code, …}
 显示 user_code, 打开 verification_uri_complete ─────────────────────────▶ 账号页(带 ?user_code=)
                                                                          用户点「确认这台设备」
                                                               ◀────────── POST /device/approve
 点「我已确认」──────▶ POST /api/cloud/binding/complete ─▶ POST /device/token
            ◀──────── {status:"approved", email, device_id} ◀── 一次性凭据
                         本地只存 email / device_id / 加密后的 token
```

- 未确认时 Cloud 回 428 `authorization_pending`,本地接口回 `{status:"pending"}`。
- 过期 / 已用过分别回 410 `device_code_expired` / `device_code_used`;本地原样转述错误码。
- `device_code` 只交给渲染层用于回调 `complete`;它是短期轮询码,不是账号凭据。**云端 token
  从不经过渲染层**。
- 解绑:桌面端 `DELETE /api/cloud/binding` 只删本地行;撤销云端设备在官网账号页
  (`DELETE /device/{id}`)。两件事分开,是因为它们属于两份不同的数据。

## 本地新表与迁移

`backend/app/db/model_slices/cloud_binding.py`:

```
cloud_bindings(
  user_id PK → users.id ON DELETE CASCADE,
  cloud_user_id, email, device_id,
  token TEXT  ← core/secrets_at_rest.EncryptedText
  created_at
)
```

- 只**新增**表,旧表和旧列一行不动。
- 迁移步骤 `migrate-cloud-bindings-table`(`backend/app/db/migrations.py`,AFTER_SCHEMA)把新表
  记进迁移账本,并对已有库做 `checkfirst`;`Base.metadata` 的 create-all 照旧建新表。
- `token` 登记在 `core/secrets_at_rest.ENCRYPTED_COLUMNS`,棘轮测试保证它确实用了加密列。
- 本地账号删除时,`domain/members.delete_account` 按 schema 扫到 `cloud_bindings.user_id`
  并删掉;外键也写了 CASCADE。

## 不在这一期

分享、社区、feed、同步、钱包、模型网关、邮箱验证(字段 `email_verified_at` 已留,恒为 `null`)、
云端设备凭据的刷新轮换、桌面端用云端凭据调用任何业务接口。

## 只有真机能验 / 拿不准

- **真机**:系统浏览器打开 `verification_uri_complete`、桌面端在 Electron 里打开外部链接、
  真实 Postgres 上的 `create_all` 与并发设备码消费。CI 用 SQLite + TestClient。
- **拿不准**:长期设备 token 在"后续分享 / 同步"里是否够用;如果那时需要更细的权限,应该加
  作用域或改成 access + refresh,而不是把这一枚 token 直接当万能钥匙。邮箱验证要做时,注册
  流程与现有可能要补一步"未验证不能绑定"。
- **这一期没做**:登录 / 设备码的限速与人机验证、邮箱验证、找回密码。上线公网前至少要补
  "按 IP + 按账号的失败限速";`email_verified_at` 已经留好,但恒为 `null`。
- **语言**:`verification_uri` 固定指到 `/en/account`,中文用户需要自己在站内切到中文。
  设备码本身把 `user_code` 带在查询串里,登录后仍会预填。
