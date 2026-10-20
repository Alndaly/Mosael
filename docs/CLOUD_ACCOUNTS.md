# MosaelCloud 账号与桌面端绑定

最初一期只做两件事:**MosaelCloud 有自己的一套账号**、**桌面端能把它绑到某个本地用户身上**。
这一版又补上了**邮箱验证码注册**与**验证码登录**(见「邮箱验证码与验证码登录」一节),
以及 **GitHub / Google 登录**(见「GitHub / Google 登录」一节)。
分享、社区、同步、钱包、模型网关都不在这里,也不预先加字段。

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
| POST | `/signup/code` | 往邮箱发 6 位注册验证码;已注册的邮箱 409 |
| POST | `/signup` | 邮箱 + **验证码** + 密码注册,成功即 `email_verified_at`;**不自动登录** |
| POST | `/login` | 密码登录,Set-Cookie 会话 |
| POST | `/login/code` | 往邮箱发登录验证码;未注册邮箱也回同一句 `{"sent": true}` |
| POST | `/login/code/verify` | 邮箱 + 验证码换会话,cookie 与密码登录同一条路径 |
| POST | `/logout` | 撤销当前会话 |
| GET | `/me` | 当前云端账号 |
| DELETE | `/me` | 删号(会话 / 设备 / 设备码级联删除) |
| POST | `/device/code` | 桌面端取 `{device_code, user_code, expires_in, interval}` |
| POST | `/device/approve` | 已登录的官网确认 `{user_code}` |
| POST | `/device/token` | 桌面端轮询;未确认 428,确认后一次性发凭据 |
| GET | `/devices` | 这个账号绑定的设备(官网账号页) |
| DELETE | `/device/{id}` | 云端撤销某台设备 |
| GET | `/device/me` | Bearer 设备凭据认自己(给后续同步 / 分享留的接口) |
| GET | `/oauth/providers` | 哪些第三方登录已配置: `{providers:{github:bool, google:bool}}` |
| GET | `/oauth/{provider}/start` | 生成 state / nonce / PKCE,302 到第三方;未配置 302 回官网报"没启用" |
| GET | `/oauth/{provider}/callback` | 校验 state + nonce,换 token、取身份,走现有 `open_session`;成功后 302 到 `/account` |

失败一律 `{error, message: {en, zh}}`;错误码稳定,文案中英各一份。OAuth 的浏览器入口例外:
它用 302 把用户送回官网的登录 / 注册页,错误码放在 `?oauth_error=` 里,官网再按当前语言显示
同一组中英文案。

## 邮箱验证码与验证码登录

注册从"邮箱 + 密码"改成"邮箱 + 验证码 + 密码":先 `POST /signup/code` 拿码,再带着码
`POST /signup`。登录则在同一条 `/login` 之外多两条:`/login/code` 发码、`/login/code/verify`
用码换会话。两种登录方式**共用 `cloud_sessions` 与那枚 HttpOnly cookie**,没有第二条鉴权路径。

### 表 `cloud_email_codes`

```
cloud_email_codes(
  id, email, purpose(signup|login), code_hash,   -- 只存 sha256,明文只进邮件
  attempts,                                      -- 验错次数
  request_ip,                                    -- 只为每 IP 限流;和码一起过期,不是身份
  created_at, expires_at, used_at
)
```

哈希把 `purpose:email:code` 一起拌进去,同一串数字在不同邮箱 / 用途下不是同一个摘要。
**6 位数字只有 100 万种,单靠哈希挡不住离线穷举** —— 真正的防线是 TTL、一次性、尝试上限和
重发限流,见下表的常量与理由。`request_ip` 目前没有清理任务,和码一样属于短期运维数据;
要长期保留时应单独做清理策略。

### 阈值(常量在 `cloud/src/cloud/email_codes.py`,理由随行注释)

