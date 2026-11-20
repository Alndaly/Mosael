# 2026-11-20 任务查询与空闲轮询性能优化

## 优化前证据

- 主工作区 `jobs` 共 68,699 行。
- 最近 200 条任务按 `workspace_id + created_at DESC, id DESC` 查询，但旧索引为
  `workspace_id + status + updated_at`，SQLite 查询计划包含 `USE TEMP B-TREE FOR ORDER BY`。
- 同一真实数据库连续 5 次查询：108.2 / 115.4 / 109.0 / 109.1 / 111.1ms，中位约 109ms。
- `select(Job)` 每次读取约 2,135,292 字节，包括列表出参并不使用的 `result`。
- Agent 会话详情在 AI Studio / Canvas / Voice Dock 空闲时仍每 1.2–1.5 秒轮询。
- ComfyUI 工作台可见时每 300ms 注入一次状态读取 JS。
- 发布器启动立即标记全部账号复检，真实日志的一次启动巡检持续约 72 秒。

## 改动

- 新增 `idx_jobs_workspace_created_id (workspace_id, created_at, id)`；旧库由一次性迁移补齐，
  schema version 48 → 49。
- 任务列表与任务中心面板 `defer(Job.result)`，详情、取消和子任务等完整出参不变。
- Agent 会话详情运行中 1200ms、空闲 10,000ms；任务中心活动 1500ms、空闲 15,000ms。
- 点击整理上下文时直接由本地 mutation 显示「正在整理」，不等待空闲轮询发现 running。
- ComfyUI 连续 20 拍无状态变化后从 300ms 降到 1000ms；画布变化、事件、Agent 调用或窗口恢复重置为快速节奏。
- 发布任务认领与心跳立即启动，全量账号巡检延迟 15 秒；停止发布器会取消旧定时器。

## 同一数据库副本复测

- 新查询计划：`SEARCH jobs USING INDEX idx_jobs_workspace_created_id (workspace_id=?)`，无临时排序。
- 完整行查询 5 次：0.9 / 0.7 / 0.6 / 0.6 / 0.6ms，中位 0.6ms。
- 排除 `result` 的列表投影 5 次：0.7 / 0.5 / 0.4 / 0.4 / 0.4ms，中位 0.4ms。
- 排除 `result` 后选中数据为 1,217,354 字节，减少约 43%。

这些数据只证明查询路径的改善，不把不同工作负载下的进程 CPU 快照当作同条件对照。

## 验证

- 前端与 Electron 完整回归：989 个文件、7451 项通过。
- 后端任务、面板、迁移与数据库安全：31 项通过。
- 新增索引/幂等迁移/无临时排序回归；新增列表与面板不读取 `result` 回归。
- 新增 Agent 空闲轮询、ComfyUI 降频恢复、发布器启动延迟与停止回归。
- 前端 oxlint、TypeScript、Electron typecheck、后端 ruff、`git diff --check` 通过。

## 本轮不做

编辑器 rAF、原文件高清静止帧与解码帧预算暂不修改。需要单独采集播放、scrub、多轨和 ComfyUI
同时打开时的 Performance trace，再决定是否进入下一阶段，避免无现场证据地改动音画同步链路。
