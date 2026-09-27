# 官网的生产镜像(Next.js standalone)。构建上下文是**仓库根**:构建时要读 ../plugins(插件页的 README)。
#   docker build -f website/Dockerfile -t mosael-website .
# 部署见 docs/DEPLOY_COMMUNITY.md 与 deploy/community/docker-compose.yml。

FROM node:24-alpine AS deps
RUN corepack enable && corepack prepare pnpm@12.5.1 --activate
WORKDIR /repo/website
COPY website/package.json website/pnpm-lock.yaml website/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM deps AS build
COPY website /repo/website
COPY plugins /repo/plugins
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:24-alpine AS runner
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /repo/website
COPY --from=build /repo/website/.next/standalone ./
COPY --from=build /repo/website/.next/static ./.next/static
COPY --from=build /repo/website/public ./public
COPY --from=build /repo/website/content ./content
COPY --from=build /repo/plugins /repo/plugins
USER node
EXPOSE 3000
CMD ["node", "server.js"]
