import type { QueryClient } from "@tanstack/react-query";

import type { AgentSession } from "@/api/domains/sessions";

/**
 * 用户刚让一轮跑起来(发送 / 回答选择卡 / 继续发送)之后的缓存更新。
 *
 * 界面的「思考中」、接流和消息轮询都以 `agent-session.status === "running"` 为准;
 * 空闲会话的详情轮询是 10 秒,而这一轮其实在请求返回前就已经开始了。只失效消息或问题列表,
 * 界面会停在旧 `idle` 上:选择卡已经消失,进度却要等下一次空闲轮询才出现。
 *
 * 先乐观改成本地 `running` 让进度当帧出现,再失效三条缓存让服务端的真实状态(以及刚落库的
 * 用户消息、排队项)立即校正。发送、作答和语音输入都走这一份,别各写一遍。
 */
export function markAgentTurnStarted(qc: QueryClient, sessionId: string): void {
  qc.setQueryData<AgentSession>(["agent-session", sessionId], (current) =>
    current ? { ...current, status: "running" } : current,
  );
  void qc.invalidateQueries({ queryKey: ["agent-session", sessionId] });
  void qc.invalidateQueries({ queryKey: ["agent-messages", sessionId] });
  void qc.invalidateQueries({ queryKey: ["agent-queue", sessionId] });
}
