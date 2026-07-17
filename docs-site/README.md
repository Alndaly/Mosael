# Mibu 文档站(docs-site)

基于 [Astro Starlight](https://starlight.astro.build/) 的文档站。**一份产物两用**:

- **App 内**:`pnpm build` 出纯静态 `dist/`,由 Electron 主进程的本地静态服务器托管,离线可看。
- **独立部署**:同一份 `dist/` 丢到任意静态托管做 SEO(Vercel / Cloudflare Pages / Nginx / GitHub Pages)。

> 注意:这是全部对外文档的**唯一**来源——用户手册、架构、部署、发布、团队/云端等都在 `src/content/docs/` 下
> (含 `dev/`、`about/` 里的工程/设计文档)。仓库根 `README.md` 只是速览与直达入口。

## 本地开发

```bash
cd docs-site
pnpm install
pnpm dev          # http://localhost:4321
```

内容在 `src/content/docs/`(Markdown / MDX)。侧边栏在 `astro.config.mjs` 里按目录 autogenerate。

## 构建

```bash
pnpm build        # → dist/(含 Pagefind 本地搜索索引,离线可用)
pnpm preview      # 本地预览 dist/
```

## 独立部署(SEO)

部署前把站点域名设成真实地址,用于生成 `sitemap.xml` / canonical / og:

```bash
DOCS_SITE_URL="https://docs.你的域名.com" pnpm build
```

- 根域名部署:`base` 用默认 `/` 即可。
- 子路径部署(如 GitHub Pages 项目站 `/repo/`):额外设 `DOCS_BASE="/repo/"`。

把 `dist/` 作为静态站点部署即可;Starlight 已内置 sitemap 与语义化 HTML,SEO 友好。

## 在 App 内托管

Electron 主进程会用一个本地静态服务器托管本目录构建出的 `dist/`(见 `frontend/electron/main.cjs`
的文档服务),用户可在应用内打开文档。打包脚本会把 `docs-site/dist/` 一并带进应用资源。
