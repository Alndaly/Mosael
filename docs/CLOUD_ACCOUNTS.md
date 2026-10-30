# MosaelCloud 账号服务

**MosaelCloud 有自己的一套账号**:邮箱验证码注册、密码 / 验证码两种登录,以及
**GitHub / Google 登录**(见「GitHub / Google 登录」一节)。社区分享的第①笔(身份、分享、
点赞 / 收藏 / 评论)见「社区分享第①笔」。**桌面端不绑定云端账号** —— 没有设备码、没有设备
列表,也没有 `/api/cloud/binding*` 这一层;桌面端只经本地后端**只读反代**社区分享。
同步、钱包、模型网关不在这里,也不预先加字段。

设计方向来自 [ADR 0039](adr/0039-mosael-cloud.md)(Cloud 是独立产品边界),但它当时设想的是
"重新接社区服务的设备授权";这一期按维护者的新方向改成**一套独立的 Cloud 账号**,不复用
`community/` 的数据库,也不把云端身份塞进本地 `backend/` 的 `users` 表。

## 两套身份

| | 本地 Mosael | MosaelCloud |
| --- | --- | --- |
| 谁在用 | 这台机器 / 这个部署 | 官网 |
| 身份表 | `backend` 的 `users`(用户名 + 密码) | `cloud/` 的 `cloud_users`(邮箱 / 手机号 + 密码) |
| 登录 | 本地后端签的会话(`auth_sessions`) | Cloud 的 HttpOnly cookie(`cloud_sessions`) |
| 桌面端关系 | 本地账号照旧登录、照旧用 | 不绑定;社区分享的读请求经本地后端反代 |

**互不污染**:Cloud 不知道本地 `users` / `workspaces` / `auth_sessions`,本地库里也没有任何
指向 Cloud 账号的表。Cloud 的测试用两个真实 SQLite 文件钉住这条边界(见
`cloud/tests/test_identity_isolation.py`)。

## 目录与部署形态

```
cloud/                      新的后端模块(FastAPI + SQLAlchemy),不属于 backend/
  src/cloud/                账号、会话、OAuth、社区分享
  tests/                    SQLite 临时库,不连外网
website/                    官网:注册 / 登录 / 账号三页 + 同源反代
backend/                    本地后端:社区分享只读反代 /api/cloud/v1/shares/*
```

**为什么放 `cloud/` 而不是 `backend/`**:`backend/` 是跑在用户自己电脑上的本地服务端,它的
`users`、工作区、素材、插件都属于这台机器;MosaelCloud 是维护者部署的公网账号服务,数据库、
合规边界、发布节奏都不同。放进 `backend/` 会让"本地账号"和"云端账号"在同一个进程、同一个库
里长出互相引用的可能,而这正是这一期要避免的。也不并进 `community/`:社区服务是另一个产品
(工作流 / 插件市场 / 画板分享,ADR 0026),桌面端接入已被移除,和账号服务的最小面不一致。

### 本地开发

```bash
cd cloud
uv sync
CLOUD_COOKIE_SECURE=false CLOUD_PUBLIC_URL=http://localhost:3000 \
  uv run uvicorn cloud.main:app --host 127.0.0.1 --port 8901 --reload
```

官网 `pnpm dev`(:3000)的 `next.config.ts` 会把 `/api/cloud/v1/*` 同源反代到
`CLOUD_API_URL`(默认 `http://127.0.0.1:8901`)。

**本地后端接哪个 Cloud**(`MOSAEL_CLOUD_URL`,ADR 0088 §0):

| 设成 | 结果 |
| --- | --- |
| 不设(安装版就是这样) | 接官方的 `https://mosael.com/api/cloud/v1` |
| 一个地址 | 接这个 Cloud:开发时指向本机(`http://127.0.0.1:8901/api/cloud/v1`),团队自部署指向自己的 |
| 空串(`MOSAEL_CLOUD_URL=`) | 这个部署不接 Cloud(离线 / 内网);设置页说「这个部署关闭了 MosaelCloud,请联系部署管理员」 |

