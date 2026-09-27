# 部署官网与社区服务

> **暂不可用(2026-09-27)。** 社区能力先从应用和官网里拿掉了:官网恢复成 1.7.0 的样子(官方索引静态生成),
> 它的 Dockerfile 和社区页面都不在了,下面这套 compose 按现在的仓库搭不起来。社区服务 `community/` 的代码还在;
> 以后重新接入时按那时的实现更新这份手册。见 [ADR 0026](adr/0026-community-service.md) 开头的修订。

这份文档给维护者:在一台自己的服务器上,把官网(Next.js)和社区服务(账号、提交、画板分享,见
[ADR 0026](adr/0026-community-service.md))跑起来,并且知道怎么备份、升级、回滚、查问题。

部署形态是一份 docker compose([deploy/community/docker-compose.yml](../deploy/community/docker-compose.yml)):

```
            ┌──────────── 服务器 ─────────────────────────────────────────────┐
 浏览器 ──443──▶ Caddy(自动 HTTPS)                                            │
            │   ├─ /api/community/*   → community(FastAPI,8000,不对外)       │
            │   ├─ /community-media/* → community_media 卷里的文件(只读)      │
            │   └─ 其余               → website(Next.js standalone,3000)     │
            │   community ──▶ postgres(17,不对外)                              │
            │   community ──▶ 腾讯云短信 / 验证码 / COS(可选)                  │
            └────────────────────────────────────────────────────────────────┘
```

官网和 API 同一个域名(同源):刷新令牌的 cookie 是第一方的,不开 CORS。

本地先整个逛一遍、不部署:见 [community/README.md](../community/README.md) 的「本地跑起来」。

---

## 1. 服务器要求

| 项 | 最低 | 建议 |
| --- | --- | --- |
| CPU / 内存 | 2 核 / 4 GB | 4 核 / 8 GB(构建官网镜像时 Node 要 2 GB 以上) |
| 磁盘 | 40 GB SSD | 按画板分享量估:每个用户上限 5 GB(可配置),本地存储全在 `community_media` 卷里;量大就换 COS |
| 系统 | 能跑 Docker 的 64 位 Linux(Ubuntu 22.04+ / Debian 12+) | |
| 软件 | Docker Engine 24+ 与 Compose v2(`docker compose version`) | |
| 网络 | 公网 IP;入站开放 80、443(TCP)与 443(UDP,HTTP/3);出站能访问腾讯云 API | 安全组只开这三个口,SSH 另限来源 IP |

国内服务器(大陆地域)对外提供网站**必须先完成 ICP 备案**,见第 3 节。

## 2. 域名与 HTTPS

1. 在域名服务商把站点域名(下文 `example.com`)的 A 记录(有 IPv6 再加 AAAA)指到服务器公网 IP。
2. `.env` 里写 `SITE_DOMAIN=example.com`、`ACME_EMAIL=你的邮箱`。
3. Caddy 启动后自动向 Let's Encrypt 申请证书并续期,不需要手动放证书。证书与账号存在 `caddy_data` 卷里 ——
   **不要删这个卷**,否则会重新申请,频繁重申会被限流。
4. 申请证书要求 80 / 443 能从公网访问到这台机器,并且域名已解析过去。大陆服务器未备案的域名会被接入商拦截,
   证书也申请不下来。

## 3. ICP 备案清单(大陆服务器)

代码里不涉及,都是维护者在云厂商和工信部那边办的事:

- [ ] 在服务器所在的云厂商(如腾讯云)提交 ICP 备案:主体(个人或企业)、网站负责人、域名(需已实名)、
      服务器(备案要绑定该厂商的大陆服务器)。
- [ ] 网站名称、内容说明与实际一致(社区含用户上传内容,企业主体更顺利)。
- [ ] 管局审核通过后拿到备案号(形如「粤ICP备XXXXXXXX号」),**在官网页脚展示并链接到 https://beian.miit.gov.cn**。
- [ ] 网站开通后 30 日内到全国互联网安全管理服务平台做公安联网备案,拿到后同样展示在页脚。
- [ ] 准备《用户协议》《隐私政策》文本(官网登录、注册、找回页勾选;服务里只存版本号 `COMMUNITY_TERMS_VERSION`
      和同意时间)。改了文本就把版本号加一,用户下次登录会被要求重新同意。
