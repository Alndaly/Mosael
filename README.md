# Open Studio

**简体中文** | [English](README.en.md)

AI 视频创作工作室 = **NLE 内核 + AI 应用中心 + 创作型智能体工作台 + 自媒体矩阵发布**。

本地优先的桌面应用:一个 Electron 壳里跑着 FastAPI 后端(SQLite)、React 前端和一个内嵌浏览器发布执行器。
素材导入 → 逐字剪辑 → 导出成片 → 抖音/B站/小红书/视频号矩阵发布,可由工作流与定时触发器全自动串起来。
工作流可嵌套(子图 / 调用工作流 / 框选折叠);所有持久登录集中在「浏览器池」里,供发布、工作流 RPA 与智能体复用。

![操作演示:素材拖入时间线,播放头定位后一键分割](docs/media/timeline-edit.gif)

> 更多操作演示(工作流搭建、知识库、发布矩阵……)见[文档站点](docs-site/)各指南页。

### 近期新增

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

打包版启动 5 秒后静默比对 [GitHub Releases](https://github.com/Alndaly/mibu-cut/releases)
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
| `pnpm build:backend` | PyInstaller 打包后端 → `backend/dist/mibu-backend` |
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

### 测试与检查

```bash
cd backend  && uv run pytest -q          # 553 用例
cd frontend && pnpm vitest run           # 130 用例
cd frontend && pnpm exec tsc -b --noEmit # 类型检查(必须在 frontend 目录下跑)
cd frontend && pnpm gen:api              # 后端 OpenAPI 变更后重生成 TS 类型
```

## 数据与日志

| 位置 | 内容 |
| --- | --- |
| `~/.open-studio/mibu.db` | SQLite 主库(工作区/项目/素材/序列/任务/账号…) |
| `~/.open-studio/media/` | 导入与导出的媒体文件 |
| `~/.open-studio/kb_vectors.db` | 知识库向量(Milvus Lite,可配远程) |
| `~/Library/Application Support/Open Studio/logs/publisher.log` | 发布执行器全链路(认领/goto/登录/巡检/回报) |
| `~/Library/Application Support/Open Studio/logs/backend.log` | 打包版后端 stdout/stderr |
| `~/Library/Application Support/Open Studio/Partitions/` | 各发布账号的持久登录会话 |

排查发布问题先看 `publisher.log`,每一步都有记录。

## 仓库结构

```
backend/          FastAPI + SQLAlchemy 2.0 + Alembic(29 个迁移)
  app/domain/     领域内核:sequences(剪辑) render workflows publish browser kb agent
                  scheduler transcripts generation plugins notifications
  app/api/routes/ HTTP 路由
  tests/          pytest
frontend/         Vite + React 19 + TS + Tailwind v4 + Radix/shadcn
  src/features/   editor timeline monitor media ai-studio workflows browser-pool
                  publish kb scheduler plugins settings
  src/design/     设计令牌(tokens.css)
  src/app/        壳层、路由、i18n(messages.ts)、全局样式(styles.css)
electron/         main.cjs(主进程)+ publish/(内嵌浏览器发布执行器 TS 源)
agent-sidecar/    智能体 sidecar(pi 运行时,Node)
docs/             架构与子系统文档(见下)
plugins/          本地插件(子进程 + MCP 暴露)
```

## 深入文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 系统架构:三段自举、领域内核、数据模型、关键模式
- [docs/PUBLISHING.md](docs/PUBLISHING.md) — 发布与账号矩阵:内嵌浏览器、worker 协议、**硬约束与排错**
- [docs/MCP.md](docs/MCP.md) — 智能体的 MCP 工具与确认卡
- [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md) — 插件清单格式与权限
- [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) — 已完成能力清单与前端规约

## 第三方登录(可选)

Google / Apple 登录按钮只在配置了对应凭据时出现(`backend/.env`):

```
MIBU_GOOGLE_CLIENT_ID=...        # Google Cloud「Web 应用」客户端
MIBU_GOOGLE_CLIENT_SECRET=...    # 重定向 URI 登记 http://127.0.0.1:8800/api/auth/oauth/google/callback
MIBU_APPLE_CLIENT_ID=...         # Apple Services ID;Apple 要求 HTTPS 回调,适用于团队部署
MIBU_APPLE_CLIENT_SECRET=...     # 按 Apple 规范用团队密钥签好的 JWT
MIBU_OAUTH_REDIRECT_BASE=...     # 团队部署时覆盖回调基址(默认 http://127.0.0.1:8800)
```

流程是桌面友好的授权码流:系统浏览器完成授权 → 回调打到本机后端 → App 轮询自动落座;
首次登录按邮箱局部名创建本地账号(与密码账号同权,无本地口令)。

## 许可

源码可见但**保留所有权利**:仅限评估/学习/个人非商业用途,未经书面授权禁止商用与再分发。
详见 [LICENSE](LICENSE);商业授权请联系作者。

## 团队 / 远程服务器

默认连本机后端。要连团队服务器:**登录页底部「后端服务器 · 切换」**——必须在登录前选,因为登录请求本身要打到目标服务器。
填云端地址 → 探活 → 切换并重载(需重新登录)。设置页 → 本地后端 里是同一个入口。
