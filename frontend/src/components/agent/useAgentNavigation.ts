/**
 * 智能体要求界面跳到哪儿 —— 前端这一半。
 *
 * **方向是反的,所以不能走返回值。** 工具调用跑在后端,而切页面只有前端做得到。所以
 * `open_view` 把意图写在会话行的 `pending_view` 上,前端看见了才真的跳。
 *
 * **为什么不是 SSE。** 流只在助手面板开着、并且正在跑一轮的时候存在。免提浮标那种场景
 * 没有任何流 —— 而那恰恰是"带我过去"最有用的时候:手在别处、面板收起来了,你说一句
 * "去发布页看看",它总不能回一句"请你自己点左边第四个"。会话行两处都读得到。
 *
 * **消费一次:跳完由前端 DELETE。** 后端读一次就清的话,同时开着的两个界面里只有先轮询
 * 到的那个会跳,另一个永远不知道发生过什么。
 */

import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import { agentSessionSelectionKey } from "@/features/ai-studio/sessionSelection";

/**
 * 当前选中的助手会话 id。
 *
 * 存在 localStorage 里,而**同一个标签页里改它不触发 storage 事件** —— 所以除了监听
 * 事件(别的窗口改的)还得轮一下(本页面板换会话)。抽出来是因为浮标和导航都要它,
 * 各写一份的话总有一份会忘掉后半句,表现为"面板换了会话,浮标还在对旧的说话"。
 */
export function useSelectedAgentSessionId(workspaceId: string): string {
  const key = agentSessionSelectionKey(workspaceId);
  const [sessionId, setSessionId] = React.useState(() => window.localStorage.getItem(key) || "");
  React.useEffect(() => {
    const sync = () => setSessionId(window.localStorage.getItem(key) || "");
    sync();
    window.addEventListener("storage", sync);
    const timer = window.setInterval(sync, 2000);
    return () => {
      window.removeEventListener("storage", sync);
      window.clearInterval(timer);
    };
  }, [key]);
  return sessionId;
}

export function useAgentNavigation({
  workspaceId,
  onNavigate,
}: {
  workspaceId: string;
  /** 带我去这一页。`id` 目前只对 editor 有意义(打开那个项目)。 */
  onNavigate: (view: string, id: string) => void;
}) {
  const qc = useQueryClient();
  const sessionId = useSelectedAgentSessionId(workspaceId);

  //: **和浮标用同一个 queryKey**,所以这不是第三个轮询 —— react-query 按 key 合并,
  //: 两个观察者共享同一次请求。各起一个 key 的话,一个会话每 1.5 秒会被打两次。
  const session = useQuery({
    queryKey: ["agent-session", sessionId],
    queryFn: () => api<{ pending_view?: string }>(`/api/agent/sessions/${sessionId}`),
    enabled: Boolean(sessionId),
    refetchInterval: 1500,
  });

  const pending = session.data?.pending_view ?? "";
  //: 同一条待跳转在被 DELETE 掉之前还会被轮询读回来几次(请求在飞的那段时间)。
  //: 不记下来的话,同一次"带我过去"会连着跳三四次 —— 而副作用是把用户在这几百毫秒里
  //: 自己点开的页面又抢回去。
  const doneRef = React.useRef("");
  const navigateRef = React.useRef(onNavigate);
  navigateRef.current = onNavigate;

  React.useEffect(() => {
    if (!sessionId || !pending) return;
    const stamp = `${sessionId}:${pending}`;
    if (doneRef.current === stamp) return;
    doneRef.current = stamp;
    const [view, id = ""] = pending.split(":");
    navigateRef.current(view, id);
    void api(`/api/agent/sessions/${sessionId}/view`, { method: "DELETE" })
      // 清失败就让它下一轮再来一次:重复跳到同一页是小事,跳不动才是大事。
      .catch(() => (doneRef.current = ""))
      .finally(() => void qc.invalidateQueries({ queryKey: ["agent-session", sessionId] }));
  }, [pending, sessionId, qc]);
}