- [ ] 如果开放用户上传公开内容(画板、工作流、插件),准备好举报处理流程:审核员在「管理」里看举报、下架(第 13 节)。
- [ ] 短信签名的主体要与备案主体一致(见第 4 节)。

## 4. 腾讯云短信

### 4.1 开通与审核

1. 腾讯云控制台 → 短信 → 开通服务;「应用管理」里创建一个应用,记下 **SdkAppId**(形如 `1400xxxxxx`)。
2. 「国内短信 → 签名管理」创建签名:
   - 类型选「网站」,签名内容一般用网站名(如「Mosael」),证明材料用 ICP 备案截图;
   - 审核通过后记下**签名内容**(填 `COMMUNITY_TENCENT_SMS_SIGN_NAME`,注意是**内容**不是签名 ID)。
3. 「国内短信 → 正文模板管理」创建模板,类型选「验证码」,例如:

   ```
   您的验证码为{1},{2}分钟内有效,请勿泄露给他人。
   ```

   - 审核通过后记下**模板 ID**,填 `COMMUNITY_TENCENT_SMS_TEMPLATE_ID`;
   - 模板变量:服务按 `COMMUNITY_TENCENT_SMS_TEMPLATE_PARAMS` 的顺序填,`code` = 6 位验证码,`minutes` = 有效分钟数
     (缺省 5)。上面这个模板就是 `code,minutes`;模板只有一个变量「验证码为{1}」就写 `code`;
   - 登录、绑定(注册)、找回密码想用不同文案,就建三个模板,分别填 `…_TEMPLATE_ID_LOGIN` / `_BIND` / `_RESET`,
     没填的用 `COMMUNITY_TENCENT_SMS_TEMPLATE_ID`。
4. 「套餐包」买短信条数;「安全设置」里可以再加一道频率限制(服务本身已经限:同号 60 秒一条、24 小时 10 条、
   同 IP 每小时 20 条)。

### 4.2 API 密钥与最小权限

**不要用主账号的密钥。** 在「访问管理 CAM」建一个只做这件事的子用户(访问方式只勾「编程访问」),记下
**SecretId / SecretKey**(填 `COMMUNITY_TENCENT_SECRET_ID` / `_SECRET_KEY`),给它绑一条自定义策略:

```json
{
  "version": "2.0",
  "statement": [
    {
      "effect": "allow",
      "action": ["sms:SendSms"],
      "resource": ["*"]
    },
    {
      "effect": "allow",
      "action": ["captcha:DescribeCaptchaResult"],
      "resource": ["*"]
    }
  ]
}
```

不用人机验证就去掉第二条。密钥泄露时在 CAM 里禁用它、换一对新的,改 `.env` 后 `docker compose up -d community`。

## 5. 腾讯云验证码(天御,可选)

防短信轰炸:配了之后,发短信前必须先过一次人机验证。

1. 控制台 → 验证码 → 新建验证,记下 **CaptchaAppId** 与 **AppSecretKey**。
2. `.env` 填 `COMMUNITY_CAPTCHA_APP_ID`、`COMMUNITY_CAPTCHA_APP_SECRET_KEY`(两项都填才启用)。
3. 校验用的是第 4.2 节那个子用户的 SecretId / SecretKey(策略里的第二条)。
4. 官网从 `GET /api/community/v1/auth/config` 读到 `captcha.app_id`,在发送验证码前弹出验证,把
   `{ticket, randstr}` 带进 `POST /auth/sms/send` 的 `captcha` 字段。

## 6. 对象存储 COS(可选)

缺省用本地存储(`community_media` 卷,Caddy 直接出文件)。文件多了、或想上 CDN,换成 COS:

1. 控制台 → 对象存储 → 创建存储桶:地域与服务器相同;访问权限选**私有读写**(媒体用预签名地址读);
2. 存储桶的「跨域访问 CORS 设置」加一条:来源 `https://example.com`,方法 `PUT, GET, HEAD`,
   允许的头 `Content-Type`,暴露 `ETag`(画板文件由浏览器 / 应用直传到 COS);