`/api/health` 的 `cloud` 字段报当前状态(`configured` / `cloud_not_configured` / `cloud_misconfigured`),只看配置、不出网;
打包冒烟要求它是 `configured`。界面上的提示只说找谁,**不教用户设环境变量** —— 那是部署管理员的事,写在这里。

**后缀 `/api/cloud/v1` 不能省。** 转发是按 `base + "/shares"` 这样拼的:少了后缀请求会打到站点根,
云端回 404 —— 表现为「登录完立刻被踢回登录页」,很难看出来。配错时 `require_configured()` 会直接
503 `cloud_misconfigured` 并说明要补什么。

本地同时跑官网和桌面端时,Cloud 那边用 `CLOUD_ALLOWED_ORIGINS` 把两个 Origin 都列上
(官网 `http://127.0.0.1:3000` / 桌面后端 `http://127.0.0.1:8901`),否则桌面端直连会被同源闸挡住。

### 生产

Cloud 是一个独立进程:PostgreSQL(`CLOUD_DATABASE_URL=postgresql+psycopg://…`)、
`CLOUD_PUBLIC_URL=https://mosael.com`、`CLOUD_COOKIE_SECURE=true`。目标机器上已有 nginx,
由它把 `/api/cloud/*` 同源转给回环端口上的 Cloud,其余转给官网:

```
location /api/cloud/ { proxy_pass http://127.0.0.1:8901; }
location /           { proxy_pass http://127.0.0.1:3000; }
```

完整 server 块在 `deploy/nginx/mosael.conf`。nginx 不读 `.env`,装的时候要把 `${DOMAIN}`
换成真实域名;反代必须带 `proxy_set_header Host $host;` 和
`proxy_set_header X-Forwarded-Proto $scheme;` —— 少了后者 Cloud 会以为请求走的是 http,
不下发 Secure cookie。

**为什么同域反代而不是跨域 + CORS**:会话在 HttpOnly cookie 里,同源时它是第一方 cookie;
跨域就得 `SameSite=None`,把 CSRF 面放大,还要维护一份 CORS 白名单。同源之后 Cloud 只需要
认识官网这一个 Origin,浏览器端也没有任何 token 要存。CI 不启动 Cloud 服务:`.github/workflows/tests.yml`
的 `cloud` job 只跑 `uv sync --frozen`、ruff 和 pytest(TestClient),不监听端口。

**`CLOUD_PUBLIC_URL` 必须就是用户实际访问的那个 Origin**(例如用户从 `www.mosael.com` 进站,
这里也写 `https://www.mosael.com`)。它同时决定 cookie 的站点与写请求的同源校验;写错的表现
是"登录成功但一保存就说来自别的网站"。

### 一键部署(Compose + 已有 nginx)

`deploy/` 有官网 + Cloud + Postgres + cleanup 的 Compose:Postgres 用命名卷,Cloud 等
Postgres healthy 才启动,另有 cleanup 容器定时删过期的验证码 / 会话 / OAuth 中间态。
**机器上已有 nginx,所以不装 Caddy**:compose 只把官网和 Cloud 绑在
`127.0.0.1:3000` / `127.0.0.1:8901`,80/443 由宿主 nginx 的
`deploy/nginx/mosael.conf` 接;同源仍是一个 `DOMAIN`,没有第二套域名。

```bash
cd deploy
cp .env.example .env      # 填 DOMAIN、POSTGRES_PASSWORD;要发信 / OAuth 再填对应项
docker compose up -d --build

# 接入已有 nginx(域名要和 .env 的 DOMAIN 一致)
cd ..
sudo cp deploy/nginx/mosael.conf /etc/nginx/conf.d/mosael.conf
sudo sed -i 's/${DOMAIN}/mosael.example.com/g' /etc/nginx/conf.d/mosael.conf
sudo nginx -t && sudo systemctl reload nginx

# 443 / 证书:certbot 会改 nginx,先备份
sudo cp -a /etc/nginx /root/nginx.bak
sudo certbot --nginx -d mosael.example.com
```

