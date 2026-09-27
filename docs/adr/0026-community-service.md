# ADR 0026:社区服务 —— 账号、提交、画板分享

## Status

Accepted — 2026-09-27。按阶段落地,部署由维护者按 [docs/DEPLOY_COMMUNITY.md](../DEPLOY_COMMUNITY.md) 进行。

## Context

维护者要求(2026-09-27):官网要有社区 ——

- 能注册、登录账号:**手机号 + 短信验证码**(腾讯云短信)和**账号密码**两种,token 要能自动刷新;
- 用户能**真实提交**工作流和插件;
- 补一些可视化;
- 桌面应用里的无限画布能**一键分享成一个链接**,别人在浏览器里就能看(参考 TapNow)。

现状:

- 官网(`website/`,Next.js 16)构建时静态生成全站。插件页、工作流页读的是仓库里的静态索引
  (`public/plugins/registry.json`、`public/workflows/catalog.json`),内容只来自维护者提交的代码。
- 应用里的插件市场读发版产物里的 `registry.json`;「工作流社区」读的是后端内置模板。
- 应用里的「共享」只在工作区内部(`domain/sharing.py`),没有对外链接。
- 没有任何服务器端组件:账号、提交、分享都需要一个真正在跑的服务和数据库。

## Decision

### 1. 一个独立的社区服务 `community/`,和桌面后端分开部署

- **FastAPI + SQLAlchemy 2 + PostgreSQL + Alembic**,`uv` 管理,和 `backend/` 同一套工具链(ruff、pytest)。
  不复用桌面后端的进程:桌面后端跑在每个用户自己的机器上,社区服务只有一份,在维护者的服务器上。
  [ADR 0001](0001-no-network-microservices.md) 说的是**应用内部**不拆微服务;社区是另一个产品边界。
- 数据形状的变化一律走 Alembic 迁移,不写兼容分支([ADR 0006](0006-migrate-instead-of-branching.md))。
- **和桌面应用共用格式校验,不抄第二份。** 插件包清单、工作流文件的校验规则只在一处:从
  `backend/app/domain/plugins/manifest.py` 与工作流导入那一段里抽出**不依赖桌面运行时**的纯模块
  (放在 `packages/mosael-formats/`,两边都依赖它)。社区服务收到的包,和用户点「从文件安装」时过的是
  同一套规则 —— 社区上能上架的,装得上;装不上的,上不了架。
- 同源部署:`https://<站点>/api/community/*` 反代到社区服务,官网和 API 同一个域名 —— 刷新 token 的 cookie
  是第一方的,不涉及跨站 cookie。部署形态是一份 docker compose:反代(Caddy,自动 HTTPS)、官网(Next.js
  standalone)、社区服务、PostgreSQL,对象存储可选。

### 2. 账号

`users`:`id`、`handle`(公开的用户名,唯一)、`display_name`、`avatar_key`、`phone`(E.164,唯一,可空)、
`password_hash`(argon2id,可空)、`role`(`user` / `moderator` / `admin`)、`status`(`active` / `banned`)、时间戳。

- **手机号 + 验证码**:第一次用这个号码登录即注册(随后可设密码)。验证码 6 位,5 分钟有效,**只存哈希**,
  一个码最多试 5 次;同一号码 60 秒内不重发、每天至多 10 条;同一 IP 每小时至多 20 条。发送前可选**腾讯云
  验证码(天御)**校验,防短信轰炸 —— 部署时配了就启用。发短信经腾讯云短信 `SendSms`(签名、模板 ID、
  SdkAppId、SecretId/Key 全走环境变量,仓库里一个都不出现)。开发环境用 `console` 发送器,码打到日志。
- **账号密码**:用户名或手机号 + 密码登录;注册账号密码必须绑定一个验证过的手机号(防批量注册,也是找回
  密码的唯一途径)。连续失败按账号和 IP 两个维度限速。
- **找回密码**:手机验证码 → 设新密码 → 吊销这个人的全部刷新 token。
- 登录、注册、找回页上有《用户协议》《隐私政策》勾选(国内上线要求);两份文本由维护者提供,服务里只存版本号和
  同意时间。

