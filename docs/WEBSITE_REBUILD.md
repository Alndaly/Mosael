# 官网重建交接

> 目标:把 Astro/Starlight 文档站(`docs-site/`)重建成一个**官网** —— 品牌门面,文档是
> 其中一部分,并为后续的插件 / 工作流社区留出位置。
>
> 这份文档是给**下一轮**看的:已经确认的事实、已经踩过的坑、以及推荐的形状。

## 当前进度(2026-08-03)

站在 `website/`,`pnpm build` 出 35 个静态页。已经完成:

- **双语路由**。`/zh` 与 `/en`,`[locale]` 段下就是根布局,`/` 由 redirects 收口。
- **首页**。撞色色带版面(纸 / 墨 / 朱轮流铺满),三段叙述各配一张真实界面。
- **文档区**。24 页(中英各 12)从 Starlight 迁成 `content/docs/` 下的 MDX,三栏
  (目录 / 正文 / 本页目录),正文一个字没改。
- **插件页**。列表构建期直接读 `plugins/examples/` 里的 manifest,不另抄一份。
- **工作流页**。条目形状已定,画廊在等第一条投稿。
- **录制脚本**已改成同时写 `docs-site/` 和 `website/public/media/`。

**还没做**:退役 `docs-site/`(两份文档并存会漂移,但新站还没部署,所以先留着);
`/api/workflows` 的示例图;把 README 里指向 openstudio.team 的链接对一遍。

设计与工程上的约定写在 [`website/README.md`](../website/README.md),不在这里重复。

## 技术栈(用户指定)

Next.js + Tailwind CSS + shadcn/ui,**全部取最新版**。

动手第一步是核对版本,别照记忆写:

```bash
npm view next version && npm view tailwindcss version && npm view react version
npx shadcn@latest init          # shadcn 自己会带上匹配的依赖
```

注意:Tailwind 4 起配置从 `tailwind.config.js` 移到了 CSS 里的 `@theme`;shadcn 的 CLI 已跟进,
但网上多数教程还停在 v3 的写法。以官方文档为准。

## 现有内容:26 页,中英双语,不能丢

```
start/     intro · quickstart · download
guides/    editing · ai-studio · workflows · publishing · knowledge-base · providers · plugins
about/     project · contact
index.mdx  首页
```

`en/` 下是同构的英文版。**双语必须保留** —— 现在是 Starlight 的 i18n,Next 这边要自己搭
(App Router 的 `[locale]` 段 + 一份 messages)。

媒体在 `docs-site/src/assets/`(17MB,screens/ 与 gifs/),由
`scripts/record-doc-media.py` 对着真实界面生成 —— **重建后要把那个脚本的输出路径跟着改**,
否则下次重录会写进一个没人读的目录。

## 设计方向(用户原话:「文艺一些」)

这个产品的调性在 README 和现有首页里已经有了 —— 中文语境、克制、不堆特性清单。几条建议:

- **首页讲一件事**:本地优先的 AI 视频工作台。别把七个模块平铺成七张卡。
- 现有的 GIF 是真实界面录的,是最好的素材。让它们大一点、少一点。
- 深浅色都要 —— 应用本身两套主题,官网只做一套会显得是两个产品。
- 中文排版是重点:行高、标点挤压、中英混排的字距。这部分决定「文艺」成不成立,
  比配色重要。

## 社区留位(用户后续计划)

要给**官方插件**与**工作流**留出可索引的位置。建议现在就把数据形状定下来,哪怕先手写:

- 插件:id / 名称 / 简介 / 作者 / 仓库 / 截图 / 支持的能力
- 工作流:名称 / 简介 / 节点数 / 需要哪些供应商 / 一份可导入的 JSON

现成的例子在 `plugins/examples/`(text-toolkit、tikhub、mcp-everything),
manifest 格式见 `docs/PLUGIN_MANIFEST.md`。工作流的导入格式就是 `/api/workflows` 的 graph。

## 踩过的坑

- **配图会过期,而过期的配图比没有更糟**。`scripts/record-doc-media.py` 是脚本化重录的入口,
  别退回手工截图。
- 现在的站点构建产物走 Astro 的图片优化(PNG → webp,240kB → 62kB)。Next 用
  `next/image` 能达到同样效果,但**要确认 GIF 的处理**:`next/image` 默认不优化 GIF,
  需要 `unoptimized` 或换成 video。
- 文档里有指向仓库文件的相对链接(如 `../docs-site/src/content/docs/guides/plugins.md`),
  迁移时会断,搜一遍 `](../` 和 `](/docs`。

## 别忘了

`docs/` 下还有一批**开发者文档**(ARCHITECTURE / MCP / PLUGIN_* / adr/),它们服务的是贡献者
而不是用户,留在仓库里即可,不要一起搬进官网 —— 但官网该有一个指向 GitHub 的入口。
