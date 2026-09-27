# Mosael 社区服务

账号(短信 / 密码、轮换刷新、设备授权)、工作流与插件的提交与审核、画板分享。设计见
[ADR 0026](../docs/adr/0026-community-service.md),上线部署见 [DEPLOY_COMMUNITY.md](../docs/DEPLOY_COMMUNITY.md)。

FastAPI + SQLAlchemy 2 + Alembic,`uv` 管理。插件包、工作流文件、画板快照的校验来自
[`packages/mosael-formats`](../packages/mosael-formats) —— 和桌面后端同一份。

## 本地跑起来(零依赖)

不需要 Postgres、Caddy、对象存储或短信账号。缺省就是开发模式(`COMMUNITY_ENV=development`):

- 数据库是 `COMMUNITY_DATA_DIR`(缺省 `./community-data`)下的 SQLite,启动时自动迁移;
- 文件存在同一个目录,由服务自己出(`/api/community/media/…`);
- 签名密钥第一次启动时生成到数据目录(`dev-jwt-key.pem`),重启不掉线;
- 短信验证码打印在服务的日志里;想省掉这一步,设 `COMMUNITY_DEV_SMS_CODE=000000`(只有开发模式接受);
- 刷新令牌的 cookie 不带 Secure(本地是 http);站点地址缺省是本地官网开发服务器 `http://localhost:3100`。

```bash
cd community
uv sync

# 示例数据:官方条目、开发账号 admin / demo、几个社区工作流、一个已上架和一个待审核的插件、
# 近 30 天的下载 / 浏览 / 点赞、一张公开画板。幂等,可以重复跑。
uv run python -m community.cli dev-seed

# 起服务
COMMUNITY_DEV_SMS_CODE=000000 uv run uvicorn community.main:app --port 8900 --reload
```

- 开发账号的密码在 `dev-seed` 第一次运行时随机生成,打印在终端上,也写在
  `community-data/dev-credentials.txt`(只在这台机器的开发库里有效)。
- 接口文档(只在非生产环境):<http://localhost:8900/api/community/v1/docs>
- 看官网上的社区页面:官网开发服务器(`http://localhost:3100`)把 `COMMUNITY_API_URL` 指到 `http://localhost:8900`,
  并把浏览器发出的 `/api/community/*` 转给它(和生产上 Caddy 做的事一样,同源 —— 刷新令牌的 cookie 才是第一方的)。
- 开发模式下的两个缺省值就是为这个配的:`COMMUNITY_PUBLIC_URL=http://localhost:3100`(分享链接、设备授权页、
  上传地址都按它拼,所以上传和媒体经官网的转发是同源的)、`COMMUNITY_COOKIE_SECURE=false`(本地是 http)。
  官网开发服务器换了端口就设 `COMMUNITY_PUBLIC_URL`。
- 从头来过:删掉 `community-data/` 目录。

## 测试与检查

```bash
uv run pytest -q          # 缺省在 SQLite 上跑
COMMUNITY_TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/community_test uv run pytest -q   # CI 在 Postgres 上跑
uv run ruff check
```

## 改表

改了 `src/community/models.py` 就要配一条迁移(`tests/test_platform.py` 会比对迁移后的库和模型):

```bash
uv run alembic revision --autogenerate -m "说明"
```

生成的文件里 `community.db.UTCDateTime` 换成 `sa.DateTime(timezone=True)`(迁移不 import 应用代码),
跑过一次的迁移不再改。数据形状的变化一律走迁移,不在读取代码里认两种形状(ADR 0006)。

## 资产(人物 / 场景 / 道具)

ADR 0027 §4。`/assets` 和工作流、插件是同一种条目(`items.kind = "asset"`,`asset_kind` 一列按种类筛),提交收的是
分享包 `mosael.asset/1`(校验在 `mosael_formats.asset_bundle`,桌面端导出、导入过的是同一份),参考图走 `/shares/uploads`
那套三步上传。虚构的发布即上架,真人人物要 `consent_kind` 并进审核队列。`dev-seed` 会放一个虚构人物(带冬装变体)、
一个场景、一个道具,和一个在审核队列里的真人人物。

## 目录

| 位置 | 内容 |
| --- | --- |
| `src/community/app.py` | 应用、中间件(语言、安全头、请求大小上限、写请求限速)、错误形状 |
| `src/community/api/` | 路由:`auth`、`me`、`items`(工作流与插件)、`shares`、`public`(统计与主页)、`admin` |
| `src/community/tokens.py` | 访问令牌(EdDSA JWT)与轮换的刷新令牌 |
| `src/community/sms.py` | 验证码的发与验、限速、腾讯云短信与验证码 |
| `src/community/submissions.py` | 提交、版本、审核与差异 |
| `src/community/storage.py` | 存储接口:`local` / `s3` |
| `src/community/og.py` | 分享预览图 |
| `src/community/catalog.py` | 官方条目导入 |
| `src/community/devseed.py` | 本地开发的示例数据 |
| `src/community/cli.py` | 运维命令:`migrate`、`create-admin`、`set-role`、`seed-official`、`gen-jwt-key`、`check-config`、`dev-seed` |
| `migrations/` | Alembic 迁移 |

## 和 ADR 约定不一样的地方

- **刷新令牌 cookie 的 Path 是 `/api/community/v1/auth`**,不是 ADR 里写的 `/api/community/auth`:刷新接口在
  `/api/community/v1/auth/refresh`,浏览器只在请求路径以 cookie 的 Path 开头时才带它 —— 照 ADR 原文设,cookie
  永远到不了刷新接口。可以用 `COMMUNITY_REFRESH_COOKIE_PATH` 改。
- 设备授权轮询太快回 `429 slow_down`(带 `Retry-After`,间隔加 5 秒);设备码用过一次再来是 `400 device_code_invalid`;
  被拒绝是 `403 access_denied`。ADR 只定了 428 / 410 两种。
- ADR 之外多出的接口:`GET /auth/config`(协议版本、人机验证的 CaptchaAppId)、`POST /{workflows|plugins|shares}/{slug}/report`
  (举报)、`GET /shares`(公开画板列表)、`GET /shares/{slug}/og.png`(预览图)、`POST /admin/reports/{id}/dismiss`、
  `PUT /uploads/{sha256}`(本地存储的上传地址)。
