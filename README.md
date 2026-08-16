# Open Studio

**简体中文** | [English](README.en.md)

AI 视频创作工作室 = **NLE 内核 + AI 应用中心 + 创作型智能体工作台 + 自媒体矩阵发布**。

本地优先的桌面应用:一个 Electron 壳里跑着 FastAPI 后端(SQLite)、React 前端和一个内嵌浏览器发布执行器。
素材导入 → 逐字剪辑 → 导出成片 → 抖音/B站/小红书/视频号矩阵发布,可由工作流与定时触发器全自动串起来。
工作流可嵌套(子图 / 调用工作流 / 框选折叠);所有持久登录集中在「浏览器池」里,供发布、工作流 RPA 与智能体复用。

![操作演示:素材拖入时间线,播放头定位后一键分割](docs/media/timeline-edit.gif)

> 更多操作演示(工作流搭建、字幕配音、发布矩阵……)见[官网文档](https://openstudio.team)各指南页(源码在 `website/content/docs/`)。

### 近期新增

**字幕配音,以及「引擎 / 模型」分开** —— 字幕面板里每条字幕自带配音入口,也可以整批配;产物落到
一条专门的配音轨(原声不动,不满意整条删掉就回到原样),再配一次回到同一条轨而不是摞出一叠。
可选「缩放到段落长度」——用的是片段自己的倍速,渲染时 atempo 变速,所以无损、可撤销、事后还能微调。

配音这条路上最要紧的一件事是:**语言对不上时,引擎不会报错**。它按自己认识的发音规则硬念一遍,
交出一段听起来像中文又不像中文的东西,然后报成功。现在选引擎的那一刻就会说清楚,而不是等你听完
几十秒才发现。判据只用书写系统(假名、谚文、西里尔、阿拉伯、天城文是硬证据;拉丁字母证明不了
任何事,所以那几门语言由你在「权重」下拉里明说)。

顺着这条线把 F5-TTS 的**语言能力从引擎挪到了权重上**:引擎什么语言都支持,支持范围由权重决定。
十门语言(中英 / 日 / 法 / 德 / 西 / 意 / 俄 / 印地 / 阿拉伯 / 芬兰)可按需下载,缺哪份就在配音弹层
当场给下载按钮——用你自己的克隆音色念日文,只是多下一份权重的事。

![字幕配音:每条字幕自带入口,产物落到一条专门的配音轨](docs/media/subtitle-dub.png)

**智能体会话的「轨迹」视图** —— 对话回答「它说了什么」,轨迹回答**「它做了什么、时间花在哪」**:
一屏三条泳道(输入 / 模型 / 工具)把整个会话压成色块,下面是逐步的执行流,点开某一步能看到它的
入参、返回、耗时。系统提示只在**变化的那一轮**记一份(跨会话记忆和任务计划都拼在里面,每轮都可能
不一样),上下文注入单独成条——你看到的提问,才是模型真正收到的那一份。

![轨迹视图:三条泳道 + 逐步执行流 + 会话统计](docs/media/agent-trace.png)

**发布矩阵的平台专属属性** —— 可见性(私享 / 不公开列出 / 公开)、YouTube 的「面向儿童」、小红书的
原创声明,声明在一处、表单按平台自动出。TikTok 与 YouTube 的自动发布链路已在真机跑通;B 站与视频号
实测确认没有可见性控件,就不假装有。

**后端也说你的语言** —— 任务消息、引擎目录、下载进度句都按请求方的 `Accept-Language` 返回。存的是
key + 参数、出口才翻:任务记录活得比一次请求久,写入时就翻会把语言冻死在那一刻。

**界面字号跟屏幕走** —— 673 处写死的像素收成四档 token,小屏不再挤、大屏不再空。

**供应商与模型分成两级** —— 一条「供应商」是**一个端点 + 一份凭据**,下面可以有任意多个模型;
能力(对话 / 绘图 / 视频 / 音频)、上下文长度、推理与视觉开关都挂在**模型**上。

**智能体的上下文水位与自动整理** —— 输入框的会话设置里直接显示还剩多少,超过窗口八成时把早期对话
交给模型摘要、保留最近若干轮,也可以随时手动「立即整理」。整理会作为一条记录留在对话里。

**思考模式 / 订阅计划额度 / 桌面常驻 / 飞书里批准确认卡** —— 会话级思考档位;订阅制供应商可查额度与
重置周期;关窗只收进托盘(定时任务跑在本机后端里);从飞书驱动智能体时确认卡就地批准。

**工作流嵌套(参考 ComfyUI / dify)** —— 框选画布上的节点,一键「折叠为子图」,进出边界的引用自动重连;子图可任意嵌套,`调用工作流`把整条流程当工具复用,循环体与顶层共用同一套并行引擎。

![框选 → 折叠为子图](docs/media/collapse-subgraph.gif)

**浏览器池** —— 把所有持久登录身份统一成「档案」:发布账号(挂平台)与任意站点的通用登录,一处管理;发布、工作流 RPA 与 AI 智能体都能复用其登录态。智能体复用需**逐次显式授权**(确认卡点名是哪个身份),动不了你没给的账号。

![浏览器池:统一登录身份,工作流与智能体安全复用](docs/media/browser-pool.png)

![智能体授权闸:复用登录身份必须逐次显式授权](docs/media/agent-authorize.png)

> 浏览器池为真机截图;「折叠为子图」动画与授权确认卡为按品牌设计系统生成的示意图。

---

## 快速开始:启动 App

已构建好的 App 在 `release/mac-arm64/Open Studio.app`,双击即可,或:

```bash
open "release/mac-arm64/Open Studio.app"
```

App 会自动拉起内置后端(占 `127.0.0.1:8800`)、加载前端、启动发布执行器——不需要手动起任何服务。

> 端口 8800 若已有健康的后端(比如你开着 dev server),App 会**复用**它而不是再起一个。

## 从源码构建

```bash
pnpm install                 # 根目录一次
cd backend && uv sync && cd ..

pnpm build:mac               # 前端 + 发布器 bundle + 后端(PyInstaller) + 打包 .app
open "release/mac-arm64/Open Studio.app"
```

`pnpm dist:mac` 同流程但产出 `.dmg`(分发时用)。

### 应用更新

打包版启动 5 秒后静默比对 [GitHub Releases](https://github.com/Alndaly/OpenStudio/releases)
最新 tag 与当前版本,发现新版弹提示引导到发布页下载;设置 → 本地后端 → 版本 里也有
「检查更新」按钮。

**发布新版只需打 tag**:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

CI(`.github/workflows/release.yml`)会自动打包 macOS `.dmg`(arm64)与 Windows
安装包(NSIS),挂到自动生成变更说明的 GitHub Release 上,两个平台都成功后才转正。
版本号在 CI 里直接取自 tag,不需要先改 `package.json`。构建产物只进 Releases,
**永远不进仓库**。在 Actions 页手动触发同一工作流则是试打包(只出 workflow
artifact,不碰 Releases)。

> macOS 的**静默自动安装**需要 Developer ID 签名 + 公证(未签名包 Squirrel 校验必失败),
> 所以当前是「检查 + 提示」的降级路线;`build.publish` 已配好 GitHub provider,签名具备后
> 换 electron-updater 即可平滑升级为全自动安装,渲染层接口不变。仓库无 Release 或不可达时
> 检查静默失败,不打扰使用。

⚠️ **改了前端就必须重新 `build:frontend`**(`build:mac` 已包含)。只跑 `build:publisher` 再打包会让前端停留在旧版本——这个坑踩过:CSS 改了却"没生效",查半天发现根本没进包。

### 构建脚本

| 脚本 | 作用 |
| --- | --- |
| `pnpm build:frontend` | Vite 构建前端 → `frontend/dist` |
| `pnpm build:publisher` | esbuild 打包内嵌发布执行器 → `electron/publish.bundle.cjs` |
| `pnpm fetch:tts-python` | 抓取随包分发的独立 CPython → `build/python`(声音克隆用,~48MB) |
| `pnpm build:backend` | PyInstaller 打包后端 → `backend/dist/open-studio-backend` |
| `pnpm build:mac` | 以上三者 + electron-builder 出 `.app` |
| `pnpm dist:mac` | 同上,出 `.dmg` |

## 开发模式

后端与前端分开跑(前端热更新):

```bash
# 终端 1 — 后端
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8800

# 终端 2 — 前端
cd frontend
pnpm dev            # http://localhost:5173
```

浏览器打开 `http://localhost:5173` 即可开发绝大部分功能。
**例外**:发布的内嵌浏览器(登录/上传/地址栏工具栏)只存在于 Electron,网页版会提示"需要桌面端"。

### 桌面端热调试(内嵌浏览器等 Electron 功能)

不用打包,一条命令起 vite + Electron:

```bash
pnpm dev            # 仓库根目录;等价于 frontend 的 pnpm electron:dev
```

它会先构建发布 bundle,再并行跑三件事(带颜色前缀 `vite` / `bundle` / `electron`):
- `vite`:前端热更新(`--strictPort`,5173 被占直接报错,不会静默换到 5174 导致 Electron 加载错服务器);
- `bundle`:`esbuild --watch=forever`,改 `electron/publish/**` 的 TS 自动重打 `publish.bundle.cjs`;
- `electron`:等 5173 就绪后加载它;`main.cjs` 的 dev 分支会自动复用或拉起 8800 的 `uvicorn` 后端。

改 `electron/publish/**` 后 bundle 会自动更新,但**主进程不热更**——重启 `pnpm dev` 生效。改 `main.cjs`/`preload.cjs` 同理。主窗口 DevTools:`Cmd+Option+I`;内嵌账号视图:发布页右键账号 → 「检查页面(DevTools)」。

若 Electron 报 `Electron failed to install correctly`(pnpm 有时漏跑其安装脚本):`pnpm rebuild electron`。

若后端报 `bad interpreter: .../.venv/bin/python3: No such file or directory`:venv 的 console script
把解释器路径**写死在 shebang 里**,仓库目录一改名(或整个搬到别的机器/路径)就全部失效。重建即可:

```bash
cd backend && uv venv --clear && uv sync
```

> 拉起后端的两处(`dev:backend` 脚本与 `main.cjs`)已改用 `.venv/bin/python -m uvicorn` ——
> `python` 是符号链接、不经 shebang,所以它们本身不受路径变动影响;受影响的是直接调
> `uvicorn` / `pytest` 等 console script 的用法。

### 测试与检查

```bash
cd backend  && uv run pytest -q          # 910 用例
cd frontend && pnpm vitest run           # 258 用例
cd frontend && pnpm exec tsc -b --noEmit # 类型检查(必须在 frontend 目录下跑)
cd frontend && pnpm gen:api              # 后端 OpenAPI 变更后重生成 TS 类型
```

## 数据与日志

| 位置 | 内容 |
| --- | --- |
| `~/.open-studio/open-studio.db` | SQLite 主库(工作区/项目/素材/序列/任务/账号…; |
| `~/.open-studio/media/` | 导入与导出的媒体文件 |
| `<userData>/logs/publisher.log` | 发布执行器全链路(认领/goto/登录/巡检/回报) |
| `<userData>/logs/backend.log` | 打包版后端 stdout/stderr |
| `<userData>/Partitions/` | 各发布账号的持久登录会话 |

`~/.open-studio` 是 `Path.home()` 下的目录,Windows 上即 `C:\Users\<用户名>\.open-studio`。
`<userData>` 是 Electron 的用户数据目录:mac 为 `~/Library/Application Support/Open Studio`,
Windows 为 `%APPDATA%\Open Studio`。插件目录同理——不必照着这里拼,插件页会直接显示后端
解析出的**真实路径**。

排查发布问题先看 `publisher.log`,每一步都有记录。

## 仓库结构

```
backend/          FastAPI + SQLAlchemy 2.0(建表走 create_all + _migrate_*,见 ARCHITECTURE)
  app/domain/     领域内核:sequences(剪辑) render workflows publish browser kb agent
                  scheduler transcripts generation plugins notifications
                  provider_models(供应商模型) provider_quota ai_retry
  app/api/routes/ HTTP 路由
  tests/          pytest
frontend/         Vite + React 19 + TS + Tailwind v4 + Radix/shadcn
  src/features/   editor timeline monitor media ai-studio workflows browser-pool
                  publish kb scheduler plugins settings
  src/design/     设计令牌(tokens.css)
  src/app/        壳层、路由、i18n(messages.ts)、全局样式(styles.css)
electron/         main.cjs(主进程)+ publish/(内嵌浏览器发布执行器 TS 源)
agent-sidecar/    智能体 sidecar(pi 运行时,Node)
contracts/        跨实现的可执行规约(前后端各跑一遍同一份语料),见 contracts/README.md
docs/             架构与子系统文档(见下)
plugins/          本地插件(子进程脚本 / 接入 MCP 服务)
```

## 深入文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 系统架构:三段自举、领域内核、数据模型、关键模式
- [docs/PUBLISHING.md](docs/PUBLISHING.md) — 发布与账号矩阵:内嵌浏览器、worker 协议、**硬约束与排错**
- [docs/MCP.md](docs/MCP.md) — 智能体的 MCP 工具与确认卡
- [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md) — 插件清单格式与权限
- [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) — 已完成能力清单与前端规约
- [docs/MAINTENANCE_HOTSPOTS.md](docs/MAINTENANCE_HOTSPOTS.md) — 已知维护风险区,以及**改动后至少要跑什么**

## 第三方登录(可选)

Google / Apple 登录按钮只在配置了对应凭据时出现(`backend/.env`):

```
OPEN_STUDIO_GOOGLE_CLIENT_ID=...        # Google Cloud「Web 应用」客户端
OPEN_STUDIO_GOOGLE_CLIENT_SECRET=...    # 重定向 URI 登记 http://127.0.0.1:8800/api/auth/oauth/google/callback
OPEN_STUDIO_APPLE_CLIENT_ID=...         # Apple Services ID;Apple 要求 HTTPS 回调,适用于团队部署
OPEN_STUDIO_APPLE_CLIENT_SECRET=...     # 按 Apple 规范用团队密钥签好的 JWT
OPEN_STUDIO_OAUTH_REDIRECT_BASE=...     # 团队部署时覆盖回调基址(默认 http://127.0.0.1:8800)
```

流程是桌面友好的授权码流:系统浏览器完成授权 → 回调打到本机后端 → App 轮询自动落座;
首次登录按邮箱局部名创建本地账号(与密码账号同权,无本地口令)。

## 许可

源码可见但**保留所有权利**:仅限评估/学习/个人非商业用途,未经书面授权禁止商用与再分发。
详见 [LICENSE](LICENSE);商业授权请联系作者。

## 团队 / 远程服务器

默认连本机后端。要连团队服务器:**登录页底部「后端服务器 · 切换」**——必须在登录前选,因为登录请求本身要打到目标服务器。
填云端地址 → 探活 → 切换并重载(需重新登录)。设置页 → 本地后端 里是同一个入口。