| 常量 | 值 | 为什么 |
| --- | --- | --- |
| `CODE_TTL_SECONDS` | 600(10 分钟) | 够用户切到邮箱、等信到达;再长就是给暴力猜更多时间 |
| `CODE_MAX_ATTEMPTS` | 5 | 6 位码的在线命中概率从 1/1000000 压到 1/200000,到上限即作废 |
| `RESEND_COOLDOWN_SECONDS` | 60 | 同一邮箱 + 用途 60 秒内只能发一次,挡住连点与"轰炸收件箱" |
| `EMAIL_HOURLY_LIMIT` | 5 | 每邮箱每用途每小时 5 封;正常注册 / 登录用不到,超过就是想刷 |
| `IP_HOURLY_LIMIT` | 20 | 比单邮箱宽,因为同一个 NAT 后可能坐着多个人;真正挡单邮箱轰炸的是上一行 |

失败分类是明确的:`email_code_required` / `email_code_invalid` / `email_code_expired` /
`email_code_used` / `email_code_attempts_exhausted` / `email_code_cooldown` / `too_many_requests`,
每一种都有中英两份文案。

### 枚举防护

- `/login/code` 对**注册过和没注册过的邮箱回完全相同的响应**(`200 {"sent": true}`)。
  未注册邮箱也会落一行码占掉配额,所以冷却与限流行为也一致;只是不投递、永远用不了。
- `/login/code/verify` 对未知邮箱统一回 `email_code_invalid`,与"码错"不可区分。
- 注册用途对已注册邮箱回 `409 email_taken` —— 注册页本来就会在创建账号时告诉用户这件事,
  这不是新泄露面。

### 发信配置(`CLOUD_SMTP_*`)

| 环境变量 | 缺省 | 说明 |
| --- | --- | --- |
| `CLOUD_SMTP_HOST` | 空 | 空 = **没配置发信**,发码接口回 `503 mail_not_configured`,不假装成功 |
| `CLOUD_SMTP_PORT` | 587 | 也可以直接写在 host 里:`localhost:1025` |
| `CLOUD_SMTP_TLS` | 有用户名时 `starttls`,否则 `none` | `starttls`(587)/ `ssl`(465)/ `none`(本地 Mailpit) |
| `CLOUD_SMTP_USERNAME` / `CLOUD_SMTP_PASSWORD` | 空 | 有用户名才登录;密码不写日志 |
| `CLOUD_SMTP_FROM` | `no-reply@mosael.com` | 信封 / 头里的发件人 |

本地开发用 Mailpit,只填一个变量即可(无认证时 TLS 缺省就是 `none`):

```bash
CLOUD_SMTP_HOST=localhost:1025 \
CLOUD_COOKIE_SECURE=false \
CLOUD_PUBLIC_URL=http://localhost:3000 \
  uv run uvicorn cloud.main:app --host 127.0.0.1 --port 8901 --reload
```

没配置发信时,**注册过与没注册过的邮箱都回同一个 `503`** —— 否则「服务没配好」会变成账号探测器。
发信失败回 `502 email_send_failed`,并删掉那枚没送出去的码(否则它白占冷却和配额)。
**日志里不出现完整验证码**,邮箱也只写脱敏形式(`a***@example.com`);测试注入假 sender
断言"发给了谁、什么码",从不真发,也不连外网。测试里没有"开发环境跳过验证"的开关。

## GitHub / Google 登录

第三方登录只做 **OAuth 2.0 授权码 + PKCE(S256)**,不做隐式流:授权码只在服务端之间交换,
浏览器地址栏里从不出现 access token。`state` 一次性、绑定发起它的浏览器,换 token 时带
`code_verifier`;成功后**复用现有的 `open_session`**,没有第二条鉴权路径。

### 时序

```
浏览器                       MosaelCloud                         GitHub / Google
 GET /oauth/github/start ──▶ 生成 state / nonce / verifier,存库,
                             302 到 authorize ─────────────────▶ 用户授权
 ◀─────────────────────────────────────────────────────────────── 302 回 callback?code&state
 GET /callback?code&state ──▶ 校验 state + nonce + PKCE verifier,
                             换 token、取 userinfo ──────────────▶ token / userinfo
                             三条邮箱规则落到某个账号,open_session
 ◀── 302 /{locale}/account?oauth=created|existing
```

### 表 `cloud_identities`

```
cloud_identities(
  id,
  provider,                 -- github | google
  provider_user_id,         -- GitHub 数字 id / Google sub,一律按字符串存
  cloud_user_id FK → cloud_users.id ON DELETE CASCADE,
  created_at,
  UNIQUE(provider, provider_user_id)
)
```