`CLOUD_PUBLIC_URL` 由 compose 按 `https://${DOMAIN}` 注入,`CLOUD_COOKIE_SECURE=true` 固定;
SMTP / OAuth 留空就是"没启用"(接口明确报错、官网不显示按钮),不要在 compose 里塞假值。
`DOMAIN` 必须与用户实际访问的 Origin 一致(含 `www` 的选择),也要与 nginx 里替换后的域名
一致。完整的首次部署清单、旧库 `password_hash` 迁移 SQL、过期清理、x86_64 / arm64 构建时的
`--platform` 说明与故障对照见 [`deploy/README.md`](../deploy/README.md)。

## 接口(`/api/cloud/v1`)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/signup/code` | 往邮箱发 6 位注册验证码;已注册的邮箱 409 |
| POST | `/signup` | 邮箱 + **验证码** + 密码注册,成功即 `email_verified_at`;**不自动登录** |
| POST | `/login` | 邮箱 + 密码登录,Set-Cookie 会话 |
| POST | `/login/phone` | 手机号 + 密码登录;短信账号设置密码后走这里 |
| POST | `/login/code` | 往邮箱发登录验证码;未注册邮箱也回同一句 `{"sent": true}` |
| POST | `/login/code/verify` | 邮箱 + 验证码换会话,cookie 与密码登录同一条路径 |
| POST | `/login/sms/code` | 往手机号发登录验证码 |
| POST | `/login/sms/verify` | 手机号 + 验证码换会话;首次验证自动建账号 |
| POST | `/logout` | 撤销当前会话 |
| GET | `/me` | 当前云端账号;`has_password` 表示是否设过密码 |
| POST | `/me/password` | 已登录时设置 / 修改密码;已有密码必须带 `current_password` |
| DELETE | `/me` | 删号(会话 / 身份 / 分享级联删除) |
| GET | `/oauth/providers` | 哪些第三方登录已配置: `{providers:{github:bool, google:bool}}` |
| GET | `/oauth/{provider}/start` | 生成 state / nonce / PKCE,302 到第三方;未配置 302 回官网报"没启用" |
| GET | `/oauth/{provider}/callback` | 校验 state + nonce,换 token、取身份,走现有 `open_session`;成功后 302 到 `/account` |
| POST | `/device-tokens` | 会话换一枚**设备令牌** `{token, secret}`;`secret`(`mct_…`)只在这一次响应里出现(ADR 0088) |
| GET | `/device-tokens` | 这个账号的设备令牌列表(名字、签发、最近使用;不含原文) |
| DELETE | `/device-tokens/{id}` | 吊销自己的一枚;别人的 / 不存在的一律 404 |
| GET | `/gateway/me` | **只认 `Authorization: Bearer mct_…`**,不认 cookie:这枚令牌属于谁、是哪台设备 |
| GET | `/gateway/account` | 只认设备令牌:这个用户的积分、下一批、套餐(ADR 0088,详见 cloud/README「官方中转网关」) |
| GET | `/gateway/v1/models` | 只认设备令牌:OpenAI 兼容的模型目录,价是积分 |
| POST | `/gateway/v1/chat/completions` | 只认设备令牌:OpenAI 兼容的对话,预占 → 转发 → 按用量结算 |
| GET | `/plans` | 在线能买的套餐与开着的支付渠道(ADR 0088 第 3 步,详见 cloud/README「在线购买」) |
| POST | `/orders` | 下单拿二维码(会话或设备令牌) |
| GET | `/orders`、`/orders/{id}` | 我的订单;读单个时还没到账就主动查单 |
| POST | `/payments/{alipay\|wechat}/notify` | 支付渠道的异步通知,靠验签认渠道 |
| DELETE | `/device-tokens/current` | **只认 Bearer**:令牌吊销自己(桌面端登出时用) |

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

**没有密码的账号怎么登录**:`/login/code`(邮箱验证码)对邮箱账号可用,`/login/sms/code`
(短信验证码)对手机号账号可用,所以第三方或短信建的账号随时能回来。登录之后可以走
`POST /me/password` **第一次设置密码**:没有 `password_hash` 时不要求当前密码,有密码时必须
验旧密码;只改密码,不踢掉当前会话。设置之后,邮箱账号走 `POST /login`,手机号账号走
`POST /login/phone`。还没有"忘记密码"流程,密码登录失败也还没有限速。

