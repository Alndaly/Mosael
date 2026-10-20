# Mosael 一键部署(官网 + MosaelCloud,接入已有 nginx)

**这台机器上已经有 nginx(监听 80)→ 不装 Caddy。** Compose 只跑四个服务
(Postgres + MosaelCloud + 官网 + cleanup),80/443 交给宿主 nginx;官网和 Cloud 只绑在
`127.0.0.1` 的回环端口上,由 `deploy/nginx/mosael.conf` 反代。

**只有一个域名**:`https://<DOMAIN>/` 是官网,`https://<DOMAIN>/api/cloud/v1/*` 是云账号。
两者同源 —— 云账号的会话 cookie 才是第一方 cookie,不需要 CORS,也不需要第二个子域。

```
浏览器 ──https──> 宿主 nginx :80/:443   (/etc/nginx/conf.d/mosael.conf)
                     ├── /api/cloud/*  → 127.0.0.1:8901  → cloud:8000   (FastAPI)
                     └── 其余          → 127.0.0.1:3000  → website:3000 (Next.js)
                                                          │
                                            postgres:5432 (仅 compose 内网,命名卷)
                                            cleanup: 定时删过期行(不对外)
```

## 一条命令(从零到能访问)

```bash
git clone https://github.com/Alndaly/Mosael.git
cd Mosael/deploy
cp .env.example .env
$EDITOR .env          # 只改 DOMAIN 和 POSTGRES_PASSWORD;要发信 / OAuth 再填对应项
docker compose up -d --build   # 在服务器上构建(x86_64),第一次会构建两个镜像

# 接入机器上已有的 nginx —— 把 ${DOMAIN} 换成和 .env 里完全相同的域名
cd ..
sudo cp deploy/nginx/mosael.conf /etc/nginx/conf.d/mosael.conf
sudo sed -i 's/${DOMAIN}/mosael.example.com/g' /etc/nginx/conf.d/mosael.conf
sudo nginx -t && sudo systemctl reload nginx

# HTTPS 证书:certbot --nginx 会改 nginx 配置,先原样备份
sudo cp -a /etc/nginx /root/nginx.bak
sudo certbot --nginx -d mosael.example.com

# 自检
curl -fsS https://mosael.example.com/api/cloud/v1/health   # {"status":"ok"}
```

打开 `https://<DOMAIN>/` 就是官网,注册 / 登录页在 `/en/signup`、`/zh/signup`。
`CLOUD_PUBLIC_URL` 由 `.env` 的 `DOMAIN` 拼成 `https://<DOMAIN>`,不要另行配置;**它必须
与用户地址栏里的 Origin 完全一致**(`www` 的处理见 `nginx/mosael.conf` 末尾)。

> 改了代码或 `NEXT_PUBLIC_*` / 站长验证码之后,用 `docker compose up -d --build` 重新构建。
> 只改云服务的 `CLOUD_SMTP_*` / OAuth 凭据不需要重建镜像,`docker compose up -d` 会重建容器。
> 改 `DOMAIN` 要同时改 `.env` 和 `/etc/nginx/conf.d/mosael.conf`(nginx 不读 `.env`)。

## 目录里每个文件干什么

| 文件 | 作用 |
| --- | --- |
| `docker-compose.yml` | 四个服务:postgres、cloud、website、cleanup(cron);健康检查串起启动顺序;只有一个命名卷(数据库)。官网/Cloud 只发布到 `127.0.0.1`,不发布 80/443。 |
| `.env.example` | 所有环境变量的占位符与说明。复制成 `.env` 后填;`.env` 已被 `.gitignore` 忽略。 |
| `nginx/mosael.conf` | 宿主 nginx 的 server 块:`/api/cloud/*` → `127.0.0.1:8901`,其余 → `127.0.0.1:3000`;含 `Host` / `X-Forwarded-Proto` / `X-Forwarded-For` 与 `client_max_body_size 20m`。**nginx 不读 `.env`**,`${DOMAIN}` 由安装时 sed/手改。 |
| `cloud/Dockerfile` | `uv sync --frozen --no-dev` + `uvicorn cloud.main:app`,非 root,只暴露容器内 8000。 |
| `website/Dockerfile` | pnpm 构建 Next.js;`output: "standalone"` 运行产物 + public/media,非 root,只暴露容器内 3000。 |
| `cloud/Dockerfile.dockerignore`、`website/Dockerfile.dockerignore` | 构建上下文是**仓库根**(`context: ..`),这两个文件只放对应镜像真正需要的路径(等价于社区服务的 `Dockerfile.dockerignore`)。 |
| `postgres/init.sql` | 只在数据卷为空时执行:校验 UTF8、把库默认时区钉成 UTC;表由 Cloud 启动时 `create_all` 建。 |
| `cron/cleanup.sh` | 每 `CLEANUP_INTERVAL_SECONDS` 删一次过期 `cloud_email_codes` / `cloud_sessions` / `cloud_oauth_states`。 |

