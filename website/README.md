# Mosael 官网(website)

Next.js 16 + Tailwind 4 + shadcn/ui。中英双语,文档正文也在这里 —— 它取代了原来的 Astro
Starlight 文档站。

```bash
pnpm install
pnpm dev            # http://localhost:3000
pnpm build          # 文档、下载、更新日志构建期静态生成;社区页请求时渲染
```

## 渲染形态与社区服务

官网分两半(ADR 0026 §8,见 [docs/adr/0026-community-service.md](../docs/adr/0026-community-service.md)):

- **静态的**:首页、文档、下载、更新日志、搜索索引、《用户协议》《隐私政策》占位页 —— 构建期生成,
  不依赖社区服务。服务挂了,文档照常。构建时**不需要** `COMMUNITY_API_URL`。
- **请求时渲染的**:工作流、插件、画板、统计、作者主页(`/u/<handle>`)、分享查看页(`/b/<slug>`)、
  登录 / 注册 / 找回密码、我的账号、设备授权、提交、审核。服务端经 `COMMUNITY_API_URL` 读社区服务的
  公开数据;和「我」有关的一切在浏览器里经会话客户端取。**没配 `COMMUNITY_API_URL` 时这些页显示
  「社区未开放」**,不回退到仓库里的静态索引。

浏览器里的社区请求一律同源发到 `/api/community/v1/*`:线上由反代(Caddy)转给社区服务;本地开发时
`next.config.ts` 的 rewrite 把 `/api/community/*` 转到 `COMMUNITY_API_URL`(路径原样保留,服务自己挂在
`/api/community/v1` 下)。所有接口路径只在 `src/lib/community/endpoints.ts` 里拼;ADR 的接口表里没列、社区服务已经实现、
官网也要用的(举报、公开画板列表、`/auth/config`、忽略举报)单独放在 `REQUESTED` 里,应当补进 ADR。
响应的字段名对齐社区服务(`src/lib/community/types.ts`)。

桌面应用与社区服务给出的链接不带语言段(`/workflows/<slug>`、`/plugins/<slug>`、`/device?code=…`、
`/me/submissions`、`/me/shares`),`next.config.ts` 的 redirects 把它们送到默认语言下对应的页 ——
后两个是「我的账号」页上的锚点。

**会话**(`src/lib/community/session.ts`,测试在 `test/session.test.mjs`):访问令牌只在内存里;刷新令牌是
服务设的 HttpOnly cookie,脚本从不碰。到期前 60 秒(每个标签页再随机提前 0–15 秒)主动刷新;401 时
单飞刷新、其余请求等它、原请求重放一次,刷新失败回到未登录;标签页之间经 `BroadcastChannel` 通告
「拿到新令牌了 / 退出了」;刷新请求带 `X-Requested-With`。页面加载时经 `/auth/refresh` 恢复会话 ——
只在这个浏览器登录过时才自动做(localStorage 里一个布尔标记,不是令牌),文档页的匿名访客不打扰服务。
React 那一层是 `components/community/session-provider.tsx` 的 `useSession()`(带 `communityFetch`)。

**用户写的东西一律不进 MDX**:插件 README、条目说明、分享画板的文档格走 `SafeMarkdown`
(react-markdown,不认原始 HTML)。分享查看页 `/b/<slug>` 另有严格的 CSP(`src/proxy.ts` 只匹配这一条
路由,每个请求一个 nonce);进这一页的站内链接用普通 `<a>`,整页加载 CSP 才生效。

### 社区相关的环境变量

| 变量 | 何时读 | 说明 |
| --- | --- | --- |
| `COMMUNITY_API_URL` | 运行时(服务端) | 社区服务的基址,如 `http://community:8000`,不带 `/api/community/v1`。空 = 社区未开放 |
| `COMMUNITY_MEDIA_ORIGINS` | 运行时 | 分享页 CSP 放行的媒体存储 origin(空格或逗号分隔)。`local` 存储同源,不用配;S3 / COS 这类不同源的存储填它的 origin |
| `NEXT_PUBLIC_TENCENT_CAPTCHA_APP_ID` | 构建时(可选) | 腾讯云验证码(天御)的 CaptchaAppId。不配时用社区服务 `GET /auth/config` 给的;两边都没有就不弹人机验证 |
| `NEXT_PUBLIC_COMMUNITY_TERMS_VERSION` | 构建时(可选) | 《用户协议》《隐私政策》的版本号(`agree_terms_version`)。以服务 `/auth/config` 为准,取不到时用它,默认 `1` |

用户上传的图片、视频、头像、分享预览图一律用普通 `<img>` / `<video>`,不走 `next/image`:地址来自社区
服务(本地存储时是同源的相对路径,S3 时是桶或 CDN 的地址),不在 `images` 配置的白名单里,也不需要
Next 再压一遍。

`NEXT_PUBLIC_*` 在构建时写进前端产物,改了要重新构建。

## 本地跑社区

在本机把官网和社区服务连起来逛、点、登录:

1. **启动社区服务**(`community/`,步骤以 `community/README.md` 为准):开发环境、端口 8900,先跑它的
   `dev-seed` 导入官方条目和演示数据。几项开发配置要对上官网:
   - `COMMUNITY_PUBLIC_URL=http://localhost:3100` —— 本地存储的上传地址、设备授权链接按它拼,指向官网,
     浏览器的请求才同源、经下面的 rewrite 转给服务;
   - `COMMUNITY_COOKIE_SECURE=false` —— 本地是 http。Chrome 在 localhost 上也收 Secure cookie,Safari 不收;
   - `COMMUNITY_DEV_SMS_CODE=<六位数字>`(可选)—— 短信验证码固定成这个;不配时验证码打在服务日志里。