**入口**:官网在「我的 → 个人信息」的密码块;桌面端把 MosaelCloud 从「账户」页拆成独立的
「MosaelCloud 账号」设置页(本地账号的密码仍留在「账户」),两处都读 `has_password` 决定是否
显示「当前密码」。桌面端经本地后端 `POST /api/cloud/v1/me/password` 转发,不把云端密码写进
本地库;密码登录的输入框接受邮箱或手机号,后者转发到 `/api/cloud/v1/login/phone`。

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
  直接拒绝。浏览器的写接口走 cookie;桌面端走 `Authorization: Bearer` 设备令牌(见下一条),浏览器不会替跨站页面带上它,同源闸照旧对两条路都生效。缺少 Origin 的非浏览器调用
  放行 —— 浏览器一定会带,缺头等于"不是浏览器"。
- **设备令牌**(ADR 0088 第 1 步,表 `cloud_device_tokens`):桌面端登录拿到会话后,紧接着
  `POST /device-tokens` 换一枚 `mct_` + 256 位随机串的令牌,库里只存 sha256。**它不是 0004 拆掉的
  设备绑定**:没有设备码、没有官网确认配对 —— 换令牌和登录是同一次用户动作。令牌不过期,失效靠吊销
  (桌面端登出、`DELETE /device-tokens/{id}`、删号级联);`last_used_at` 按分钟粒度写。
  官方中转网关(`/gateway/*`)**只认这枚令牌**,浏览器会话在那里一律 401 `device_token_invalid`。
  账号接口(`api/deps.current_user`)两条路都认,但**一个请求只走一条**:带了 Bearer 就只认令牌,认不出直接
  `device_token_invalid`,不回头看 cookie。桌面端登录拿到会话 → 换令牌 → 立刻退掉那份会话,此后只拿令牌说话。
- **桌面端的「Mosael Cloud」连接**(ADR 0088):登录后本地建一条 vendor 为 `mosael-cloud` 的供应商连接,端点是
  `<MOSAEL_CLOUD_URL>/gateway/v1`、钥匙是上面那枚设备令牌(只存在 `cloud_login`,不进凭据表);模型清单与积分单价由
  `domain/cloud_connection.sync` 从网关目录对齐(登录时、设置页那一行点「刷新」时)。它对直连对话、智能体、画板、工作流
  就是一条普通的 OpenAI 兼容连接;用量账本里它的花费按「积分」单独记。

## 社区分享第①笔:身份、分享、互动

P1 的地基,接口契约由这一笔定死(逐条列在 `cloud/README.md` 的「社区分享接口」一节):

- **身份**加在 `cloud_users` 上:`display_name` / `handle` / `avatar_seed`,三列都可空;
  0006 另加 `official`(NOT NULL,默认 false,只由种子命令写,见下面「官方内容」) ——
  注册不填,第一次发布 / 评论才要求(缺 `display_name` → `409 identity_required`,文案是
  "先起个名字")。`handle` 唯一、只允许 `[a-z0-9_-]`、保留字(`admin` / `api` / `u` …)回 409;
  没显式给时自动生成 `member-xxxxxxxx`,之后可用 `PUT /me` 改。头像不存图片:只存短种子,
  P1 由前端算"昵称首字母 + 由种子决定的颜色"。
- **分享**表 `cloud_shares`:`owner_user_id` NOT NULL(没有匿名发布);`kind` 是
  `workflow` / `board` / `plugin`(0005 起);`locale` 是 `zh-CN` / `en-US`(0007 起,
  **NOT NULL**,发布时必填);`payload` 是 JSON(Postgres 上 JSONB),服务端只
  确认它是合法 JSON 并量 **2 MB** 上限(超过 → 413,不截断、不解析节点 / 画板结构);`status`
  只有 `listed` / `removed`。