## 首次部署清单

1. **DNS**:在域名商处加一条 **A 记录:`@`(裸域 `<DOMAIN>`)→ 这台服务器的公网 IPv4**
   (有 IPv6 再补 `AAAA @`)。`www` 可选;如果不加 `www` 的 A 记录,就只用主域访问。
   加了 `www` 就必须在 nginx 配置里选一种处理方式(见 `nginx/mosael.conf` 末尾),
   并且想清楚 `CLOUD_PUBLIC_URL` 对应哪一个 Origin。
2. **端口 / 防火墙**:这台机器上 nginx 已经占着 80;只需要对公网放行 TCP 80、443。
   compose 不发布 80/443,3000 / 8901 / 5432 都只在回环或 compose 内网,不要放行。
3. **`.env`**:
   - `DOMAIN`:只写主机名(`mosael.example.com`),不要 `https://`、路径或结尾斜杠。
     **它要和 `nginx/mosael.conf` 里替换后的域名完全一致。**
   - `POSTGRES_PASSWORD`:用 `openssl rand -hex 32`,它要拼进数据库 URL;不要用带 `@ : / # %`
     的随机串。首次初始化之后改它不会改数据库里的密码(见故障对照)。
   - `WEBSITE_PORT` / `CLOUD_PORT`:默认 3000 / 8901,只绑 `127.0.0.1`;只有被别的进程
     占用时才改,改完 nginx 配置里两处 `proxy_pass` 也要一起改。
4. **SMTP(可选,但邮箱验证码注册/登录需要)**:填 `CLOUD_SMTP_HOST`、端口、加密方式、
   用户名/密码、`CLOUD_SMTP_FROM`。不填的话发码接口明确回 `503 mail_not_configured`,
   官网会把原因显示给用户 —— 不会假装发出。
5. **第三方登录(可选)**:在两个平台各建一个 OAuth 应用,回调地址必须**逐字**是:

   ```
   https://<DOMAIN>/api/cloud/v1/oauth/github/callback
   https://<DOMAIN>/api/cloud/v1/oauth/google/callback
   ```

   然后把 client id / secret 填进 `.env`。留空 = 未启用:官网不显示对应按钮,入口返回
   `oauth_not_configured`,不会出现"点了没反应"。
6. **官网的可选构建期变量**:`NEXT_PUBLIC_GOOGLE_ANALYTICS_ID`、`SITE_VERIFICATION_*`。
   它们写进前端产物,改完必须 `docker compose build website`(或 `up -d --build`)。
   留空 = 不注入 GA、不出对应验证 meta。
7. **启动并自检**:

   ```bash
   cd deploy
   docker compose config >/dev/null      # 解析检查(还没复制 .env 时可加 --env-file .env.example)
   docker compose up -d --build          # 首次会构建;首次拉 Postgres 镜像
   docker compose ps                     # 等 postgres/cloud/website 都 healthy
   curl -fsS http://127.0.0.1:8901/api/cloud/v1/health      # {"status":"ok"}
   curl -fsS -o /dev/null -w '%{http_code}\n' -L http://127.0.0.1:3000/   # 200(根路径 307 到 /en)
   ```

   `cloud` 等 `postgres` healthy 才启动,`cleanup` 等两者 healthy(`depends_on: condition:
   service_healthy`);云服务 unhealthy 时先看 `docker compose logs cloud`。容器 healthy
   之后再到宿主 nginx 这一层验证:改完配置必须 `sudo nginx -t` 通过再 `systemctl reload nginx`。