### 3. Token:短命的访问令牌 + 轮换的刷新令牌

- **访问令牌**:JWT(EdDSA,密钥由环境变量给),15 分钟,载荷只有 `sub`(用户 id)、`sid`(会话 id)、`role`。
- **刷新令牌**:256 位随机串,**库里只存哈希**,属于一个会话(`sessions`:设备名、IP、UA、创建 / 最后使用时间)。
  **每用一次就换一个新的**(轮换);已经换掉的旧令牌再被拿来用 → 视为被盗,**整个会话吊销**。滑动 30 天、
  绝对上限 90 天。为了几个并发请求同时刷新时不误伤,旧令牌在被换掉后的 **20 秒宽限期**内再用,返回同一对新令牌。
- **网页**:刷新令牌放在 `HttpOnly; Secure; SameSite=Lax; Path=/api/community/v1/auth` 的 cookie 里(路径必须是刷新接口的
    前缀,否则浏览器不会带上它;最初写成 `/api/community/auth` 是错的,实现时改正),脚本拿不到;
  访问令牌只在内存里。前端一个请求封装:
  - 到期前 60 秒**主动刷新**;
  - 收到 401 时**只刷新一次**(同一时刻只有一个刷新在飞,其余请求等它),成功后重放原请求一次,失败就回到登录;
  - 多个标签页之间用 `BroadcastChannel` 通告「刷新好了 / 退出了」,不各刷各的。
  - 刷新接口额外要求 `X-Requested-With` 头,配合 SameSite 防 CSRF。
- **桌面应用**:走**设备授权**(RFC 8628):应用要一个设备码 → 打开浏览器到 `/{locale}/device?code=XXXX-XXXX` →
  用户在网页上登录、确认「允许这台 Mosael 访问你的社区账号」→ 应用轮询拿到一对令牌。刷新令牌存在桌面后端现有的
  加密凭据存储里(和服务商密钥同一处),同样轮换、同样的刷新规则。应用里可以看到、也可以在网页「设备」页里吊销。

### 4. 提交工作流与插件

- **工作流**:上传应用导出的 `.mosael-workflow.json`,服务端过同一套校验;标题、简介、封面图、标签由作者填。
  **发布即上架**(是数据,不在别人机器上执行代码;含「运行代码」节点的,详情页醒目标出)。
- **插件**:上传插件 zip(和「从文件安装」同一种包),服务端过同一套校验(清单、权限声明、无符号链接、无路径穿越、
  大小上限)。**先进审核队列**,由 `moderator` 以上角色通过后才公开 —— 插件会在别人的电脑上运行代码。
  审核界面并排显示清单、权限、文件列表与上一版的差异。
- 每一项有**版本**(同一作者再提交同一 id 即新版本);插件的 id 由第一个提交者占有,别人不能用同一个 id 发版。
- 社区数据:浏览数、下载数(按天聚合)、点赞;举报 → 进审核队列,`moderator` 可以下架。
- 现有的官方条目(静态索引里那些)迁移成一个 `official` 作者名下的条目,官网列表把「官方」和「社区」分开标。
- 应用里的插件市场默认索引**不变**(发版产物里的 `registry.json`,见 [RELEASING](../RELEASING.md)):社区上的插件
  在应用里单列一个「社区」来源,读社区服务的 `/plugins` 接口,装之前照旧弹权限确认。

### 5. 画板分享

- 应用里画板工具栏上「分享」:把这张画板做成一份**快照**上传,拿回一个短链接 `/{locale}/b/<slug>`。
- 快照 = 画布的格子与连线(去掉运行态、任务 id、连接 id 这类本机事实)+ 格子引用的媒体文件 + 文档格钉住那一版的
  正文 + 3D 场景格的预览图。**不带**提示词以外的生成参数里的密钥、不带本机路径。
- 快照不可变;再分享同一张画板**沿用同一个链接**,发一个新版本。主人可以撤回(链接立即 410)、设可见性
  (`unlisted` 默认:知道链接才能看;`public`:出现在作者主页和「画板」列表里)。
