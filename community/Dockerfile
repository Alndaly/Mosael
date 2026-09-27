# 社区服务的生产镜像。构建上下文是**仓库根**:要带上 packages/mosael-formats(和桌面后端共用的格式校验)、
# 官方条目的静态索引(seed-official 用)和 Mosael 字标(分享预览图用)。
#   docker build -f community/Dockerfile -t mosael-community .
# 部署见 docs/DEPLOY_COMMUNITY.md 与 deploy/community/docker-compose.yml。

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# 分享预览图的标题要能画中文:装 Noto CJK。
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

WORKDIR /app/community
COPY packages/mosael-formats /app/packages/mosael-formats
COPY community/pyproject.toml community/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY community /app/community
RUN uv sync --frozen --no-dev

COPY website/public/brand/mosael-wordmark-tight.png /app/assets/mosael-wordmark-tight.png
COPY website/public/plugins/registry.json /app/official-catalog/plugins/registry.json
COPY website/public/workflows /app/official-catalog/workflows

ENV PATH=/app/community/.venv/bin:$PATH \
    COMMUNITY_ENV=production \
    COMMUNITY_DATA_DIR=/data \
    COMMUNITY_STORAGE_DIR=/data/media \
    COMMUNITY_OFFICIAL_CATALOG_DIR=/app/official-catalog \
    COMMUNITY_OG_WORDMARK_PATH=/app/assets/mosael-wordmark-tight.png \
    COMMUNITY_OG_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc

RUN useradd --system --uid 10001 --home /data community \
    && mkdir -p /data/media /data/keys \
    && chown -R community /data \
    && chmod 700 /data/keys
USER community
EXPOSE 8000

# --proxy-headers:客户端 IP 取 Caddy 给的 X-Forwarded-For(限速按它算)。服务端口不对外发布,只有 Caddy 连得到,
# 所以信任所有来源的转发头是安全的(见 docker-compose.yml)。--no-access-log:uvicorn 的访问日志带查询串,
# 本地上传地址的签名就在查询串里;访问日志由服务自己记、不带查询串。
CMD ["uvicorn", "community.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log", "--workers", "2"]