8. **nginx 安装 / 证书**:

   ```bash
   cd ..   # 回到仓库根(第 7 步在 deploy/ 里)
   # 装站点配置:${DOMAIN} 必须换成 .env 里同一个域名
   sudo cp deploy/nginx/mosael.conf /etc/nginx/conf.d/mosael.conf
   sudo sed -i 's/${DOMAIN}/mosael.example.com/g' /etc/nginx/conf.d/mosael.conf
   sudo nginx -t && sudo systemctl reload nginx

   # 443 / 证书:certbot --nginx 会改写上面的文件,先备份
   sudo cp -a /etc/nginx /root/nginx.bak
   sudo certbot --nginx -d mosael.example.com
   ```

   certbot 成功后它会自动补上 443、证书路径和 HTTP→HTTPS 跳转;要覆盖 `www`,用
   `-d mosael.example.com -d www.mosael.example.com`。证书续期由 certbot 的 systemd
   timer 负责,`systemctl list-timers 'certbot*'` 可查。
   出事要回滚:`sudo rm -rf /etc/nginx && sudo cp -a /root/nginx.bak /etc/nginx`。
9. **备份**:数据库在 compose 的 `postgres_data` 命名卷(用 `pg_dump` 备份);
   nginx 配置在 `/etc/nginx`,证书在 `/etc/letsencrypt`(certbot 管理),它们都不在 compose 里。
   `docker compose down` 保留数据库数据;**`docker compose down -v` 只删 compose 自己的
   命名卷(数据库)**,不会动 `/etc/nginx` 和 `/etc/letsencrypt`。

### 本机验收(可选,不需要 nginx)

```bash
cd deploy
cp .env.example .env
# DOMAIN=localhost 即可,POSTGRES_PASSWORD 随便填
docker compose up -d --build
curl -fsS -o /dev/null -w 'website %{http_code}\n' -L http://127.0.0.1:3000/   # 200
curl -fsS http://127.0.0.1:8901/api/cloud/v1/health                            # {"status":"ok"}
docker compose down -v    # 验收完清干净
```

端口只绑在 `127.0.0.1`,所以本机验收不需要动系统 nginx,也不会占用 80/443。
Cloud 只认 `.env` 里 `DOMAIN` 拼出的 Origin;本机直连 3000 只验证页面,不验证登录写请求。

nginx 配置本身也可以不装 nginx 就校验(容器只做语法检查):

```bash
cd ..   # 仓库根
docker run --rm -v "$PWD/deploy/nginx:/etc/nginx/conf.d:ro" nginx:alpine nginx -t
```

注意这只是语法检查,`${DOMAIN}` 没替换也能过;真正安装前必须换成域名。

## 架构 / 平台注意(Apple Silicon 构建、Linux 运行)

镜像里是**平台相关**的原生二进制:Python 3.14 的 psycopg/argon2 wheel、Next.js 的
SWC 与 sharp。`docker build` 默认构建成**构建机**的架构:

- 目标服务器是 **x86_64**,而构建机通常是 arm64 Mac:最省事的是**在服务器上构建**
  (`docker compose up -d --build`),产物天然是 `linux/amd64`。
- 在 arm64 Mac 上构建 amd64:

  ```bash
  DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose build
  # 然后把镜像推到 registry / 用 docker save|load 送到服务器,再 docker compose up -d
  ```

  走 QEMU,Next.js 构建会明显变慢,但产物可运行。
- 服务器是 arm64(Graviton / Ampere):在 Mac 上原生构建即可,不要加 `linux/amd64`。
- Postgres、cleanup 用的是多架构官方镜像,不受影响;受影响的只有 cloud 和 website
  两个自建镜像。混用架构时,`docker compose config` 不会报错,症状是容器反复重启并打印
  `exec format error` —— 重新按服务器架构构建即可。
- 不要把 `--platform` 只加给一个服务;两个自建镜像要用同一个平台。

## 旧库升级(复用已有 Cloud 数据库)