3. CAM 再建一个子用户(或复用第 4.2 节的那个,但分开更好),策略只给这一个桶:

   ```json
   {
     "version": "2.0",
     "statement": [
       {
         "effect": "allow",
         "action": [
           "name/cos:PutObject",
           "name/cos:GetObject",
           "name/cos:HeadObject",
           "name/cos:DeleteObject"
         ],
         "resource": ["qcs::cos:ap-guangzhou:uid/1250000000:examplebucket-1250000000/*"]
       }
     ]
   }
   ```

   (把地域、APPID、桶名换成你的。)
4. `.env`:

   ```
   COMMUNITY_STORAGE=s3
   COMMUNITY_S3_ENDPOINT=https://cos.ap-guangzhou.myqcloud.com
   COMMUNITY_S3_REGION=ap-guangzhou
   COMMUNITY_S3_BUCKET=examplebucket-1250000000
   COMMUNITY_S3_ACCESS_KEY_ID=<SecretId>
   COMMUNITY_S3_SECRET_ACCESS_KEY=<SecretKey>
   COMMUNITY_S3_ADDRESSING_STYLE=virtual
   # 可选:桶绑了 CDN 且设成公有读时填 CDN 地址,媒体就不用预签名
   COMMUNITY_S3_PUBLIC_URL=
   ```

阿里云 OSS、AWS S3 同理;compose 里也带了一个可选的 MinIO(`docker compose --profile minio up -d`,
见 Caddyfile 末尾注释)。从 local 换到 s3 **不会自动搬旧文件**:先用 `aws s3 sync` / `coscli` 把
`community_media` 卷的内容按原路径传进桶,再切换。

## 7. 首次启动

以下命令都在服务器上的仓库目录里执行。

```bash
git clone https://github.com/Alndaly/Mosael.git && cd Mosael/deploy/community
cp .env.example .env
chmod 600 .env
```

编辑 `.env`,至少改这些(生成随机值的命令写在注释里):

- `SITE_DOMAIN`、`ACME_EMAIL`、`COMMUNITY_PUBLIC_URL=https://<域名>`
- `POSTGRES_PASSWORD`(`openssl rand -base64 32`)
- `COMMUNITY_SECRET_KEY`(`openssl rand -base64 48`)
- 腾讯云短信那一组(第 4 节)
- `COMMUNITY_TERMS_VERSION`(和官网上的协议文本版本一致)

然后:

```bash
# 1. 构建镜像(官网镜像构建要几分钟)
docker compose build

# 2. 生成访问令牌的 EdDSA(Ed25519)签名密钥,存进 community_keys 卷(只生成一次;
#    重新生成 = 所有已签发的访问令牌立即失效,刷新令牌不受影响,15 分钟内大家会自动续上)
docker compose run --rm community python -m community.cli gen-jwt-key --out /data/keys/jwt-ed25519.pem

# 3. 起数据库,跑迁移
docker compose up -d postgres
docker compose run --rm community python -m community.cli migrate

# 4. 检查生产配置(缺什么说什么)
docker compose run --rm community python -m community.cli check-config

# 5. 导入官方条目(官网静态索引里的插件与工作流,归在 official 作者名下;幂等,可重复跑)
docker compose run --rm community python -m community.cli seed-official

# 6. 建第一个管理员(交互输入密码;这个手机号以后也能用短信登录、找回密码)
docker compose run --rm community python -m community.cli create-admin --handle admin --phone 13800000000

# 7. 全部起来
docker compose up -d
docker compose ps
curl -fsS https://example.com/api/community/v1/health
```

之后提拔审核员:`docker compose run --rm community python -m community.cli set-role <handle> moderator`。

不用 compose 生成密钥也可以:`openssl genpkey -algorithm ed25519 -out jwt-ed25519.pem`,再把文件内容
(换行写成 `\n`)填进 `COMMUNITY_JWT_PRIVATE_KEY`。

## 8. 每次发版要不要重跑什么

