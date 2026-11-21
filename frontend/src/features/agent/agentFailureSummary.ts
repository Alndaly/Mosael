/**
 * 失败那一轮,错误卡上该显示哪句话。
 *
 * 后端把**已经说出口的半截正文**放在 `content`,把给人看的失败说法放在
 * `payload.failure_text`。错误卡拿 `content` 当摘要,就会把「我先读一下技能……」印成失败原因,
 * 真正的「连接中断 / 授权过期」反而只剩在详情里。两个聊天面板共用这一处,别再分叉。
 */
export function agentFailureSummary(message: { content: string; payload?: unknown }): string {
  const failure = (message.payload as { failure_text?: unknown } | null | undefined)?.failure_text;
  return typeof failure === "string" && failure.trim() ? failure : message.content;
}