唯一约束在**库上**,不只是应用层判断:同一个第三方账号只能指向一个 Cloud 账号。
反方向不唯一 —— 一个 MosaelCloud 账号可以绑多个第三方(测试里用 GitHub + Google 绑同一个
账号钉住)。表里不存 access token,也不存昵称 / 头像:这一期只需要"能认人"。

### 表 `cloud_oauth_states` 与一次性消费

```
cloud_oauth_states(
  state_hash PK,            -- 只存 sha256(state)
  provider, code_verifier,  -- verifier 换 token 要用明文,和 state 一起 10 分钟过期
  nonce_hash,               -- 只存 sha256(nonce)
  link_user_id,             -- 发起时已登录 = 绑到这个账号;空 = 登录 / 注册
  locale, return_page,      -- 失败时回到用户点按钮的那一页,并用哪种语言
  created_at, expires_at, used_at
)
```

- **state**:43 字符随机串,只出现在跳转 URL 里;库里存 sha256。回调按哈希查、检查
  provider 匹配、未过期、未使用,然后用一条
  `UPDATE … SET used_at = now() WHERE state_hash = ? AND used_at IS NULL` 原子消费;
  `rowcount != 1` 即拒绝。并发回调只有一个能拿到 verifier。
- **nonce**:同时写进发起请求的浏览器的一枚 `HttpOnly; SameSite=Lax; Path=/api/cloud/v1`
  短命 cookie,库里只存它的 sha256。回调必须把它带回来 —— 这一步把 state 绑到"发起登录的
  那个浏览器",挡住"攻击者拿自己的授权码骗受害者完成回调"的登录 CSRF。这一期不验 id_token,
  所以它不是 OIDC 的 nonce;若以后改成验 id_token,需要另加一枚真正的 OIDC nonce。
- **PKCE**:verifier 由 `secrets.token_urlsafe(64)` 生成(86 字符),challenge 是
  `base64url(sha256(verifier))` 去掉 padding。授权请求带 `code_challenge_method=S256`,
  换 token 时带 verifier;第三方校验失败会回 `invalid_grant` / `bad_verification_code`,
  我们映射成 `oauth_code_rejected`,**不把第三方的原始报错给用户**(只进日志)。
- **回调地址**:只由 `CLOUD_PUBLIC_URL` 推出,不看请求的 `Host` / `X-Forwarded-*`,因此天然与
  官网同源;`CLOUD_PUBLIC_URL` 写错时表现是第三方报 redirect_uri 不匹配。
- **短期数据**:state 行 10 分钟后失效,和验证码一样目前没有后台清理任务。用完的 state 行
  保留到下次清理(只有哈希与 verifier,没有身份信息)。

### 邮箱规则(只有三条路)

只认第三方**明确返回已验证**的邮箱:GitHub 读 `/user/emails`,取 `verified: true`(优先
`primary`);Google 读 userinfo 的 `email_verified: true`。没返回、或不是 true,一律拒绝并回
`oauth_email_unverified`,说清"第三方没有返回已验证的邮箱"。

| 情况 | 结果 | 重定向 |
| --- | --- | --- |
| 这个第三方 id 已经绑过 | 登录它指向的那个账号,**不新建** | `/account?oauth=existing` |
| 没绑过,但已验证邮箱已有 Cloud 账号 | **绑到已有账号**,不新建重复账号,旧密码不动 | `/account?oauth=existing` |
| 没绑过,邮箱也没有账号 | 新建账号:`email_verified_at` 写上、`password_hash` 为空,再写身份行 | `/account?oauth=created` |
| 已登录账号 A,试图绑一个已属于账号 B 的第三方 id | **冲突**,拒绝且不改任何一边 | 回登录页 `?oauth_error=oauth_identity_conflict` |
| 第三方 id 已属于账号 A,但它这次返回的已验证邮箱属于账号 B | **冲突**,不猜该登进谁 | 回登录页 `?oauth_error=oauth_identity_conflict` |

"发起登录时已登录"会被记进 `link_user_id`(见上表),回调把第三方身份绑到当前账号。这使
"一个账号绑多个第三方"可用,也是冲突规则真正会发生的地方;登录页 / 注册页不额外做一套
"连接账号"界面,绑定入口就是这两页的按钮。**没有做**身份列表、解绑、账号合并。