全新库什么也不用做:Cloud 启动时 `Base.metadata.create_all` 会按当前模型建表,
`cloud_users.password_hash` 本来就是可空(第三方登录新建的账号没有密码)。

**旧库**(在第三方登录之前建的)的 `password_hash` 是 `NOT NULL`;`create_all` 不会改已有列。
在启动新版 Cloud 之前执行一次:

```bash
cd deploy
docker compose up -d postgres
docker compose exec -T postgres psql -U mosael -d mosael <<'SQL'
ALTER TABLE cloud_users ALTER COLUMN password_hash DROP NOT NULL;
SQL
docker compose up -d
```

只在旧库上执行;新库执行会报列已经是可空(或没有可改的东西),不要反复跑。SQLite 开发库
不需要这条,直接换新库即可。

## 过期行清理

`cleanup` 服务用 `postgres:17-alpine` 里的 `psql`,启动后立刻跑一次,之后每
`CLEANUP_INTERVAL_SECONDS`(默认 3600)跑一次。SQL 在 `cron/cleanup.sh`:

```sql
DELETE FROM cloud_email_codes  WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
DELETE FROM cloud_sessions     WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
DELETE FROM cloud_oauth_states WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
```

**只删已过期的行**,不动用户、设备、绑定,也不动还没过期的验证码/会话。查看日志:

```bash
docker compose logs -f cleanup
```

手动跑一次同样的清理(不改删表范围):

```bash
docker compose exec -T postgres psql -U mosael -d mosael <<'SQL'
DELETE FROM cloud_email_codes  WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
DELETE FROM cloud_sessions     WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
DELETE FROM cloud_oauth_states WHERE expires_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC');
SQL
```

如果不想跑这个容器,可以在 `.env` 里把间隔调大,或删掉 compose 里的 `cleanup` 服务;
但那样三张短期表会一直长,建议保留。

## 常见故障对照

| 现象 | 原因 / 处理 |
| --- | --- |
| 打开域名不是 Mosael,而是机器上别的站点 | `/etc/nginx/conf.d/mosael.conf` 里 `server_name` 还是 `${DOMAIN}` 或写错了域名。`sudo nginx -T \| grep -A2 server_name` 看实际值;替换后 `sudo nginx -t && sudo systemctl reload nginx`。 |
| `nginx -t` 报错 / reload 没生效 | 先看报错行;常见是 sed 把域名替换坏了、端口写错、或少了 `;` / `}`。certbot 改过之后出问题,用备份回滚:`sudo rm -rf /etc/nginx && sudo cp -a /root/nginx.bak /etc/nginx`。 |
| `https://<DOMAIN>/` 502 / 一直转圈 | `docker compose ps` 看 website/cloud 是否 healthy;`docker compose logs website cloud`。再看 nginx `proxy_pass` 的端口是否和 `WEBSITE_PORT` / `CLOUD_PORT` 一致,以及回环端口是否真的在监听:`curl -v http://127.0.0.1:3000/`、`curl -v http://127.0.0.1:8901/api/cloud/v1/health`。 |
| `/api/cloud/v1/health` 502,官网正常 | cloud 没起来 / 还在等 postgres。`docker compose logs cloud`;cloud 的 `depends_on` 要求 postgres healthy。也可能 nginx 里 `/api/cloud/` 的 `proxy_pass` 端口写错。 |
| 注册/登录提示"还没配置发信",接口 503 `mail_not_configured` | `.env` 里 `CLOUD_SMTP_HOST` 为空。填 SMTP 后 `docker compose up -d cloud`(不用重建镜像)。 |
| 官网没有 GitHub / Google 按钮,入口回 `oauth_not_configured` | 对应 `CLOUD_*_CLIENT_ID/SECRET` 有一项为空。两把都填;回调地址必须与 README 上面列的一致。 |
| 登录看起来成功,一保存就说"来自别的网站"(`cross_site_request`) | 用户访问的 Origin 与 `CLOUD_PUBLIC_URL` 不一致:用了 `www.` 却填了 apex、http/https 混了、nginx 里 `X-Forwarded-Proto` 丢了,或 `.env` 的 `DOMAIN` 与 nginx 的 `server_name` 不是同一个域名。把两边改成地址栏里**完全一致**的主机名,`docker compose up -d cloud` + reload nginx。 |
| 登录成功但浏览器没保存 cookie | nginx 少了 `proxy_set_header X-Forwarded-Proto $scheme;`:Cloud 以为请求走 http,不会下发 Secure cookie。补上并 reload。 |
| certbot 失败 | DNS 没解析到本机、80/443 没放行、IPv6 AAAA 指错,或前面还有 CDN/反代。先 `curl -I http://<DOMAIN>/` 确认请求到了这台机器;`sudo certbot --nginx -d <DOMAIN>` 重试前先确认 `/root/nginx.bak` 是好的。 |
| `exec format error` / 容器起来就退 | 构建机架构(arm64)和服务器(x86_64)不一致。按「架构 / 平台注意」在服务器上 `docker compose up -d --build`,或用 `DOCKER_DEFAULT_PLATFORM=linux/amd64` 重新构建。 |
| `password authentication failed for user "mosael"` | 首次初始化后改了 `POSTGRES_PASSWORD`:数据库里还是旧密码。改回旧密码,或用 `down -v` 清库重来(会丢数据),或进 psql 手动 `ALTER USER`。密码里有 `@ : / # %` 也会拼坏 URL —— 改用 `openssl rand -hex 32`。 |
| 3000 / 8901 已被占用,容器起不来 | 改 `.env` 的 `WEBSITE_PORT` / `CLOUD_PORT`,同时改 `nginx/mosael.conf` 两处 `proxy_pass`,再 `docker compose up -d` + reload nginx。 |
| 改了 GA / 站长验证码但页面没变 | 它们是构建期变量。`docker compose build website && docker compose up -d`。 |
| 磁盘/镜像很大 | `website/public/media` 有 181MB 实拍,按要求进镜像;运行镜像约数百 MB 是正常的。`Dockerfile.dockerignore` 已排除 `node_modules`/`.next`,但请从干净克隆构建,别把本机巨大的构建产物带进上下文。 |
| 想换回干净状态 | `docker compose down -v` 只删 compose 命名卷(数据库);`down`(不加 `-v`)只停容器,数据还在。系统 nginx 的配置和证书不受影响,需要时用 `/root/nginx.bak` 回滚。 |

