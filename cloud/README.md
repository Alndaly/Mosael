# MosaelCloud 账号服务

独立于本地 Mosael 的账号服务:邮箱 + 验证码 + 密码注册、密码 / 验证码两种登录、
**GitHub / Google 第三方登录(授权码 + PKCE)**、HttpOnly cookie 会话,
以及社区分享第①笔:**身份(昵称 / 短名 / 头像种子)+ 分享 + 点赞 / 收藏 / 评论**、
第②笔:**评论 / 点赞 / 收藏的通知**,第③笔:**官方内容 = 官方账号发布的分享**
(插件 / 工作流,`official` 公开标记 + `seed-official` 幂等种子命令),注册即登录。
第④笔:**分享记下语言(`zh-CN` / `en-US`)**,官方内容按语言各发一条;
**官方账号可以正常登录**,密码来自环境变量 `CLOUD_OFFICIAL_PASSWORD`。
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

**没配 `CLOUD_SMTP_HOST` 时邮件发码接口会明确回 `503 mail_not_configured`**,不会假装发出;
没配齐腾讯云短信五项时,手机验证码接口回 `503 sms_not_configured`。邮件与短信都使用
60 秒重发冷却。测试注入假 sender,不连外网。

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
`{display_name, handle, avatar_seed, official}` 这份公开身份,email 永不出现在公开响应里。**

```
GET    /me                        → {user} | 401
PUT    /me                        body {display_name?, handle?} → {user};冲突 409 / 校验 422
POST   /shares                    body {kind,locale,title,summary?,payload,license?} → {share} (201)
                                  kind 只能是 workflow|board|plugin(否则 422);
                                  locale 只能是 zh-CN|en-US(**必填**,缺 422 / 非法 422 invalid_locale);
                                  payload > 2 MB → 413
GET    /shares                    ?q=&kind=&locale=&sort=new|hot&limit=&cursor= → {items,next_cursor}
                                  locale 省略 = 不筛语言(两种都返回);非法值 422
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
GET    /notifications             ?limit=&cursor= → {items,next_cursor,unread}(需登录)
GET    /notifications/unread-count → {count}(需登录)
POST   /notifications/read        body {ids?} → {marked,unread};不传 ids = 全部标已读
```

`/me` 是**本人**形状:除公开身份外还带 `id` / `email` / `email_verified_at` / `created_at`
(只有本人看得到);公开列表 / 详情 / 评论里的 `author` 只有公开身份四列(含 `official`)。

`share` 的公开形状固定为
`{id,kind,locale,title,summary,bytes,license,created_at,author,stats,liked_by_me,favorited_by_me}`;
`stats = {downloads,likes,favorites,comments}`;游客的 `liked_by_me` / `favorited_by_me` 是 false。
`locale` 是**这一行标题 / 简介的语言**,不是 payload 的语言(同一条官方内容两种语言共用 payload)。
`payload` 只在 `/payload` 与 `/download` 单独取;详情 / payload / 下载不因 locale 改变行为。

**`locale` 必填、`GET /shares` 不传则返回全部**,两条都是刻意的:

- 发布时"自己的语言"来自**官网当前语言段**,应该由客户端明确声明;服务端给默认值会把英文内容
  悄悄标成中文(而且一旦落库就不可逆)。所以 `POST /shares` 缺 `locale` = 422。
- 列表不传 `locale` 时**两种语言都返回**,不替调用方猜一个默认值:猜成 `zh-CN` 会让英文内容
  从列表里静默消失。"没选语言"是调用方的真实状态,应该原样体现在结果里。

### 通知

互动(点赞 / 收藏 / 评论)会给**分享作者**留一条通知;自己对自己的分享不产生。
`GET /notifications` 只返回本人的,新序在前;`item =
{id,kind,read_at,created_at,actor:{display_name,handle,avatar_seed},share:{id,title,kind},comment_preview?}`。
`comment_preview` 是评论原文按字符截断到 120(不渲染 markdown、不做实体转义),只在评论通知里有。
`unread` / `unread-count` 都是**未读总数**,不是本页条数。