2. **启动官网**:

   ```bash
   COMMUNITY_API_URL=http://127.0.0.1:8900 pnpm --dir website dev --port 3100
   ```

   `/api/community/*` 经 `next.config.ts` 的 rewrite 原样转到服务:请求里的 cookie 带过去,服务回的
   `Set-Cookie` 原样回到浏览器(刷新令牌的 cookie 是 host-only 的,Path 是 `/api/community/v1/auth`)。
   开发环境下服务自己出本地存储的文件(`/api/community/media/…`),同一条 rewrite 就能取到;分享页的预览图
   (`/api/community/v1/shares/<slug>/og.png`)按这次请求的站点补全成绝对地址。
3. **打开 <http://localhost:3100/zh/login>**(用 `localhost`,别混用 `127.0.0.1` —— cookie 按主机名分),
   用手机号 + 开发验证码登录(首次即注册),或用 `dev-seed` 建的演示账号走「账号密码」。要试审核页,
   用社区服务的 `set-role` 把自己设成 `moderator`。

不设 `COMMUNITY_API_URL` 时社区页显示「社区未开放」,文档照常 —— 只改文档时不用起服务。

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
src/lib/community/                   社区服务的接口路径、类型、会话客户端、CSP、图表几何(纯函数,node --test 可测)
src/components/community/            社区页的组件(列表、详情、登录、账号、提交、审核、画板查看)
src/proxy.ts                         只给 /<语言>/b/<slug> 加严格 CSP
public/plugins/registry.json         旧版应用读的插件索引(见 docs/RELEASING.md),官网页面不再读它
public/workflows/                    官方模板的下载文件与目录,供迁进社区服务、后端测试使用;官网页面不再读它
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

- **lint 用 oxlint,不是 eslint**。typescript-eslint 拒绝 TypeScript 7(`does not support TS 7.0`),
  而「依赖取最新版」是这个站的前提;oxlint 自带 TS/TSX 解析、不依赖 `typescript` 包,和
  frontend 是同一套(见 `frontend/LINT.md`)。`.oxlintrc.json` 开了 correctness 整类,加上
  eslint-config-next 原先那几组插件(React、hooks、Next.js、jsx-a11y),全部按 error 算,
  现在是零告警。它挂在仓库根的 `pnpm lint` 里,CI 的 Lint 步骤会跑。类型检查不归它:
  `next build` 会调 `tsc`(`experimental.useTypeScriptCli`)。
- **`/` 没有页面**,由 `next.config.ts` 的 redirects 送到默认语言(`/en`,见
  `src/i18n/config.ts` 的 `DEFAULT_LOCALE`)。全站路由都在 `[locale]` 段下,因为
  `<html lang>` 必须跟着语言变,而真正的根布局拿不到动态参数。这里不做 Accept-Language
  协商:那需要一个匹配全站的 proxy(middleware),每个请求都要过它。现有的 `src/proxy.ts`
  只匹配分享查看页,静态页不经过它。
- **分享查看页上主题脚本与统计不执行**:根布局是静态的,拿不到每个请求的 nonce,next-themes 的内联脚本
  和 GA 在 `/b/<slug>` 的严格 CSP 下被拦下。主题在水合后由 next-themes 补上(深色用户会闪一下),
  统计在这一页不采集 —— 这是有意的取舍。
- **配图会过期,而过期的配图比没有更糟**。重录用 `scripts/record-doc-media.py`,它同时写
  `website/public/media/`;别退回手工截图。

## 界面实拍

当前文档对应 1.7.0。中英指南，配套浅色与深色实拍；MP4 使用可暂停的播放器。录制来源、许可、场景与复录方法见 [媒体说明](../docs/media/README.md)。`pnpm test` 会核对媒体清单哈希、主题配对、语言和正文引用，防止旧图混入新版文档。

## 文档组织与维护

文档导航按六组组织：开始使用、整理与构思、制作与剪辑、自动化与发布、扩展与部署、关于项目。
分组和顺序只在 `src/lib/docs-navigation.ts` 中维护；上一篇、下一篇使用同一顺序。物理目录仍是
`start / guides / about`，保留已发布 URL，不因调整导航改名或移动文件。

新增页面时同时添加 `zh`、`en` 正文和导航条目，填写标题、简短任务描述、版本与更新日期。
两种语言保持相同的小节层级，正文中的内部链接不带语言前缀，由渲染器补充。过时说明应结合当前界面修订，历史更新日志保留原始版本语境。

移动端将「文档目录」和「本页目录」放在同一条导航栏，使用一个模态面板展示。面板限制在视口内、内部滚动，支持 Esc、点击遮罩及选中链接关闭；关闭后恢复触发按钮的焦点。桌面左侧显示完整文档分组，右侧显示当前页标题。

验证：`pnpm test`、`pnpm build`（不设 `COMMUNITY_API_URL` 也要能过），以及从仓库根目录运行
`backend/.venv/bin/python -m pytest backend/tests/test_site_docs_stay_in_sync.py -q`。
交互验证覆盖 390 / 768 / 1100 / 1440 像素宽度、中英文和明暗主题。

启动构建后的官网后，可从仓库根目录运行 `backend/.venv/bin/python scripts/verify-docs-navigation.py` 复查目录交互；`--base-url` 可指定预览地址，截图与结果默认写入 `output/playwright/`。
