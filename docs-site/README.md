# Open Studio 文档站(docs-site)

基于 [Astro Starlight](https://starlight.astro.build/) 的文档站,双语(简体中文为默认,英文在 `src/content/docs/en/`)。

> 注意:这是全部对外文档的**唯一**来源——用户手册、下载安装、各功能指南、项目信息都在
> `src/content/docs/` 下(`start/`、`guides/`、`about/`)。仓库根 `README.md` 只是速览与直达入口。

产物是纯静态 `dist/`,当前用途是**独立部署做 SEO**;「App 内本地托管离线查看」在规划中,尚未接入
(Electron 主进程目前没有文档服务,打包也不带 `docs-site/dist/`)。构建产物不入库(见本目录 `.gitignore`)。

## 本地开发

```bash
cd docs-site
pnpm install
pnpm dev          # http://localhost:4321
```

内容在 `src/content/docs/`(Markdown / MDX)。侧边栏在 `astro.config.mjs` 里按目录 autogenerate;
英文页放在 `src/content/docs/en/` 下的镜像路径,缺失的英文页会自动回退到中文并提示。

产品截图在 `src/assets/screens/`(1920 宽 PNG,来自真实界面)。更新截图时保持同名覆盖即可,
中英文页共用同一批图。

## 构建

```bash
pnpm build        # → dist/(含 Pagefind 本地搜索索引,离线可用)
pnpm preview      # 本地预览 dist/
```

## 独立部署(SEO)

部署前把站点域名设成真实地址,用于生成 `sitemap.xml` / canonical / og:

```bash
# 默认已是 https://openstudio.team;部署到别的域名时才需要覆盖
DOCS_SITE_URL="https://docs.你的域名.com" pnpm build
```

- 根域名部署:`base` 用默认 `/` 即可。
- 子路径部署(如 GitHub Pages 项目站 `/repo/`):额外设 `DOCS_BASE="/repo/"`。

把 `dist/` 作为静态站点部署即可;Starlight 已内置 sitemap 与语义化 HTML,SEO 友好。