- 查看页是**只读画布**:能平移、缩放、点开看大图 / 播放视频音频、读文档格全文;有 Open Graph 预览图(第一次访问时
  由服务端从快照生成)。
- 限额(可配置):每张快照 300 格、单文件 200 MB、总计 1 GB;每个用户总存储 5 GB。
- 上传走「先要上传地址 → 逐个文件 PUT → 提交快照」三步,文件按内容哈希去重,断了能续。

### 6. 存储

媒体、插件包、工作流文件、头像都放对象存储,一个接口两种实现:

- `local`:服务器磁盘上的一个卷,由反代直接出文件(默认,单机部署最简单);
- `s3`:S3 兼容接口,腾讯云 COS、阿里云 OSS、MinIO、AWS S3 都走它(`endpoint`、`bucket`、密钥全走环境变量)。

用户上传的东西**一律不当网页内联出**:下载型文件带 `Content-Disposition: attachment`,全站 `nosniff`,
分享查看页有严格的 CSP。

### 7. 可视化

- **社区统计页**:注册用户、工作流 / 插件数、下载与分享的逐日趋势,热门条目。
- **条目详情**:下载量的 30 天走势;工作流详情画出它的**节点图**(从工作流文件直接画,只读)。
- **作者主页**:TA 的工作流、插件、公开画板,和逐日贡献热力图。

### 8. 官网的形态

- 文档、下载、更新日志仍然**构建时静态生成**,不依赖社区服务 —— 服务挂了,文档照常。
- 社区相关页面(插件、工作流、画板、作者、统计、登录、我的)在**请求时渲染**,读社区服务。没配社区服务地址
  (`COMMUNITY_API_URL` 为空,本地只看文档时)这些页面显示「社区未开放」,不回退到静态索引 —— 静态索引迁进数据库
  之后就不再是社区内容的来源。

## API 约定(v1,前缀 `/api/community/v1`)

所有响应 JSON;错误统一 `{"error": {"code": "…", "message": "…"}}`,`message` 按 `Accept-Language` 给中文或英文。
列表一律游标分页:`?cursor=…&limit=…`,回 `{"items": […], "next_cursor": "…" | null}`。

**认证**(`/auth`)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/sms/send` | `{phone, purpose: "login"\|"bind"\|"reset", captcha?}` → 204;限速见上 |
| POST | `/auth/sms/login` | `{phone, code, agree_terms_version}` → 登录(首次即注册) |
| POST | `/auth/register` | `{handle, password, phone, code, agree_terms_version}` → 登录 |
| POST | `/auth/password/login` | `{login: handle 或 phone, password}` → 登录 |
| POST | `/auth/password/reset` | `{phone, code, new_password}` → 204,吊销全部会话 |
| POST | `/auth/refresh` | 网页:cookie;应用:`{refresh_token}` → 新一对令牌 |
| POST | `/auth/logout` | 吊销当前会话 |
| POST | `/auth/device/code` | `{client_name}` → `{device_code, user_code, verification_uri, expires_in, interval}` |
| POST | `/auth/device/token` | `{device_code}` → 未确认 `428 authorization_pending` / 轮询过快 `429 slow_down`(间隔 +5 秒)/ 被拒 `403` / 重复兑换 `400` / 过期 `410` / 成功令牌对 |
| POST | `/auth/device/approve` | 登录后:`{user_code}` → 204 |

「登录」的回包:`{access_token, expires_in, user}`;网页的刷新令牌只在 `Set-Cookie` 里,应用(设备授权、
`refresh` 带 body 的那种)在 body 里多一个 `refresh_token`。

**我**(`/me`):`GET /me`、`PATCH /me`(昵称、头像、handle 一次)、`POST /me/password`、`GET /me/sessions`、
`DELETE /me/sessions/{id}`、`GET /me/submissions`(含审核状态)。

**工作流**:`GET /workflows`(`?q&tag&sort=trending|new|downloads&author`)、`GET /workflows/{slug}`、
`GET /workflows/{slug}/versions`、`POST /workflows`(multipart:文件 + 元数据)、`POST /workflows/{slug}/versions`、
`GET /workflows/{slug}/download`(计数后 302 到文件)、`POST|DELETE /workflows/{slug}/like`。

**插件**:同工作流的形状,路径换成 `/plugins`,提交后状态 `pending`;`GET /plugins/index.json` 给应用读,
字段与发版产物 `registry.json` 相同。

**画板分享**:

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/shares/uploads` | `{files: [{sha256, size, content_type}]}` → `{uploads: [{sha256, url, method, headers, expires_in}], skipped: [sha256…]}`;不在白名单里的类型 422 |
| PUT | 上传地址 | 文件本体(`local` 存储时是服务自己的地址,`s3` 时是预签名 URL) |
| POST | `/shares` | `{board_key, title, visibility, snapshot}` → `{slug, url, version}`;同一个 `board_key` 再发 = 新版本 |
| GET | `/shares/{slug}` | 当前版本的快照(公开 / 不公开但知道链接) |
| PATCH | `/shares/{slug}` | 标题、可见性 |
| DELETE | `/shares/{slug}` | 撤回 |
| GET | `/me/shares` | 我分享出去的 |

