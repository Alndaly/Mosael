# Mosael 官网(website)

Next.js 16 + Tailwind 4 + shadcn/ui。中英双语,文档正文也在这里 —— 它取代了原来的 Astro
Starlight 文档站。

```bash
pnpm install
pnpm dev            # http://localhost:3000
pnpm build          # 构建期把 36 个页面全部静态生成(文档正文中英各 13 篇)
```

## 目录

```
content/docs/<语言>/<分区>/<页>.mdx   文档正文(zh / en,分区为 start / guides / about)
public/media/{screens,gifs}          界面配图,由 scripts/record-doc-media.py 生成
src/app/[locale]/                    全站路由;这一层的 layout 就是根布局
src/i18n/messages.ts                 除文档正文外的全部文案,中英各一份
src/lib/registry.ts                  插件索引 —— 构建期直接读 plugins/examples 里的 manifest
```

## 几条约定

**样式写在 TSX 上,不在 CSS 里另开 class。** `globals.css` 只放三样东西:主题变量、
`<html>/<body>` 这一层拿不到 className 的基础排版、以及 MDX 渲染出来的裸标签
(`.docs-body`)。和主应用 `frontend/src/app/styles.css` 顶部那条约定一致。

**颜色只有四个**:纸、墨、朱、靛。它们注册在 `@theme` 里,所以 `bg-flame`、`border-ink`
这些是 Tailwind 生成的 utility。需要在深浅色之间翻转的整幅色带用
`bg-invert text-invert-foreground` —— 夜档里「反相」不是翻成纸色,而是一块抬起来的深色面板,
否则一整幅近白压在深色页面上会闪得人睁不开眼。

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