| 情况 | 要做的 |
| --- | --- |
| 官网上的官方插件 / 工作流有变化(`website/public/plugins/registry.json`、`website/public/workflows/`) | 重建镜像后跑一次 `seed-official`(幂等:只加新版本,不重复) |
| 社区服务有新迁移 | `migrate`(见第 10 节,升级步骤里已经包含) |
| 改了协议文本 | 把 `COMMUNITY_TERMS_VERSION` 加一,`docker compose up -d community` |

## 9. 备份

要备份的只有三样:**数据库**、**文件**、**密钥与配置**。

```bash
cd Mosael/deploy/community
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p ~/mosael-backups

# 数据库(逻辑备份,在线做,不停服)
docker compose exec -T postgres pg_dump -U mosael -d mosael -Fc > ~/mosael-backups/db-$STAMP.dump

# 本地存储的文件(用 COS 时跳过:在 COS 上开版本控制 / 跨地域复制)
docker run --rm -v mosael_community_media:/src:ro -v ~/mosael-backups:/dst alpine \
  tar czf /dst/media-$STAMP.tar.gz -C /src .

# 签名密钥与配置
docker run --rm -v mosael_community_keys:/src:ro -v ~/mosael-backups:/dst alpine \
  tar czf /dst/keys-$STAMP.tar.gz -C /src .
cp .env ~/mosael-backups/env-$STAMP
```

- 用 cron 每天跑一次,备份文件同步到另一台机器或 COS(备份里有密钥,**加密后再外传**,如 `gpg -c`)。
- 至少每季度做一次**恢复演练**:

  ```bash
  docker compose up -d postgres
  docker compose exec -T postgres pg_restore -U mosael -d mosael --clean --if-exists < db-XXXX.dump
  docker run --rm -v mosael_community_media:/dst -v ~/mosael-backups:/src alpine \
    sh -c 'cd /dst && tar xzf /src/media-XXXX.tar.gz'
  ```

卷名前缀 `mosael_` 来自 compose 文件里的 `name: mosael`;`docker volume ls` 可以核对。

## 10. 升级与回滚

**升级**(先备份,见第 9 节):

```bash
cd Mosael && git fetch && git checkout <新版本的 tag 或提交>
cd deploy/community
docker compose build
docker compose run --rm community python -m community.cli migrate   # 迁移只加不删,旧版本代码照样能跑在新表上
docker compose up -d
docker compose run --rm community python -m community.cli seed-official   # 官方条目有变化时
```

**回滚**:

1. 代码回滚:`git checkout <上一个版本>`,`docker compose build && docker compose up -d`。
2. 如果这次升级带了迁移、而上一个版本的代码跑不了新表(迁移说明里会写),用升级前的数据库备份恢复
   (第 9 节的 `pg_restore`)—— 恢复会丢掉升级之后产生的数据,所以先确认必须回到旧表。
   迁移都带 `downgrade`,也可以
   `docker compose run --rm community alembic downgrade <目标版本号>`(在 `/app/community` 目录下执行);
   生产上优先用备份,`downgrade` 只在确认过数据形状时用。
3. 回滚后 `curl https://<域名>/api/community/v1/health` 确认。

## 11. 日志在哪

| 组件 | 怎么看 | 说明 |
| --- | --- | --- |
| 社区服务 | `docker compose logs -f community` | 一行一条 JSON:`ts`、`level`、`logger`、`msg`,访问日志 `logger=community.access`(方法、路径 —— **不带查询串**、状态码、耗时、IP、`request_id`)。**不记验证码、令牌、密码**,出口还有一道过滤 |
| Caddy | `docker compose logs -f caddy` | 证书申请、上游连不上 |
| 官网 | `docker compose logs -f website` | Next.js 的服务端日志 |
| 数据库 | `docker compose logs -f postgres` | |

每个响应都带 `X-Request-Id`,用户报问题时让他给这个值,`docker compose logs community | grep <id>`。
Docker 缺省的 json-file 日志不轮转,建议在 `/etc/docker/daemon.json` 里设
`{"log-driver": "json-file", "log-opts": {"max-size": "50m", "max-file": "5"}}` 后重启 Docker。

## 12. 故障排查