`board_key` 是应用在本机为这张画板生成、存在画板上的一个随机 id —— 服务端据此认出「同一张画板的新版本」,
不需要知道本机的画板 id。

**快照格式**(`snapshot`,`schema: "mosael.board-snapshot/1"`):

```jsonc
{
  "schema": "mosael.board-snapshot/1",
  "viewport": {"x": 0, "y": 0, "zoom": 1},
  "items": [
    // 与本机画布的格子同形,去掉 run / form 里的运行态与连接;媒体引用换成文件哈希
    {"id": "i1", "kind": "image", "x": 0, "y": 0, "width": 260, "height": 180, "title": "…",
     "media": {"sha256": "…", "content_type": "image/png", "width": 1024, "height": 1024, "thumb_sha256": "…"}},
    {"id": "n1", "kind": "note", "x": 300, "y": 0, "width": 220, "height": 140, "text": "…", "color": "yellow"},
    {"id": "d1", "kind": "document", "title": "…", "markdown": "…(钉住那一版的正文)", "revision": 13}
  ],
  "edges": [{"id": "e1", "source": "n1", "target": "i1"}]
}
```

**实现时补上的接口**(官网和应用都在用):`GET /auth/config`(协议版本、验证码 AppId)、
`POST /{workflows|plugins|shares}/{slug}/report`、`GET /shares?author&cursor`(公开画板)、`GET /shares/{slug}/og.png`、
`POST /admin/reports/{id}/dismiss`、`PUT /uploads/{sha256}`(`local` 存储的签名上传地址)。`/plugins/index.json` 缺省只含
社区条目(`channel: "community"`),`?include=official` 才带官方的。`new`、`new-version`、`index.json` 是保留 slug。

**统计**:`GET /stats/overview`、`GET /stats/timeseries?metric=…&days=…`、`GET /users/{handle}`(公开主页)。

**管理**(`moderator`+):`GET /admin/queue`、`POST /admin/submissions/{id}/approve|reject`、
`POST /admin/items/{kind}/{slug}/hide`、`GET /admin/reports`。

## 分阶段

1. 社区服务骨架、账号与令牌(短信、密码、刷新轮换、设备授权)、部署文档与 compose;官网登录注册页、会话封装。
2. 工作流与插件的提交、审核、列表与详情;官方条目迁移;统计与可视化。
3. 画板分享:应用侧快照与上传、服务端存储、官网只读查看页与分享预览图。
4. 应用接入:社区账号(设备授权)、「发布到社区」、插件市场的「社区」来源。

## Consequences

- 维护者要多运维一个服务和一个数据库;部署文档给出单机 compose 的完整步骤、备份与升级方法。
- 国内上线需要 ICP 备案、短信签名与模板审核、隐私政策 —— 这些是维护者在腾讯云和工信部那边办的事,
  部署文档列出清单,代码里只留配置位。
- 社区插件在应用里是单独的来源,默认不和官方索引混在一起;装之前的权限确认不变。
