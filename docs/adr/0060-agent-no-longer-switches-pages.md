# ADR 0060:智能体不再带用户跳页 —— 撤掉 `open_view`

## Status

Accepted — 2026-10-14。维护者拍板(原话):「去掉智能体在Mosael内部的页面切换能力 这个反而触发了一些干扰 后续我会做ComputerUse能力
可以直接解决这种页面切换问题」。取代 ADR 0044 第 6 条(「智能体带着走」);ADR 0007 决定 2、ADR 0055 §9 里提到 `open_view` 的那几处随之作废。

## Context

`open_view(view, id)` 是一个直接执行的工具:智能体把「带用户去哪」写在会话行的 `pending_view`(连同 `pending_view_at`)上,前端
`useAgentNavigation` 每 1.5 秒轮询当前对话,看见了就切页、递一根接力棒让落脚的那一处接上这段对话(ADR 0044 §6),再 `DELETE` 掉。

实际用下来它是干扰:页面在人眼前被换掉,换到的未必是他要看的;为了不乱拽,又陆续加了 30 秒过期、只读会话不跟、子智能体不给、
接力棒的几种等待和作废 —— 一个「顺手带过去」的便利,换来一条横跨后端、数据库、前端三层、要靠一堆时序规则才不出错的链路。
维护者另有计划:由 Computer Use 能力直接操作界面,页面切换归它。

## Decision

**整条链路删掉,不留空壳。**

- 后端:`mcp_server.open_view` 和它的白名单 `_VIEWS`;`AgentPendingView`;`use_cases.set_pending_view` / `clear_pending_view`;
  `POST`/`DELETE /api/agent/sessions/{id}/view`;会话出参的 `pending_view`、`pending_view_at`、`pending_view_age_seconds`。
- 数据:`agent_sessions.pending_view`、`pending_view_at` 两列由迁移 `drop-agent-pending-view` 删掉(排在重建这张表的
  `drop-agent-sessions-project-id` 之前 —— 重建的守卫认不出模型上没有的列就拒绝动手)。
- 前端:`useAgentNavigation`;`activePlace` 里的接力棒(`passConversation`)。登记处(`useAgentPlace` / `useActivePlace`)留着,免提浮标用它。
- sidecar:子智能体工具清单里对 `open_view` 的排除没有对象了,一并去掉。
- 契约 `contracts/studio-views.json` 留着:`mosael://` 深链白名单和前端导航仍按它把关,只是少了智能体那一侧。

**保留的:**

- 深链本身(`#/ai?session=`、`#/entities?entity=`、工作流 id……)—— 任务中心「前往」、资产「在哪里用过」、`mosael://` 都走它。
- `generate_*` 回执里的 `session_id`:模型据此告诉用户这一张落在 AI Studio 创作里的哪一条。
- 工作台里智能体开新标签页时新标签页接住这段对话(ADR 0044 §6 最后一条、`followPlaces`):那是画布内部的动作,
  走「后端 → 主进程 → 页面」,不是切 Mosael 的页面,也从来不经过 `pending_view`。
- 0044 第 6 条的另一半照旧成立:你自己点到哪,面板就显示那一处自己的对话。

## Consequences

- 智能体回答「在哪」时只能用话说清楚是哪一页、哪一条,由人自己点过去 —— 直到 Computer Use 能力接手。
- 飞书 / 外部客户端原本就跳不了,行为不变。
- 已装机的库升级时两列被删(schema 号见 `backend/app/db/safety.py`);没有兼容分支。
