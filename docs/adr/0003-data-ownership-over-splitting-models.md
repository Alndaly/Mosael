# 数据边界靠归属规约维持,模型可按领域切片但只暴露统一装配入口

SQLAlchemy 模型可以放进 `app/db/model_slices/<domain>.py`,但这些文件是统一 ORM module 的
**实现**,不是新的公共 interface。所有调用方继续只从 `app.db.models` 导入；该装配入口负责导入
全部切片、注册 `Base.metadata` 并重新导出类。API schema 与前端 client 采用同一形状：领域切片在内，
`app.api.schemas` / `@/api/client` 是唯一稳定入口。

文件切片只改善 locality，不代表数据归属。「谁能写」仍只有一个答案：每张表归一个领域 module
所有(`app/domain/ownership.py`)，行创建只发生在拥有方，跨领域需要新行时调用拥有方的领域函数。
归属由 AST 棘轮测试强制(`tests/test_data_ownership_ratchet.py`)：存量越界 allowlist 只减不增，
新表必须登记归属。

**Supersedes the original 2026-08 decision not to split files.** 实际维护中，`models.py`、schema 与
前端 client 分别增长到 1k–2k 行，修改一个领域需要穿过多个无关领域，单文件总览的收益已经小于
定位成本。保留统一装配入口后，调用方仍只有一个导航入口；归属棘轮继续约束真正的写入 seam。

**Considered options**:让调用方直接 import 各领域切片 — 拒绝：文件布局会变成公共 interface，移动类
会扩散到全仓；ORM session 事件校验 — 拒绝：运行时才报错，棘轮在测试期就挡住且零运行时成本。

## 当前落实状态（2026-09-01）

browser、publish、jobs/task-events、notifications、scheduler、workflows 与 boards 已同时拥有 ORM、API
schema 和前端 API client 的领域切片；`SourceAssetRef` 位于生成域 schema，供生成接口与画板接口共享。
三个稳定装配入口不变，路由、领域服务与 UI 不直接导入切片文件。

装配正确性由两组测试固定：后端断言重导出的类身份相同且表已注册进 `Base.metadata`，前端断言领域
函数从 `@/api/client` 重导出。新增切片时必须同步扩展这两组测试。
