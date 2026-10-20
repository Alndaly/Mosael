# MosaelCloud 的生产镜像。构建上下文是仓库根(deploy/docker-compose.yml 的 `context: ..`):
#   docker build -f deploy/cloud/Dockerfile -t mosael-cloud .
#
# 启动方式与本地一致:uv sync 装锁文件里的依赖,再用 uvicorn 跑 cloud.main:app。
# 表结构由应用启动时的 create_all 创建(全新库);旧库升级见 deploy/README.md。

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# 和 community/Dockerfile 同一个做法:uv 来自官方镜像,不在应用镜像里现装。
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

WORKDIR /app/cloud

# 先只复制依赖清单,让这一层能被缓存;项目本身后面再装。
COPY cloud/pyproject.toml cloud/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 源码在本机是 600(仓库里的文件权限),必须让运行用户能读 —— 否则以 cloud 身份启动时
# import cloud.app 会 Permission denied。
COPY --chown=10001:10001 cloud/src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/cloud/.venv/bin:$PATH" \
    CLOUD_DATA_DIR=/data

# 不用 root 跑服务;/data 兜底 SQLite 与运行数据(生产用 Postgres 时只是 mkdir 的目标)。
RUN useradd --system --uid 10001 --home /data cloud \
    && mkdir -p /data \
    && chown cloud /data

USER cloud
EXPOSE 8000

# --proxy-headers:验证码限流按 nginx 给的 X-Forwarded-For 取客户端 IP(端口只在 127.0.0.1
# 回环上,不是公开端口,信任转发头是安全的)。
CMD ["uvicorn", "cloud.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