> 信任模型:把第三方"已验证邮箱"当成对该邮箱的控制权证明,并据此自动绑到已有 MosaelCloud
> 账号。这是行业常见做法,也是这次明确选择的行为;但它意味着安全性依赖 GitHub / Google 的
> 邮箱验证。我们只接这两家,不接任意 OIDC provider。

**没有密码的账号怎么登录**:今天的 `/login/code`(邮箱验证码)对它们可用,所以第三方建的
账号随时能回来。**产品还没有"找回密码 / 设置密码"接口**,因此它们暂时无法补一条密码登录;
要补的话应该加一条"已登录时设置密码"或"验证码换密码"的端点,而不是把空密码当成已知密码。

### 配置与"未启用"的表现

| 环境变量 | 缺省 | 说明 |
| --- | --- | --- |
| `CLOUD_GITHUB_CLIENT_ID` / `CLOUD_GITHUB_CLIENT_SECRET` | 空 | GitHub OAuth App;任一为空 = 没启用 |
| `CLOUD_GOOGLE_CLIENT_ID` / `CLOUD_GOOGLE_CLIENT_SECRET` | 空 | Google OAuth 客户端;任一为空 = 没启用 |
| `CLOUD_OAUTH_STATE_TTL_SECONDS` | `600` | state / nonce / verifier 的有效期 |

凭据**只从环境变量读**,代码和仓库里没有任何真实值。没配置时:

- `GET /oauth/providers` 对应项是 `false`;
- `GET /oauth/{provider}/start` **302 回官网**并带 `oauth_error=oauth_not_configured`,
  不会假装能跳第三方;
- 官网拿到 `false` 就**不渲染那颗按钮**(连分隔线也不占位)。

用户要在 GitHub / Google 控制台填的回调地址(逐字,**必须与 `CLOUD_PUBLIC_URL` 同源**):

```
https://mosael.com/api/cloud/v1/oauth/github/callback
https://mosael.com/api/cloud/v1/oauth/google/callback
```

本地开发把 `https://mosael.com` 换成 `http://localhost:3000`。scope 分别是
`read:user user:email` 与 `openid email profile`。

### 失败码

| 错误码 | 什么时候 |
| --- | --- |
| `oauth_not_configured` | 这个 provider 没配 client id / secret |
| `oauth_state_invalid` | state 不存在 / provider 对不上 / 过期 / 已用 / nonce cookie 对不上 |
| `oauth_callback_invalid` | 回调里没有授权码 |
| `oauth_denied` | 用户在第三方点了取消(`error=access_denied`) |
| `oauth_code_rejected` | 换 token 被拒:授权码无效、过期、PKCE 校验失败 |
| `oauth_email_unverified` | 第三方没有返回已验证邮箱,或返回的邮箱不合法 |
| `oauth_identity_conflict` | 这个第三方 id 已绑到另一个账号,和当前登录账号 / 已验证邮箱的归属对不上 |
| `oauth_provider_error` | 第三方网络 / 5xx / 响应格式不对 |

每一种都有中英两份文案;provider 的原始 `error_description` 只写日志,不进响应。

### 官网界面

- 登录页、注册页在表单下方、一条"或"分隔线之下各放两颗按钮(GitHub / Google);
  沿用账号表单那套(`form-controls.tsx` 的字号 / 圆角 / 聚焦环 + `ui/button.tsx` 的
  `Button variant="outline"`),**没有新皮肤**。
- 按钮是原生 `<a>`(经 `Button asChild`),键盘、回车、新窗口都按普通链接走;点击后切换成
  "正在前往…"并置 `aria-busy`。图标沿用站里的 `icons.tsx`(`GithubMark` + 新增的
  `GoogleMark`),不引新依赖。
- 是否渲染由 Cloud 的 `/oauth/providers` 决定,官网不重复维护一份构建期开关;请求失败按
  "没启用"处理。失败原因从 `?oauth_error=` 读回来,用现有 `FormAlert` 显示;成功回到账号页,
  用 `?oauth=created|existing` 说明"新建了账号"还是"绑到了已有账号"。

### 测试