同一 `(收件人, 互动者, 分享, 类型)` 的**未读只留一条**:数据库里有一条
`(recipient_id, actor_id, share_id, kind) WHERE read_at IS NULL` 的部分唯一索引兜底,
所以同一个人反复点赞 / 取消 / 再点赞最多一条未读;已读之后的新互动才新开一行。
取消点赞 / 收藏删掉对应的**未读**通知(已读的留作历史);删评论按 `comment_id` 把通知一起删;
分享软删不删通知数据,读取时过滤掉。

`actor` 只有公开身份(含 `official`),**email 不出现在任何通知响应里**。

## 官方内容(官方账号发布的分享)

维护者裁决:**官方内容就是官方账号发布的分享**。插件和工作流本身就是分享,所以它们和用户分享
共用 `cloud_shares`、共用 `/shares` 读接口、共用同一套 payload 形状;没有第二张表、没有第二套
结构,列表的排序 / 游标 / 统计也不为官方内容分叉。

- `cloud_users.official`(NOT NULL,默认 false)是**公开信息**:公开响应里的 `author.official`
  (徽章用)。**只有部署脚本会写 true**;注册与 `PUT /me` 都不认这个字段(测试钉住"注册请求里塞
  `official: true` 没有用")—— 这条不变。
- 身份来自配置,有缺省:`handle=mosael`(`CLOUD_OFFICIAL_HANDLE`)、`display_name=Mosael 官方`、
  `email=official@mosael.example`(`CLOUD_OFFICIAL_EMAIL`,RFC 2606 保留域)。**handle / email
  只在建号时使用**;已存在的官方账号不会被种子改写(见下面的"只补缺")。
- **它可以正常登录**:官方账号是一个由部署方持有的运营账号,密码来自
  `CLOUD_OFFICIAL_PASSWORD`。原来的三道"官方登不上"的闸**已经拆掉**:
  1. 种子不再固定"不设密码"—— 设了环境变量就 `hash_password` 写进去;
  2. 发码接口对官方号**恢复正常投递**(邮箱由部署方配成真实拥有的地址,才收得到码);
  3. `open_session` 不再对 `official` 账号回 403,`/login` 也不再跳过官方号的密码校验。
- **没设密码时**:种子不动密码。新建的账号因此 `password_hash = NULL`,密码登录回 **401**
  (`invalid_credentials`,不是 403 —— 不在响应里暴露"这是官方号");这**不是启动错误**。
  如果账号之前设过密码、后来把环境变量删掉,旧密码保持不变(`没设就不动`)。
- **短密码是启动错误**:`CLOUD_OFFICIAL_PASSWORD` 短于 `CLOUD_PASSWORD_MIN_LENGTH` 时,
  `CloudConfig` 构造即失败 —— uvicorn 起不来 / CLI 以退出码 2 结束,不静默接受弱密码。
- **官方号没有登录后门**:验证码的 60 秒冷却、每邮箱 / 每 IP 每小时上限对它一样生效;
  密码登录与普通账号走同一条 `verify_password`。
- `kind=plugin` 与 `workflow` / `board` 并列;`POST /shares`、`GET /shares?kind=`、
  详情 / payload / 下载都认它,非法 kind 仍然 422。

### 种子命令

```bash
cd cloud
uv run python -m cloud.cli seed-official --bundle ./official-bundle.json
```

它先把库升到 head(和 uvicorn 启动同一条迁移路径),再按 bundle 补官方账号与分享。
**幂等键是 `(官方账号, kind, bundle 里的 slug, locale)`**,对应 0007 起
`cloud_shares` 上的唯一索引 `(owner_user_id, kind, slug, locale)`。

**同一条内容按语言各发一行**:`zh-CN` 一行、`en-US` 一行,两行 **payload 相同**,标题 / 简介
取各自语言。重复跑不新增。bundle 里**缺一种语言**(例如只有 `zh-CN`)时只发有的那一行 ——
**不编造英文标题 / 简介**。

为什么用 slug 而不是标题:标题是给人改的 —— 运营改一次标题,按标题去重就会在下一次部署
产出第二条;slug 是发布方在 Git 里维护的稳定标识。**只补缺**:按这个键已经存在的行整行跳过
(标题 / 简介 / payload / 许可都不动);用户自己的分享没有 slug,种子永远碰不到它们。
bundle 里改标题也不会回写已有行 —— 要更新内容请在库里改,或者换一个新 slug 重新发布;
已经被软删(`status='removed'`)的官方分享不会被下一次种子"复活",它按去重键仍算存在。

**唯一的例外是密码**:设了 `CLOUD_OFFICIAL_PASSWORD` 就每次种子都把它重新 hash 写回。
标题 / payload 是"内容",运营可能在库里手改过,所以要保留;密码是"凭据",它只有一个来源 ——
部署环境变量。不每次写回,运营改环境变量就永远改不了密码,轮换也无法完成。没设就不动密码。

bundle 是**外部输入**,cloud 不读仓库其它目录。格式:

```json
{
  "plugins": [
    {
      "slug": "mosael.official.example",
      "locales": {
        "zh-CN": {"title": "官方示例插件", "summary": "官方账号发布的示例插件。"},
        "en-US": {"title": "Official Example Plugin", "summary": "Published by the official account."}
      },
      "license": "MIT",
      "payload": {"version": 1, "manifest": {"id": "mosael.official.example"}, "files": []}
    }
  ],
  "workflows": [
    {
      "slug": "mosael.official.welcome",
      "locales": {
        "zh-CN": {"title": "官方入门工作流"},
        "en-US": {"title": "Official Welcome Workflow"}
      },
      "payload": {"version": 1, "nodes": [], "edges": []}
    }
  ]
}
```

- 顶层只有 `plugins` / `workflows` 两个数组;出现别的键整份拒绝。
- 每条必填 `slug`(小写字母 / 数字 / `.` `_` `-`,最长 80)、`locales` 与 `payload`;
  `license` 可选。`locales` 至少一种语言,键只能是 `zh-CN` / `en-US`;每种语言的
  `title` 必填、`summary` 可选。**标题 / 简介在 `locales` 里,不在条目顶层** ——
  旧格式(`locale` + 顶层 `title`)整份拒绝,不写"两种 bundle 都认"的兼容分支。
- 结构不对 → 退出码 2、stderr 说明原因、**一行都不写**(先整份校验,再建账号)。
- 同一个 `slug` 在同一个数组里只能出现一次;`plugins` 与 `workflows` 之间允许同名。

## 官方中转网关(ADR 0088 第 2 步)

桌面端登录后拿**设备令牌**(`Authorization: Bearer mct_…`)调网关;浏览器会话在这里一律不认。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/gateway/me` | 这枚令牌是谁、哪台设备 |
| GET | `/gateway/account` | 这个用户的积分(按批次、先到期在前)、下一批何时发、套餐 |
| GET | `/gateway/v1/models` | **OpenAI 兼容**的模型目录:启用 + 有生效单价 + 至少一条启用通道的模型;每个带 `name`、`max_output_tokens`、`pricing`(每 token 的价,字符串,`currency: CREDITS`) |
| POST | `/gateway/v1/chat/completions` | **OpenAI 兼容**的对话;`model` 是目录里的 id,`stream` 和 OpenAI 一样缺省为假 |

桌面端把它当一条 OpenAI 兼容连接用(base_url = `…/gateway/v1`、Bearer = 设备令牌),所以直连对话、智能体、画板、工作流
不另写一套。

**一次对话的积分**:输入按**字数**当 token、输出按 `max_tokens`(缺省为模型上限)预占,先扣快到期的那批;不够回 402,
`details` 里有 `needed` / `available` / `next_grant_at`。结束后按上游报的 `usage` 结算、多退;上游没报(或桌面端中途断开)
按字数估(两个字一个 token)。流照上游转回,每块的 `model` 换成网关的 id;**最后那块 usage**(`choices: []`)由网关结算后
给出 —— `usage` 是结算用的 token 数,多一格 `mosael`(`call_id`、`charged`、token 数、`usage_reported`、`credits_left`);
非流式回包同样多一格 `mosael`。响应头 `X-Mosael-Call-Id`。

**上游通道**:对上游说 OpenAI 兼容(`<base_url>/chat/completions`,流式时带 `stream_options.include_usage`)。按优先级试;
连不上 / 超时 / 429 / 5xx 把那条冷却 60 秒、换下一条 —— **只在上游开始生成之前换**,所以不会两条各收一次;其余 4xx 不换,
全额释放后原话(抹掉 Key)回给调用方。全都不行回 503 `upstream_unavailable`,不扣积分。

**账本**:`cloud_credit_batches` 只记一批发了多少、何时到期;每一笔进出是 `cloud_usage_entries` 里带符号的一行,余额是流水的和。
月度批次(一律从开通那一刻往后数第 N 个月,日子不漂)和到期清零在读余额 / 预占时按需补记,不需要定时任务。
每次调用一行 `cloud_gateway_calls`(预占、实扣、token、走的通道)。

**开通**(还没接支付,由维护者用命令行):

```bash
uv run python -m cloud.cli channel-key                     # 生成 CLOUD_CHANNEL_KEY,写进部署 .env
uv run python -m cloud.cli mfa-key                         # 生成 CLOUD_MFA_KEY(可选双因素)
uv run python -m cloud.cli admin-grant --email a@b.com     # 把已有账号设为 MosaelCloud 管理员
uv run python -m cloud.cli admin-list                      # 列出管理员
uv run python -m cloud.cli admin-revoke --email a@b.com    # 撤销(不能撤掉最后一名)
uv run python -m cloud.cli plan-set --slug pro --name Pro --period year --monthly-credits 20000 --credit-ttl-days 60
uv run python -m cloud.cli subscribe --email a@b.com --plan pro
uv run python -m cloud.cli model-set --id deepseek-chat --label "DeepSeek V3" --max-output-tokens 8000
uv run python -m cloud.cli price-set --model deepseek-chat --input-per-1k 2 --output-per-1k 8
CLOUD_UPSTREAM_KEY=sk-… uv run python -m cloud.cli channel-add --model deepseek-chat \
  --base-url https://api.deepseek.com/v1 --upstream-model deepseek-chat --priority 0
uv run python -m cloud.cli channel-list                    # 不显示 Key
uv run python -m cloud.cli balance --email a@b.com
```

上游 Key 不走命令行参数(会进 shell 历史):从 `CLOUD_UPSTREAM_KEY` 读,没有就在终端里问。

## 在线购买(ADR 0088 第 3 步,国内二维码预付)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/plans` | 在线能买的套餐(在售且标了价)和这个部署开了哪些支付渠道;公开读 |
| POST | `/orders` | `{plan, channel}` 下单,回二维码内容 `code_url`(30 分钟有效);浏览器会话、设备令牌都认 |
| GET | `/orders`、`/orders/{id}` | 我的订单。读单个订单时还没到账就主动问一次渠道(兜住丢了的回调),过期没付就关单 |
| POST | `/payments/{alipay\|wechat}/notify` | 渠道的异步通知。**不认人,靠验签认渠道**;回给渠道它要的那句(支付宝 `success`、微信 204) |

- **到账只有一个入口**:回调和查单都走 `domain/orders.settle_paid`,锁住订单行、幂等,一笔钱只发一次;金额必须和下单那一刻一致,
  对不上不发放、记在订单 `note`;关了之后才到的付款照样发放。
- **发放**:同一套餐在有效期内 → 顺延一个周期;另一个套餐 → 再开一个、和现有的同时生效。花钱买的什么都不作废。
- **渠道**(`cloud/payments/`):支付宝当面付(precreate / query / 异步通知,RSA2)、微信支付 Native(APIv3 签名、微信支付公钥验签、
  AES-GCM 解密、通知时间戳 5 分钟内)。配了商户凭据的才开;回调地址是 `<CLOUD_PUBLIC_URL>/api/cloud/v1/payments/<渠道>/notify`,
  部署要保证它公网可达。
- 套餐定价:`cloud.cli plan-set … --price 29`(元);不给 `--price` 就不在线卖,只能管理员开通。
- 测试(`tests/test_payments.py`)跑真的签名 / 验签 / 解密代码,只把网络换成假网关;**还没有用真商户号或沙箱联调过**。

## 测试

```bash
cd cloud
uv run pytest -q     # 每个用例一个临时 SQLite 库,不连外网
uv run ruff check
```

CI 的 `cloud` job([`.github/workflows/tests.yml`](../.github/workflows/tests.yml))跑的就是上面这两条,
root 的 `pnpm lint` 里也带着同一份 ruff。CI 不启动这个服务,也不连外网。OAuth 测试注入
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
- 社区分享第②笔(通知)的迁移是 `migrations/versions/0003_notifications.py`:
  新建 `cloud_share_notifications`(**不写旧数据回填**,新表从零张行开始)。
  升级就跑 `cd cloud && uv run python -m cloud.cli migrate`(或直接重启服务,启动时自动升到 head);
  它只建表,没有需要人工确认的兼容分支。
- 社区分享第③笔(官方内容)的迁移是 `0005_shares_plugin_kind.py`(`kind` 的 CHECK 加上
  `plugin`)+ `0006_official_accounts_and_seed_slug.py`(`cloud_users.official` 与
  `cloud_shares.slug` 去重键)。种子命令见下一节。
- **语言(0007,`0007_shares_locale.py`)**:`cloud_shares` 加 `locale`(NOT NULL,只许
  `zh-CN` / `en-US`),**既有行一律回填 `zh-CN`** —— 迁移当时没有语言信息可推断,只能这么定;
  种子唯一键同时扩成 `(owner_user_id, kind, slug, locale)`。downgrade 会删列并把唯一键换回
  三列;如果库里已经有同一 slug 的两种语言,回退会**明确失败**,需要先人工处理那些行。
- 登录仍是原来的规则:`cloud_users.password_hash` 可空(第三方登录建的账号没有密码);
  官方账号设了 `CLOUD_OFFICIAL_PASSWORD` 就有密码,和普通账号走同一条登录路径。

## 配置

| 环境变量 | 缺省 | 说明 |
| --- | --- | --- |
| `CLOUD_DATA_DIR` | `./cloud-data` | SQLite 与运行数据 |
| `CLOUD_DATABASE_URL` | 空 → 数据目录里的 SQLite | 生产用 Postgres |
| `CLOUD_PUBLIC_URL` | `http://localhost:3000` | 官网原点:同源校验与 OAuth 回调 |
| `CLOUD_COOKIE_SECURE` | `true` | 本地 http 开发设 `false` |
| `CLOUD_SESSION_TTL_DAYS` | `30` | 登录会话有效期 |
| `CLOUD_PASSWORD_MIN_LENGTH` | `8` | 密码下限 |
| `CLOUD_MFA_KEY` | 空(未启用 MFA) | TOTP secret 的 Fernet 加密钥;空时用户不能开启 MFA |
| `CLOUD_MFA_TICKET_TTL_SECONDS` | `300` | 登录第二步票据有效期 |
| `CLOUD_MFA_MAX_ATTEMPTS` | `5` | 一张票据最多错几次 |
| `CLOUD_SMTP_HOST` | 空(未配置发信) | 可写 `host:port`;空则发码接口 503 |
| `CLOUD_SMTP_PORT` | `587` | host 里没写端口时用它 |
| `CLOUD_SMTP_TLS` | 有用户名时 `starttls`,否则 `none` | `starttls` / `ssl` / `none` |
| `CLOUD_SMTP_USERNAME` | 空 | 有用户名才登录 |
| `CLOUD_SMTP_PASSWORD` | 空 | 只交给 SMTP,不进日志 |
| `CLOUD_SMTP_FROM` | `no-reply@mosael.com` | 发件人 |
| `CLOUD_TENCENT_SMS_SECRET_ID` / `_SECRET_KEY` | 空(未配置短信) | 腾讯云 CAM 子账号,只授短信发送权限 |
| `CLOUD_TENCENT_SMS_SDK_APP_ID` / `_SIGN_NAME` / `_TEMPLATE_ID` | 空(未配置短信) | 短信应用、签名、模板;模板只接受 `{1}`=验证码,参数个数必须与模板正文一致 |
| `CLOUD_TENCENT_SMS_REGION` | `ap-guangzhou` | 发送地域 |
| `CLOUD_GITHUB_CLIENT_ID` / `_SECRET` | 空(未启用) | GitHub OAuth App 凭据;空则入口报"没启用" |
| `CLOUD_GOOGLE_CLIENT_ID` / `_SECRET` | 空(未启用) | Google OAuth 客户端凭据;空则入口报"没启用" |
| `CLOUD_OAUTH_STATE_TTL_SECONDS` | `600` | 一次 OAuth 登录的 state / nonce 有效期 |
| `CLOUD_OFFICIAL_HANDLE` | `mosael` | 官方账号短名;**只在建号时使用**,已存在不改 |
| `CLOUD_OFFICIAL_EMAIL` | `official@mosael.example` | 官方账号邮箱;**只在建号时使用**;验证码登录要求它是真实拥有的地址 |
| `CLOUD_OFFICIAL_PASSWORD` | 空 | 官方账号密码。设了 → 每次种子都写回(轮换);空 → 不动密码(新号密码登录 401);短于 `CLOUD_PASSWORD_MIN_LENGTH` → 启动失败 |
| `CLOUD_CHANNEL_KEY` | 空(网关未配置) | 上游 API Key 的落库加密钥(Fernet,`cli channel-key` 生成);空则网关对话 503、加通道的命令拒绝 |
| `CLOUD_ALIPAY_APP_ID` / `_PRIVATE_KEY` / `_PUBLIC_KEY` | 空(不开) | 支付宝当面付:应用 id、**应用私钥**、**支付宝公钥**(RSA2;PEM 内容或 PEM 文件路径)。三项配齐才开 |
| `CLOUD_ALIPAY_GATEWAY` | `https://openapi.alipay.com/gateway.do` | 沙箱联调时换成沙箱网关 |
| `CLOUD_WECHATPAY_MCHID` / `_APPID` / `_SERIAL_NO` / `_PRIVATE_KEY` / `_APIV3_KEY` / `_PUBLIC_KEY` / `_PUBLIC_KEY_ID` | 空(不开) | 微信支付 Native(APIv3):商户号、AppID、商户证书序列号、商户私钥、APIv3 密钥(32 字节)、**微信支付公钥**与公钥 ID。七项配齐才开 |

### 第三方 OAuth 应用的填法

| provider | 回调地址(生产) | 申请的 scope |
| --- | --- | --- |
| GitHub | `https://mosael.com/api/cloud/v1/oauth/github/callback` | `read:user user:email`(要读 `/user/emails` 的 `verified`) |
| Google | `https://mosael.com/api/cloud/v1/oauth/google/callback` | `openid email profile`(读 userinfo 的 `email_verified`) |

本地开发把域名换成 `http://localhost:3000` 即可(官网同源反代到 Cloud,与生产 Caddy 等价)。
