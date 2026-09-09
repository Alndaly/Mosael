# Mosael 官网(website)

Next.js 16 + Tailwind 4 + shadcn/ui。中英双语,文档正文也在这里 —— 它取代了原来的 Astro
Starlight 文档站。

```bash
pnpm install
pnpm dev            # http://localhost:3000
pnpm build          # 构建期静态生成全站页面(文档按 content/docs 自动发现)
```

## Google Analytics

官网通过 Next.js 官方的 `@next/third-parties/google` 组件接入 GA4。开发时复制
`.env.example` 为 `.env.local`；部署时在构建环境设置同名变量：

```bash
NEXT_PUBLIC_GOOGLE_ANALYTICS_ID=G-YDRX2Y5WZS
```

未配置该变量时不会注入 Google Analytics 脚本，也不会发送分析数据。`NEXT_PUBLIC_*`
变量会在构建时写入前端产物，修改后需要重新构建并部署。

## 目录

```
content/docs/<语言>/<分区>/<页>.mdx   文档正文(zh / en,分区为 start / guides / about)
public/media/{screens,gifs,videos}     文档的中英文、明暗主题实拍
public/media/homepage/{zh,en}/        首页多窗口展示的实际截图
src/lib/docs-navigation.ts           六组文档导航与阅读顺序
src/components/docs-mobile-nav.tsx   手机和平板的单面板目录
src/app/[locale]/                    全站路由;这一层的 layout 就是根布局
src/i18n/messages.ts                 除文档正文外的全部文案,中英各一份
src/lib/registry.ts                  插件索引 —— 构建期直接读 plugins/examples 里的 manifest
```

## 几条约定

**样式写在 TSX 上,不在 CSS 里另开 class。** `globals.css` 只放三样东西:主题变量、
`<html>/<body>` 这一层拿不到 className 的基础排版、以及 MDX 渲染出来的裸标签
(`.docs-body`)。和主应用 `frontend/src/app/styles.css` 顶部那条约定一致。

**品牌层级以暖白、墨色和紫色为主。** 暖白负责留白，墨色保证阅读，紫色只用于路径、编号、
链接和主操作。正文依靠间距、字号与细分割线区分层级，浮层与叠放截图可使用柔和投影。装饰边框应低对比度，键盘焦点与选中状态仍需清晰。
颜色都注册在 `@theme` 中，组件只使用 Tailwind utility。

**首页按一条创作路径组织。** 核心章节依次是无限画布、3D 场景与动画、素材管理、剪辑、AI 智能体和工作流；文档与素材引用贯穿这些步骤，也不要把作者账号写成官方品牌账号。唯一的 X 链接是
`https://x.com/KindaHuaX`。

**文案不要写进 JSX。** JSX 会把源码里的换行 + 缩进折成一个空格,英文里正好是词间距,
中文里就是凭空多出来的空格,而且只在浏览器里看得见。中文散文一律放 `messages.ts`。

**中文字体走 `@fontsource-variable/noto-sans-sc`,不走 `next/font/google`** ——
后者给 Noto Sans SC 只认 latin 子集,下载下来的文件里没有汉字字形,中文会一路掉到系统默认。
另外字族要挂在 `<body>` 而不是 `<html>`:字体变量是 next/font 通过 className 加在 body 上的,
在 html 那一层 `var()` 解不出来,而解不出来的 `var()` 会让整条 `font-family` 作废。

**客户端组件不能 import `@/lib/docs`**,哪怕只取一个常量:那个模块 import 了 `node:fs`,
而 client component 的 import 会被整个打进浏览器包,构建直接失败。目录树在服务端算好当
props 传。

## 已知的坑

- **`pnpm lint` 跑不了**。typescript-eslint 还不支持 TypeScript 7(`does not support TS 7.0`),
  而「依赖取最新版」是这个站的前提。类型检查没有丢:`next build` 会调 `tsc`
  (`experimental.useTypeScriptCli`)。等 typescript-eslint 跟上就能恢复。
- **`/` 没有页面**,由 `next.config.ts` 的 redirects 送到默认语言(`/en`,见
  `src/i18n/config.ts` 的 `DEFAULT_LOCALE`)。全站路由都在 `[locale]` 段下,因为
  `<html lang>` 必须跟着语言变,而真正的根布局拿不到动态参数。这里不做 Accept-Language
  协商:那需要 middleware,会让每个请求都过一次边缘函数,还让站点没法纯静态导出。
- **配图会过期,而过期的配图比没有更糟**。重录用 `scripts/record-doc-media.py`,它同时写
  `website/public/media/`;别退回手工截图。

## 界面实拍

当前文档对应 1.3.0。中英指南，配套浅色与深色实拍；MP4 使用可暂停的播放器。录制来源、许可、场景与复录方法见 [媒体说明](../docs/media/README.md)。`pnpm test` 会核对媒体清单哈希、主题配对、语言和正文引用，防止旧图混入新版文档。

## 文档组织与维护

文档导航按六组组织：开始使用、整理与构思、制作与剪辑、自动化与发布、扩展与部署、关于项目。
分组和顺序只在 `src/lib/docs-navigation.ts` 中维护；上一篇、下一篇使用同一顺序。物理目录仍是
`start / guides / about`，保留已发布 URL，不因调整导航改名或移动文件。

新增页面时同时添加 `zh`、`en` 正文和导航条目，填写标题、简短任务描述、版本与更新日期。
两种语言保持相同的小节层级，正文中的内部链接不带语言前缀，由渲染器补充。过时说明应结合当前界面修订，历史更新日志保留原始版本语境。

移动端将「文档目录」和「本页目录」放在同一条导航栏，使用一个模态面板展示。面板限制在视口内、内部滚动，支持 Esc、点击遮罩及选中链接关闭；关闭后恢复触发按钮的焦点。桌面左侧显示完整文档分组，右侧显示当前页标题。

验证：`pnpm test`、`pnpm build`，以及从仓库根目录运行
`backend/.venv/bin/python -m pytest backend/tests/test_site_docs_stay_in_sync.py -q`。
交互验证覆盖 390 / 768 / 1100 / 1440 像素宽度、中英文和明暗主题。

启动构建后的官网后，可从仓库根目录运行 `backend/.venv/bin/python scripts/verify-docs-navigation.py` 复查目录交互；`--base-url` 可指定预览地址，截图与结果默认写入 `output/playwright/`。