- **互动**三表 `cloud_share_likes` / `cloud_share_favorites` / `cloud_share_comments`,每张都带
  `user_id`。点赞 / 收藏靠 `(share_id, user_id)` 主键去重:重复 POST 返回 204 且什么都不变,
  不是 409;DELETE 不存在的行也是 204。评论非空、有长度上限,空评论 422。
- **公开响应里只有** `display_name` / `handle` / `avatar_seed` + `official` 这份公开身份;
  email 不出现在任何公开列表 / 详情 / 评论 / 个人页。`payload` 只在
  `/shares/{id}/payload` 与 `/shares/{id}/download` 返回,列表和详情不返回(省流量)。评论存原文、
  响应是 JSON 纯文本,不做 markdown / HTML 渲染。
- **删除权限**:`DELETE /shares/{id}` 对非作者回 **404**(不是 403)—— 不区分"这个 id 不存在"
  与"这个 id 不是你的",已删除的分享也就不留下探测口;作者删除是软删(`status='removed'`),
  重复删除仍 204。删除评论同理,只有本人,别人 404。
- **注册即登录**:signup 与登录 / 验证码 / 第三方回调共用同一个 `open_session`,响应直接带
  会话 cookie,紧接着 `GET /me` 就是 200。
- **迁移**:`cloud/migrations/versions/0001_initial.py`(create_all 时代的基线)+
  `0002_identity_and_community.py`(身份三列 + 分享四表)、`0003_notifications.py`(通知表)、
  `0004_drop_device_binding.py`(拆掉设备绑定,删两张表)、`0005_shares_plugin_kind.py`
  (`kind` 的 CHECK 加上 `plugin`)、`0006_official_accounts_and_seed_slug.py`
  (`cloud_users.official` + `cloud_shares.slug` 去重键)、`0007_shares_locale.py`
  (`cloud_shares.locale` + 四列唯一键,**既有行回填 `zh-CN`**)。`cloud.app.create_app()` 启动时执行
  `alembic upgrade head`;表结构不再由 `create_all` 猜,已有库先用 `cloud.cli stamp 0001`。

## 官方内容 = 官方账号发布的分享

维护者裁决:插件和工作流本身就是分享,官方插件 / 官方工作流就是**官方账号发布的分享**。
因此官方内容不是第二套模型,只是同一张表里 `owner_user_id` 指向官方账号的行。

- **`plugin` 是 `kind` 的第三个取值**(0005 迁移改 CHECK)。发布、列表过滤、详情、payload、
  下载全部复用用户分享那套接口与 payload 形状;没有"官方 payload"分支,排序 / 游标 / 统计不分叉。
- **语言(0007)**:`cloud_shares.locale` NOT NULL,只许 `zh-CN` / `en-US`,发布时必填
  (`POST /shares` 缺 → 422,非法值 → `422 invalid_locale`);`GET /shares?locale=` 过滤,
  **不传 = 两种都返回**(不猜默认语言,否则英文内容会从列表里静默消失)。同一条官方内容的
  中英两行 **payload 相同**、标题 / 简介各取自己的语言;既有行由迁移回填 `zh-CN`。
- **`cloud_users.official`(0006)** 是公开标记:`public_user()` 带出 `official`,出现在列表 /
  详情 / 评论 / 通知的 `author` 里。`email` 仍然只出现在本人形状 `/me`。
- **只有部署脚本能造官方号**:注册模型没有 `official` 字段(pydantic 忽略多余键),`PUT /me`
  也不读它;唯一写入点是 `python -m cloud.cli seed-official`。测试直接钉住"注册请求里塞
  `official: true` 之后库里的值仍是 0"。
- **官方账号可以正常登录**:身份来自 `CLOUD_OFFICIAL_HANDLE` / `CLOUD_OFFICIAL_EMAIL`
  (有缺省,只在建号时用),密码来自 `CLOUD_OFFICIAL_PASSWORD`。原来的三道"登不上"的闸已拆:
  种子不再固定无密码、发码对官方号恢复投递、`open_session` 不再对 `official` 回 403,
  `/login` 也不再跳过官方号。**没设密码**时种子不动密码:新账号密码登录 **401**
  (`invalid_credentials`,不是 403,不暴露官方身份),不是启动错误;**密码短于
  `CLOUD_PASSWORD_MIN_LENGTH` 则配置构造即失败**,uvicorn / CLI 直接退出。
