# Mibu

AI 视频创作工作室 = **NLE 内核 + AI 应用中心 + 创作型智能体工作台 + 自媒体矩阵发布**。

本地优先的桌面应用:一个 Electron 壳里跑着 FastAPI 后端(SQLite)、React 前端和一个内嵌浏览器发布执行器。
素材导入 → 逐字剪辑 → 导出成片 → 抖音/B站/小红书/视频号矩阵发布,可由工作流与定时触发器全自动串起来。

---

## 快速开始:启动 App

已构建好的 App 在 `release/mac-arm64/Mibu.app`,双击即可,或:

```bash
open release/mac-arm64/Mibu.app
```

App 会自动拉起内置后端(占 `127.0.0.1:8800`)、加载前端、启动发布执行器——不需要手动起任何服务。

> 端口 8800 若已有健康的后端(比如你开着 dev server),App 会**复用**它而不是再起一个。

## 从源码构建

```bash
pnpm install                 # 根目录一次
cd backend && uv sync && cd ..

pnpm build:mac               # 前端 + 发布器 bundle + 后端(PyInstaller) + 打包 .app
open release/mac-arm64/Mibu.app
```

`pnpm dist:mac` 同流程但产出 `.dmg`(分发时用)。

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
**例外**:发布的内嵌浏览器(登录/上传)只存在于 Electron,网页版会提示"需要桌面端"。

### 测试与检查

```bash
cd backend  && uv run pytest -q          # 148 用例
cd frontend && pnpm vitest run           # 37 用例
cd frontend && pnpm exec tsc -b --noEmit # 类型检查(必须在 frontend 目录下跑)
cd frontend && pnpm gen:api              # 后端 OpenAPI 变更后重生成 TS 类型
```

## 数据与日志

| 位置 | 内容 |
| --- | --- |
| `~/.mibu-new/mibu.db` | SQLite 主库(工作区/项目/素材/序列/任务/账号…) |
| `~/.mibu-new/media/` | 导入与导出的媒体文件 |
| `~/.mibu-new/kb_vectors.db` | 知识库向量(Milvus Lite,可配远程) |
| `~/Library/Application Support/mibu/logs/publisher.log` | 发布执行器全链路(认领/goto/登录/巡检/回报) |
| `~/Library/Application Support/mibu/logs/backend.log` | 打包版后端 stdout/stderr |
| `~/Library/Application Support/mibu/Partitions/` | 各发布账号的持久登录会话 |

排查发布问题先看 `publisher.log`,每一步都有记录。

## 仓库结构

```
backend/          FastAPI + SQLAlchemy 2.0 + Alembic(18 个迁移)
  app/domain/     领域内核:sequences(剪辑) render workflows publish kb agent
                  scheduler transcripts generation plugins notifications
  app/api/routes/ HTTP 路由
  tests/          pytest
frontend/         Vite + React 19 + TS + Tailwind v4 + Radix/shadcn
  src/features/   editor timeline monitor media ai-studio workflows batch
                  publish kb scheduler plugins settings
  src/design/     设计令牌(tokens.css)
  src/app/        壳层、路由、i18n(messages.ts)、全局样式(styles.css)
electron/         main.cjs(主进程)+ publish/(内嵌浏览器发布执行器 TS 源)
docs/             架构与子系统文档(见下)
plugins/          本地插件(子进程 + MCP 暴露)
```

## 深入文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 系统架构:三段自举、领域内核、数据模型、关键模式
- [docs/PUBLISHING.md](docs/PUBLISHING.md) — 发布与账号矩阵:内嵌浏览器、worker 协议、**硬约束与排错**
- [docs/MCP.md](docs/MCP.md) — 智能体的 MCP 工具与确认卡
- [docs/PLUGIN_MANIFEST.md](docs/PLUGIN_MANIFEST.md) — 插件清单格式与权限
- [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) — 已完成能力清单与前端规约

## 团队 / 远程服务器

默认连本机后端。要连团队服务器:**登录页底部「后端服务器 · 切换」**——必须在登录前选,因为登录请求本身要打到目标服务器。
填云端地址 → 探活 → 切换并重载(需重新登录)。设置页 → 本地后端 里是同一个入口。