`cloud/tests/test_oauth.py` 注入 `FakeOAuthProvider`(和发信注入假 sender 同一个套路),
它像真 provider 一样校验 **PKCE 与 redirect_uri**,但**绝不连 GitHub / Google**。覆盖:
code → token → userinfo → 会话全链路、state 不匹配 / 重放 / 缺 nonce、PKCE 失败、
`email_verified=false` / 没邮箱、邮箱已存在 → 绑旧账号且不新建、已登录绑定另一 provider、
同一第三方 id 绑到别的账号 → 冲突、未配置 → 明确报"没启用"、用户取消、缺 code、
provider 报错不外泄原始信息、唯一约束在库上。官网侧另有
`website/test/oauth-login.test.mjs` 钉住"未配置不渲染"、分隔线、键盘可达、loading / 失败态
与中英文案。

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

分享、社区、feed、同步、钱包、模型网关、找回密码 / 设置密码、密码登录的失败限速 / 人机验证、
云端设备凭据的刷新轮换、桌面端用云端凭据调用任何业务接口、第三方身份的列表 / 解绑 / 账号合并。

## 只有真机能验 / 拿不准

- **真机**:系统浏览器打开 `verification_uri_complete`、桌面端在 Electron 里打开外部链接、
  真实 Postgres 上的 `create_all` 与并发设备码消费、真实 SMTP 提供商的投递(SPF / DKIM /
  退信)、反代后面 `request.client.host` 是否拿到真实客户端 IP(uvicorn 需要开 proxy headers,
  否则每 IP 限流会退化成"每个代理一个桶")。CI 用 SQLite + TestClient,发信走注入的假 sender。
- **拿不准**:长期设备 token 在"后续分享 / 同步"里是否够用;如果那时需要更细的权限,应该加
  作用域或改成 access + refresh,而不是把这一枚 token 直接当万能钥匙。邮箱验证码目前每次
  重新签发,旧码在同一 purpose 下会被"最新一枚"覆盖逻辑间接作废,但没有显式批量失效;
  如果以后要支持「作废旧码」,再加一列或一条 UPDATE。SMTP 运行中故障时,注册过的邮箱会拿到
  `502`、未注册的仍是 `200` —— 这是「把失败说清楚」与「枚举防护」之间的取舍;正常运行时两者一致。
- **这一期没做**:密码登录的失败限速与人机验证、找回密码、验证码行的过期清理。上线公网前
  至少要补"按 IP + 按账号的失败限速"和一张清理任务;邮箱验证码本身的限流已经就位。
- **语言**:`verification_uri` 固定指到 `/en/account`,中文用户需要自己在站内切到中文。
  设备码本身把 `user_code` 带在查询串里,登录后仍会预填。
- **第三方登录只有真机能验**:GitHub / Google 控制台里的回调地址与 scope、真实授权页与
  同意页、HTTPS 下 `SameSite=Lax` cookie 能否随"第三方 → 我们的回调"这次顶层跳转带回来、
  邮件是否在第三方那边已验证、以及 `CLOUD_PUBLIC_URL` 与实际访问 Origin 不一致时的报错。
  CI 只走注入的假 provider,不连外网。
- **拿不准(GitHub PKCE)**:GitHub OAuth App 对 `code_challenge` / `code_verifier` 的支持
  要在真实应用上确认(Google 明确支持)。若某个 GitHub 应用忽略 verifier,授权码流程仍然
  成立,但 PKCE 那层保护不会生效 —— 这时应确认应用类型 / 文档,而不是删掉本地的 PKCE。
- **拿不准**:`cloud_oauth_states` 目前和 `cloud_email_codes` 一样没有清理任务;数据量小、
  行里只有哈希与短期 verifier,但公网长期运行前应补一条定时清理。是否允许一个账号绑多个
  **同一 provider** 的身份也没有产品约束:库允许,登录按第三方 id 解析,不做限制;若产品
  要求"一家一个",应在绑定时加应用层检查,而不是把唯一约束改成 `(provider, cloud_user_id)`。
- **已有库升级**:`cloud_users.password_hash` 从 NOT NULL 改成可空,`create_all` 不会改已有列。
  Postgres 需 `ALTER TABLE cloud_users ALTER COLUMN password_hash DROP NOT NULL;`;SQLite 开发库
  删掉重建;线上有真实数据时应写显式迁移。
