# 0084 插话在模型消费边界切段

- 状态：已采纳
- 日期：2026-10-26

## 背景

智能体运行中，用户可以把一条排队消息“插入当前轮”。此前点下按钮后立刻把它移出队列，写成普通 user 消息，并改写 `created_at`；而一轮只产生一条 assistant 草稿，所有正文、思考和工具都在同一条 `payload.timeline` 里。

结果是转录只能按 `created_at` 排序：插话落在整轮回答之后，刷新前后都无法表达「插话前做了什么 → 用户改口 → 插话后怎么继续」。仅靠前端乐观插入或调整时间戳都无法修复，因为持久化模型里没有段边界。

## 决策

### 两种用户意图

- **排到下一轮**：消息保持 `queued`，当前轮结束后由队列 drain 开新 turn。
- **插入当前轮**：先进入 `pending_steer`。这不是 transcript 消息，也不出队。

### sidecar 确认消费

`steer` 请求携带稳定的 `steerId`（就是队列消息 id）。sidecar 的 `queued pending=true` 只表示“已接住请求”，不能当成已插入。

pi 真正把这条 user 消息放进模型上下文时，sidecar 发 `steer_applied { turnId, steerId }`。这一点由 `agent-sidecar/test/steer-applied.test.mjs` 用真实 pi Agent 钉住。

### 后端切段

收到 `steer_applied` 后，按顺序：

1. 冻结当前 assistant 草稿的正文和 timeline，作为独立 assistant 段落库；
2. 把 pending steer 移出队列，`created_at` 改成这一刻，作为 user 消息落库；
3. 从空正文、空 timeline 开始新的 assistant 草稿，继续同一个 turn；
4. 实时流 `segment` 加一并向 SSE 客户端公布。

因此顺序固定为：

```text
assistant 段 1（插话前的正文/思考/工具）
user 插话
assistant 段 2（插话后的继续执行）
```

在消费前取消 pending steer，会同时重声明 sidecar 的 steering queue；消费后的消息是普通对话历史，不可撤回。

## 为什么不改数据库 schema

一次 turn 内的段边界由多条 `AgentMessage` 的持久顺序表达：旧 assistant 草稿保持原 `created_at`，user 在边界时刻落库，新草稿在其后创建。现有 `created_at` 排序已经能稳定表达顺序，不需要给历史消息补 `turn_id/sequence`，也不需要维护两套读取分支。

旧对话保持“一轮一条 assistant 消息”的历史表示，这是准确的，不需要迁移成虚假的段。

## 后果

- 前端队列条必须区分 `queued`、`held`、`pending_steer`；pending 不再显示第二个“插话”按钮。
- SSE 必须携带 `segment`；段号变化时立即失效 messages/queue 查询，避免实时气泡和持久消息短暂错位。
- 任何绕过 `steer_applied`、直接 `_unqueue` 的实现都会重新引入“整轮之后才出现插话”的问题。
- 多段 assistant 的 usage 归属最后一段；若插话后模型没有输出，usage 归上一段，不生成空气泡。