## 安全边界(不要为了部署方便改掉)

- **同源**:只有一个 `DOMAIN`。不要给 Cloud 开第二个子域,也不要加 CORS —— 那会把
  HttpOnly 第一方 cookie 变成 `SameSite=None`,放大 CSRF 面。nginx 只按路径分流。
- **Secure cookie / CSRF 保持开启**:compose 固定 `CLOUD_COOKIE_SECURE=true`,Cloud 的同源
  写请求校验不提供关闭开关;不要在生产改回 `false`。反代必须转发 `X-Forwarded-Proto`,
  否则 Secure cookie 不会下发。
- **密钥不进仓库**:`.env` 在根 `.gitignore` 里(还额外点名了 `deploy/.env`);只提交 `.env.example`。
  部署机上的 `.env` 建议 `chmod 600`。
- **不要发布内部端口**:compose 只把官网/Cloud 绑到 `127.0.0.1`(默认 3000 / 8901),
  postgres 不发布端口;80/443 只由宿主 nginx 监听。
- **SMTP / OAuth 留空就是"没启用"**:接口明确报错、官网不显示按钮;不要在 compose 里塞
  假值来"让它看起来能跑"。

## 自检命令

```bash
cd deploy
docker compose config                 # 语法 / 变量解析
docker compose ps                     # 健康状态
docker compose logs -f cloud website cleanup
curl -fsS http://127.0.0.1:8901/api/cloud/v1/health
curl -fsS -o /dev/null -w 'website %{http_code}\n' -L http://127.0.0.1:3000/

# 宿主 nginx 这一层
sudo nginx -t
sudo nginx -T | grep -A3 'server_name'
curl -fsS https://<DOMAIN>/api/cloud/v1/health
curl -fsS -o /dev/null -w 'home %{http_code}\n' -L https://<DOMAIN>/
curl -fsS -o /dev/null -w 'signup %{http_code}\n' https://<DOMAIN>/en/signup
```
