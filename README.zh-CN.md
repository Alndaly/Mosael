# Open Studio

[English](README.md) | **简体中文**

Open Studio 是一款运行在本机的 AI 视频工作室，把**多轨剪辑、AI 生成、创作型智能体、
可视化工作流和多平台发布**放进同一个桌面应用。

从导入素材、对着逐字稿剪辑，到生成画面、导出成片和发布，数据默认留在自己的机器上。
应用由 Electron、FastAPI、SQLite 与 React 组成；需要联网的 AI 能力由你配置自己的供应商账号。

![Open Studio 剪辑页：多轨时间线、监看器与逐字稿](https://qingyon-revornix-public.oss-cn-beijing.aliyuncs.com/images/20260902003526649.png)

## 下载与运行

从 [GitHub Releases](https://github.com/Alndaly/OpenStudio/releases) 下载：

- macOS：Apple 芯片版 `.dmg`
- Windows：Windows 10/11 x64 安装程序

安装后直接启动即可。应用会自动拉起内置后端（默认 `127.0.0.1:8800`）、加载前端并启动发布执行器，
不需要手动运行服务。如果 8800 端口已经有健康的 Open Studio 后端，桌面端会复用它。

浏览本地功能无需额外配置；使用 AI 对话、绘图、视频生成、配音或转写前，请先到
**设置 → 供应商**添加连接与模型。

## 核心能力

### 剪辑与逐字稿

- 多时间线、多轨道剪辑，支持切分、吸附、涟漪删除、变速、淡入淡出、画中画和撤销/重做。
- 逐字稿与时间线共用同一份编辑语义：删除句子或单词，画面同步裁切。
- 时间、说话人与正文首行对齐；长正文完整换行，不截断有用内容。
- 字幕、翻译和配音集中在同一面板；配音落到独立轨道，不覆盖原声。
- 曲线、LUT、示波器、滤镜和字幕使用同一套预览/导出契约。

![逐条字幕配音，产物落到独立配音轨](https://qingyon-revornix-public.oss-cn-beijing.aliyuncs.com/images/20260902003526649.png)

### AI 智能体

智能体通过 MCP 工具读取和操作素材、时间线、工作流、浏览器池与发布任务。会改变工程或外部状态的
动作先显示确认卡，由你批准后才执行。

- AI 工作台、剪辑页、工作流和创意画板共用同一会话池。
- 工作区助手默认停靠为真实侧栏，也可切换为悬浮，不会在打开时盖住时间线。
- 左上角直接显示当前会话名称；点击即可搜索或切换会话。
- 主智能体可以并行派发只读子智能体；每个子智能体都是可打开、可观察的独立会话。
- 轨迹视图按输入、模型与工具展示执行过程、耗时、参数和结果。
- 上下文接近上限时可自动或手动整理，整理记录会保留在对话中。

![智能体工作台与会话交互](https://qingyon-revornix-public.oss-cn-beijing.aliyuncs.com/images/20260831143139609.png)

### AI 生成与供应商

供应商配置分为两层：**连接**保存 Endpoint、API Key 或 OAuth 状态；**模型**声明对话、图像、视频、
音频能力以及上下文、推理、视觉和生成参数。界面只显示当前模型真正支持的控件，不从相似型号猜测。

- 支持 API Key 与订阅/OAuth 模型。
- 素材引用保留首帧、尾帧、参考图、编辑源和续写片段等语义。
- Evolink 可作为统一图像/视频网关，生成结果会及时下载回本地素材库。
- 字节跳动接入按产品协议区分：方舟 Ark 承载 Seedream/Seedance，火山语音承载 TTS 与播客接口。
- 未收录能力描述的自定义模型仍可使用，但不会继承其他模型的参数规则。

### 素材与创意画板

- 本地导入视频、音频和图片，自动生成缩略图与预览代理。
- URL 导入先探测清单，再选择条目、音频/视频和实际可用画质；需要登录时可复用浏览器池档案。
- 视频转 GIF 时保留原件，并生成新的派生素材；批处理可使用同名工作流节点。
- 创意画板支持便签、媒体、连线、裁切、`@` 素材引用和 AI 辅助编辑；节点状态与生成生命周期持久化。

![URL 导入：先探测，再选择内容与画质](https://qingyon-revornix-public.oss-cn-beijing.aliyuncs.com/images/20260831142758052.png)

![创意画板](https://qingyon-revornix-public.oss-cn-beijing.aliyuncs.com/images/20260901162232470.png)

### 工作流与调度

可视化 DAG 把检索、生成、转写、拼装、导出和发布串成可复用流程，支持手动、定时和 Webhook 触发。
节点组可以折叠为任意嵌套的子图，跨边界引用会自动重连；循环体与顶层使用同一并行执行引擎。

![框选节点并折叠为子图](https://qingyon-revornix-public.oss-cn-beijing.aliyuncs.com/images/20260831143122120.png)

### 浏览器池与发布

所有持久登录统一保存为浏览器档案，供发布、工作流 RPA、URL 导入和智能体复用。智能体借用某个身份
前必须逐次获得明确授权，确认卡会点名具体档案。

发布表单按平台能力生成，支持 TikTok、YouTube、抖音、B 站、小红书和视频号。平台没有的选项不会
伪装成通用能力；发布任务由独立执行器认领，应用重启后仍可继续追踪。

![浏览器池：集中管理持久登录](docs/media/browser-pool.png)

### Chrome 浏览器扩展

Chrome 扩展使用浏览器原生 Side Panel，不在网页上覆盖浮动面板。浏览 YouTube 或 B 站视频时，
点击扩展图标即可在右侧查看逐字稿、点击句子跳转时间、一键翻译，并把当前视频或播放器当前帧
导入 Open Studio 素材库。扩展使用单独的 Open Studio 登录会话，密码不会保存，也不会读取或
导出 Chrome Cookie。安装与限制见 [browser-extension/README.zh-CN.md](browser-extension/README.zh-CN.md)。

### 插件

插件可以是本地子进程脚本，也可以连接现有 MCP 服务。安装前先读取清单并展示权限、凭据与工具；
启用后，同一工具可被智能体和工作流复用。插件支持素材输入、文件产出和由宿主管理的持久密钥。

## 文档

完整使用指南位于 **[openstudio.team](https://openstudio.team)**，源码在 `website/content/docs/`。
仓库内的实现文档：

| 文档 | 内容 |
| --- | --- |
| [CHANGELOG.md](CHANGELOG.md) | 各版本的用户可见变更 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 启动流程、领域边界、数据模型与关键约定 |
| [docs/PUBLISHING.md](docs/PUBLISHING.md) | 发布矩阵、内嵌浏览器、worker 协议与排错 |
| [docs/MCP.md](docs/MCP.md) | 智能体工具与确认卡 |
| [docs/AGENT_PERMISSION_MODES.md](docs/AGENT_PERMISSION_MODES.md) | 智能体权限模式 |
| [docs/PERMISSION_MODEL.md](docs/PERMISSION_MODEL.md) | 三种主体与授权判定 |
| [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md) | 插件清单格式与权限 |
| [docs/PLUGIN_ARCHITECTURE.md](docs/PLUGIN_ARCHITECTURE.md) | 插件打包、实例化与能力注入 |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | 编码约定与架构棘轮 |
| [docs/MAINTENANCE_HOTSPOTS.md](docs/MAINTENANCE_HOTSPOTS.md) | 高风险区域与验证要求 |
| [browser-extension/README.zh-CN.md](browser-extension/README.zh-CN.md) | Chrome 侧栏扩展的安装、使用与权限 |
| [docs/adr/](docs/adr/) | 架构决策记录 |

## 本地开发

### 环境

- Node.js 22+
- pnpm
- Python 3.13 与 [uv](https://docs.astral.sh/uv/)
- ffmpeg（完整媒体测试需要）

安装依赖：

```bash
pnpm install
cd backend && uv sync && cd ..
```

浏览器开发模式（支持前端热更新）：

```bash
# 终端 1：后端
cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8800

# 终端 2：前端
cd frontend && pnpm dev
```

打开 `http://localhost:5173`。发布用内嵌浏览器、系统托盘、文件关联等 Electron 能力只在桌面模式可用：

```bash
pnpm dev
```

桌面开发命令会同时启动 Vite、发布 bundle 监听和 Electron。修改 `electron/main.cjs` 或
`electron/preload.cjs` 后需要重启进程；主窗口 DevTools 快捷键为 `Cmd+Option+I`。

### 测试与检查

```bash
cd backend && uv run pytest -q
cd frontend && pnpm vitest run
cd frontend && pnpm exec tsc -b --noEmit
cd frontend && pnpm gen:api        # 后端 OpenAPI 变化后运行
cd website && pnpm build           # 修改官网或文档后运行
```

当前基线：后端 2,440 个用例，前端 815 个用例。

### 常见问题

Electron 安装脚本未执行：

```bash
pnpm rebuild electron
```

移动仓库后虚拟环境出现 `bad interpreter`：

```bash
cd backend && uv venv --clear && uv sync
```

## 构建与发布

```bash
pnpm build:mac   # 构建未打包的 macOS App
pnpm dist:mac    # 构建 macOS DMG
```

| 命令 | 产物 |
| --- | --- |
| `pnpm build:frontend` | `frontend/dist` |
| `pnpm build:publisher` | `electron/publish.bundle.cjs` |
| `pnpm build:system` | `electron/system.bundle.cjs` |
| `pnpm build:sidecar` | `agent-sidecar/dist/sidecar.cjs` |
| `pnpm build:extension` | `browser-extension/dist` |
| `pnpm fetch:tts-python` | 声音克隆使用的独立 CPython |
| `pnpm build:backend` | `backend/dist/open-studio-backend` |

发版时同时更新根 `package.json` 与 tag：

```bash
VERSION=0.26.7
npm pkg set version="$VERSION"
git commit -am "chore(release): v$VERSION"
git tag -a "v$VERSION" -m "Open Studio v$VERSION"
git push origin main "v$VERSION"
```

`.github/workflows/release.yml` 会先运行后端与前端全量测试，再创建草稿 Release，并行构建 macOS DMG、
Windows NSIS 安装包、Chrome 扩展和插件 zip。两个桌面平台都通过打包与数据库升级冒烟后，Release 才会转为正式最新版。
手动触发同一工作流只生成 workflow artifact，不发布版本。

打包版会检查最新 Release 并提示更新。macOS 安装包当前未签名，因此采用“检查并提示下载”，不做静默安装。

## 数据与日志

| 位置 | 内容 |
| --- | --- |
| `~/.open-studio/open-studio.db` | SQLite 主库 |
| `~/.open-studio/media/` | 导入、生成与导出的素材 |
| `<userData>/logs/backend.log` | 打包后端日志 |
| `<userData>/logs/publisher.log` | 发布执行器日志 |
| `<userData>/Partitions/` | 持久浏览器档案 |
| `<userData>/custom.css` | 设置 → 外观中的自定义 CSS |

`<userData>` 在 macOS 上是 `~/Library/Application Support/Open Studio`，在 Windows 上是
`%APPDATA%\Open Studio`。应用内会显示插件等动态目录的实际路径。

## 仓库结构

```text
backend/          FastAPI、SQLAlchemy、领域服务与 pytest
frontend/         React 19、Vite、TypeScript、Tailwind v4、Radix/shadcn
electron/         主进程、preload、发布与系统集成 bundle
agent-sidecar/    智能体运行时
browser-extension/ Chrome Side Panel 视频助手
contracts/        前后端共享的可执行契约语料
plugins/          插件示例与清单
website/          openstudio.team 文档站
docs/             架构、权限、发布和 ADR
scripts/          构建与文档同步脚本
```

## 团队与远程后端

默认连接本机后端。要使用团队服务器，请在登录前通过**后端服务器 · 切换**填写地址、探活并重新加载；
设置 → 本地后端提供同一入口。浏览器档案绑定创建它的机器，不会随 SQLite 数据自动迁移。

Google / Apple 登录是可选能力，通过 `backend/.env` 配置：

```dotenv
OPEN_STUDIO_GOOGLE_CLIENT_ID=...
OPEN_STUDIO_GOOGLE_CLIENT_SECRET=...
OPEN_STUDIO_APPLE_CLIENT_ID=...
OPEN_STUDIO_APPLE_CLIENT_SECRET=...
OPEN_STUDIO_OAUTH_REDIRECT_BASE=...
```

## 许可

源码可见但**保留所有权利**：仅限评估、学习与个人非商业用途；未经书面授权不得商用或再分发。
详见 [LICENSE](LICENSE)。商业授权请联系作者。
