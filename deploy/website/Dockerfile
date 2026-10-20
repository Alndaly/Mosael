# Mosael 官网(Next.js)的生产镜像。构建上下文是仓库根(deploy/docker-compose.yml 的
# `context: ..`):
#   docker build -f deploy/website/Dockerfile -t mosael-website .
#
# next.config.ts 开了 `output: "standalone"`:运行镜像只带 server.js、trace 到的依赖、
# 静态产物和 public/(含 181MB 的 media 实拍),不带源码、测试和整个 node_modules。
# 官网构建期会读仓库根的 plugins/(见 website/src/lib/registry.ts),所以两处都要拷进来
# (相对路径必须保持 website/ 的上一级)。

FROM node:24-alpine AS builder

ENV NEXT_TELEMETRY_DISABLED=1

# website/ 是独立 pnpm 工作区;版本取仓库根 package.json 的 packageManager(pnpm@12.5.1)。
RUN npm install --global pnpm@12.5.1

WORKDIR /app/website

# 先只装依赖,让这层能被缓存。
COPY website/package.json website/pnpm-lock.yaml website/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY website ./
COPY plugins/examples /app/plugins/examples
COPY plugins/bundled /app/plugins/bundled

# NEXT_PUBLIC_* 和站长验证码是**构建期**写进产物的(见 website/README.md)。
ARG NEXT_PUBLIC_GOOGLE_ANALYTICS_ID=
ARG SITE_VERIFICATION_GOOGLE=
ARG SITE_VERIFICATION_BAIDU=
ARG SITE_VERIFICATION_BING=
ARG SITE_VERIFICATION_360=
ARG SITE_VERIFICATION_SOGOU=
# next.config.ts 的 rewrite 在 build 时就会被序列化进产物;指到内网服务名,而不是本地 8901。
ARG CLOUD_API_URL=http://cloud:8000

ENV NEXT_PUBLIC_GOOGLE_ANALYTICS_ID=$NEXT_PUBLIC_GOOGLE_ANALYTICS_ID \
    SITE_VERIFICATION_GOOGLE=$SITE_VERIFICATION_GOOGLE \
    SITE_VERIFICATION_BAIDU=$SITE_VERIFICATION_BAIDU \
    SITE_VERIFICATION_BING=$SITE_VERIFICATION_BING \
    SITE_VERIFICATION_360=$SITE_VERIFICATION_360 \
    SITE_VERIFICATION_SOGOU=$SITE_VERIFICATION_SOGOU \
    CLOUD_API_URL=$CLOUD_API_URL

RUN pnpm build

# standalone 会 trace 一部分 public/(服务端 fs 读到的配图);这里再完整覆盖一次,
# 保证 media 一张不缺。放在 builder 里做,运行镜像仍然只拷一次 standalone。
RUN mkdir -p .next/standalone/public && cp -a public/. .next/standalone/public/

FROM node:24-alpine AS runner

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

RUN addgroup --system --gid 10001 nodejs \
    && adduser --system --uid 10001 --ingroup nodejs nextjs

# standalone 的根就是运行目录(server.js 在它下面)。
COPY --from=builder --chown=nextjs:nodejs /app/website/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/website/.next/static ./.next/static

# next/image 的优化结果要写 .next/cache;非 root 用户必须能写。
RUN mkdir -p .next/cache && chown -R nextjs:nodejs .next/cache

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