- **官方号没有登录后门**:验证码的 60 秒冷却、每邮箱 / 每 IP 每小时上限都照常生效;
  密码登录与普通账号同一条 `verify_password`。这一期仍然没有"密码登录失败限速"(见文末),
  但那是所有账号共同的状态,不是官方号的特权。
- **种子幂等键是 `(官方账号, kind, slug, locale)`**,slug 来自外部 bundle,存在
  `cloud_shares.slug`,四列唯一索引兜底。不用标题:标题会被运营改,按标题去重会在下次部署
  多出一条。**只补缺**:已存在的行整行跳过,不覆盖标题 / 简介 / payload;用户分享的 slug 为
  NULL,永远不会被碰到。**唯一例外是密码**,理由见 `cloud/src/cloud/official.py` 的注释。
  bundle 格式(每条 `slug` + `locales: {zh-CN: {title, summary?}, en-US: {...}}`)与样例见
  `cloud/README.md` 的「官方内容」一节;bundle 缺一种语言就只发一条,不编造另一种语言的标题。
- **回退**:`0005` 的 downgrade 把 CHECK 换回两个值;`0007` 的 downgrade 删 `locale` 并把
  唯一键换回三列。如果库里已经有 plugin 行 / 同一 slug 的两种语言,回退会**明确失败**
  而不是悄悄删数据;要回退先人工决定那些行怎么处理。

## 不在这一期

分享的后续(draft、审核 / 举报、头像上传、下载权限 / 付费)、feed、同步、钱包、模型网关、
找回密码、密码登录的失败限速 / 人机验证、第三方身份的列表 / 解绑 / 账号合并。设置 /
修改密码与 `has_password` 已在 `/me/password` 落地。

## 只有真机能验 / 拿不准

- **真机**:真实 Postgres 上的 Alembic 迁移、真实 SMTP 提供商的投递(SPF / DKIM /
  退信)、反代后面 `request.client.host` 是否拿到真实客户端 IP(uvicorn 需要开 proxy headers,
  否则每 IP 限流会退化成"每个代理一个桶")。CI 用 SQLite + TestClient,发信走注入的假 sender。
- **拿不准**:邮箱验证码目前每次
  重新签发,旧码在同一 purpose 下会被"最新一枚"覆盖逻辑间接作废,但没有显式批量失效;
  如果以后要支持「作废旧码」,再加一列或一条 UPDATE。SMTP 运行中故障时,注册过的邮箱会拿到
  `502`、未注册的仍是 `200` —— 这是「把失败说清楚」与「枚举防护」之间的取舍;正常运行时两者一致。
- **这一期没做**:密码登录的失败限速与人机验证、找回密码、验证码行的过期清理。上线公网前
  至少要补"按 IP + 按账号的失败限速"和一张清理任务;邮箱验证码本身的限流已经就位。
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
- **已有库升级**:`cloud_users.password_hash` 从 NOT NULL 改成可空,现在由迁移体系接管。
  `create_all` 时代建出来的旧库先 `python -m cloud.cli stamp 0001`,再让启动迁移升到 head;
  若旧库的 `password_hash` 仍是 NOT NULL,Postgres 还需
  `ALTER TABLE cloud_users ALTER COLUMN password_hash DROP NOT NULL;`。新库不做这一步。
- **拿不准(社区分享)**:`payload` 的 2 MB 是**紧凑 UTF-8 JSON 的字节数**,不是请求体大小;
  前端若带大量空白,请求体会略大,但存进去的内容仍按这个尺度判定。下载计数用一条自增 UPDATE,
  高并发下计数准确,但没有做防刷(同一账号可以反复下载加数);如果以后要做"一人一天算一次",
  应该加 `(share_id, user_id, day)` 的去重表,而不是在读取代码里猜。