| 现象 | 多半是 | 怎么办 |
| --- | --- | --- |
| `community` 起不来,日志说「社区服务的生产配置不完整」 | `.env` 缺必填项 | 按日志列出的变量补;`check-config` 可以反复查 |
| 起不来,`COMMUNITY_JWT_PRIVATE_KEY is required in production` | 没生成签名密钥 | 第 7 节第 2 步 |
| 起不来,`COMMUNITY_DEV_SMS_CODE is only allowed…` | 生产 `.env` 里留了开发用的固定验证码 | 删掉这一行 |
| 访问站点证书错误 / Caddy 日志 `challenge failed` | 域名没解析到本机、80/443 没开、大陆服务器未备案 | 查 DNS、安全组、备案状态 |
| 所有 `/api/community/*` 返回 502 | 社区服务挂了或还在启动 | `docker compose ps`、`logs community` |
| 发验证码回 `sms_send_failed` | 腾讯云拒了:签名 / 模板未审核、模板变量个数不对、余额不足、密钥权限不够 | 日志里 `provider_error` 是腾讯云的错误码(如 `FailedOperation.TemplateIncorrectOrUnapproved`、`LimitExceeded.PhoneNumberDailyLimit`),对照腾讯云短信错误码文档;变量个数对不上就改 `COMMUNITY_TENCENT_SMS_TEMPLATE_PARAMS` |
| 发验证码回 `captcha_failed` 一直不过 | 验证码 AppId / AppSecretKey 填错,或子用户没有 `captcha:DescribeCaptchaResult` 权限 | 核对第 5 节 |
| 登录后刷新页面就掉线 | cookie 没带回来:没走 HTTPS(`Secure` cookie 在 http 下不存)、或官网和 API 不同源 | 确认从 `https://<域名>` 访问、`/api/community/*` 经同一个 Caddy |
| 用户报「检测到登录凭据被重复使用」 | 刷新令牌被重放(同一枚在 20 秒宽限期外又被用了):多半是用户把 cookie 复制到了别处,或真的被盗 | 会话已自动吊销,让用户重新登录;频繁出现时查日志里 `refresh token reuse detected` 的 IP |
| 画板文件上传 413 | 超过单文件 200 MB / 用户 5 GB / 单张画板 1 GB | 按需调 `COMMUNITY_SHARE_*`、`COMMUNITY_USER_STORAGE_QUOTA_BYTES`;Caddyfile 里上传的 `max_size` 也要跟着调 |
| 用 COS 时上传报 CORS 错误 | 桶的 CORS 没配 | 第 6 节第 2 步 |
| 用 COS 时提交快照报 `unknown_blob` | 直传没成功(预签名过期、CORS、权限) | 浏览器网络面板看 PUT 的响应;子用户是否有 `PutObject`/`GetObject` |
| 分享预览图上中文是方块 | 字体没找到 | 用官方镜像(装了 Noto CJK);自建镜像时设 `COMMUNITY_OG_FONT_PATH` |
| 插件提交后看不到 | 插件要审核 | 审核员在 `GET /admin/queue` 通过;作者在「我的提交」里能看到状态 |
| 统计页的日期差一天 | 按 UTC 切天 | 这是约定:所有按天聚合都按 UTC |
| `migrate` 报连不上数据库 | postgres 还没就绪 | `docker compose up -d postgres` 后等健康检查通过(`docker compose ps` 显示 healthy) |
| 磁盘满了 | 媒体卷或 Docker 日志 | `docker system df`;日志轮转见第 11 节;媒体多了换 COS |

## 13. 日常运营

- **审核**:`moderator` 以上可以用 `GET /api/community/v1/admin/queue` 看待审的插件(清单、权限、工具、文件列表与上一版的差异),
  `POST /admin/submissions/{id}/approve|reject` 处理;`GET /admin/reports` 看举报,`POST /admin/items/{kind}/{slug}/hide`
  下架(`{"hidden": false}` 恢复)。官网上的管理页面调的就是这几个接口。
- **角色**:`set-role <handle> user|moderator|admin`。
- **公开地址**:站点对外只暴露 80 / 443;数据库、社区服务、官网的端口都不发布到宿主机。
