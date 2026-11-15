import React from "react";

/**
 * 这一轮已经跑了多少秒 —— 两个聊天面板「已用 …」的唯一来源。
 *
 * 起点是**后端给的这一轮开始时间**(`turnStartedAt`,见 useAgentTurnStream),不是「面板看到
 * running 的那一刻」:刷新页面从 0 重新数是错的;一轮紧接一轮(回执、答完问题)时会话一直是
 * running,按跳变数的话是几轮加起来的时长(维护者截图里的「已用 12m」)。
 *
 * 第一帧还没到时先从此刻数起,到了就换成真正的起点。
 */
export function useTurnElapsedSeconds(running: boolean, turnStartedAt: Date | null): number {
  const [now, setNow] = React.useState(() => Date.now());
  const [seenAt, setSeenAt] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!running) return;
    setSeenAt(Date.now());
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  if (!running) return 0;
  const start = turnStartedAt?.getTime() ?? seenAt;
  return Math.max(0, Math.floor((now - start) / 1000));
}
