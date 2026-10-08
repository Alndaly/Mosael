import React from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * 对话的消息**只在一轮跑着的时候轮询**;空闲时跟着会话本身动(智能体那一路 AGENT-11 第一步)。
 *
 * 此前 AI Studio 每 1.2 秒、各页面的助手面板每 1.5 秒**无条件**把整段消息重拉一遍 —— 停在那里不动也一样。消息里带着
 * 每一轮的时间线(工具调用和完整结果),维护者库里最大的一段 14 条消息 3.1 MB:打开它,界面一直在下载、解析、整段重渲。
 *
 * 空闲时消息只会因为**一轮**而变:发消息、任务回执、答选择卡都是先起一轮(状态变成 running → 这时开始轮询),一轮收尾时
 * 宿主把状态拨回 idle、`updated_at` 改成那一刻。会话详情本来就在轮询(它轻,也要靠它知道在不在跑),所以只要「状态或
 * `updated_at` 变了」就重取一次消息 —— 跑得太快、两次轮询之间就开始又结束的那一轮也接得住。窗口回到前台时照旧刷新。
 */
export const TRANSCRIPT_POLL_MS = 1500;

export function transcriptPolling(running: boolean): number | false {
  return running ? TRANSCRIPT_POLL_MS : false;
}

export function useTranscriptFollowsSession(
  sessionId: string,
  session: { status?: string | null; updated_at?: string | null } | null | undefined,
): void {
  const qc = useQueryClient();
  const mark = session ? `${session.status ?? ""}|${session.updated_at ?? ""}` : "";
  const seen = React.useRef<{ id: string; mark: string }>({ id: "", mark: "" });
  React.useEffect(() => {
    if (!sessionId || !mark) return;
    const last = seen.current;
    seen.current = { id: sessionId, mark };
    //: 刚换到这一段(或刚挂上):消息查询自己会取,不必再来一次。
    if (last.id !== sessionId || last.mark === mark) return;
    void qc.invalidateQueries({ queryKey: ["agent-messages", sessionId] });
  }, [qc, sessionId, mark]);
}
