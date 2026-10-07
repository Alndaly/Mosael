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
 * **盯的是眼下这一处的当前对话**(ADR 0044 §6):`useActivePlace()` 那一处的。跳之前递一根接力棒
 * (`passConversation`):跳过去之后第一个变成「眼下这一处」的地方接住这段对话,多页面的活不断;你自己点过去的
 * 没有棒子,面板显示那一处自己的对话。同事共享来、只能看的那段不跟:那是智能体带**主人**过去,看的人不该被拽走,
 * 也清不掉它(清是写)。
 *
 * **过期的「带我过去」不跟。** 一段对话可能在你离开的那一处接着跑、要求跳转时没人盯着 —— 你一分钟后回去看结果,
 * 不该被拽走。`pending_view_at` 超过 30 秒的,清掉、不跳。
 *
 * **消费一次:跳完由前端 DELETE。** 后端读一次就清的话,同时开着的两个界面里只有先轮询
 * 到的那个会跳,另一个永远不知道发生过什么。
 */

import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, getAgentSession } from "@/api/client";
import { passConversation, useActivePlace } from "@/features/agent/activePlace";
import { useCurrentAgentSession } from "@/features/agent/currentAgentSession";
import { parseServerTime } from "@/lib/time";

/** 要求了多久以内的跳转还跟。 */
export const PENDING_VIEW_FRESH_MS = 30_000;

export function useAgentNavigation({
  workspaceId,
  onNavigate,
}: {
  workspaceId: string;
  /** 带我去这一页。`id` 选中那一页里的哪一样(项目、笔记、场景、素材库条目、画板、工作流)。 */
  onNavigate: (view: string, id: string) => void;
}) {
  const qc = useQueryClient();
  const place = useActivePlace();
  const current = useCurrentAgentSession(workspaceId, place);
  const sessionId = current.readOnly ? "" : current.session?.id ?? "";

  //: **和面板、浮标用同一个 queryKey**,所以这不是又一个轮询 —— react-query 按 key 合并,
  //: 几个观察者共享同一次请求。各起一个 key 的话,一个会话每 1.5 秒会被打好几次。
  const session = useQuery({
    queryKey: ["agent-session", sessionId],
    queryFn: () => getAgentSession(sessionId),
    enabled: Boolean(sessionId),
    refetchInterval: 1500,
  });

  const pending = session.data?.pending_view ?? "";
  const askedAt = session.data?.pending_view_at ?? null;
  //: 同一条待跳转在被 DELETE 掉之前还会被轮询读回来几次(请求在飞的那段时间)。
  //: 不记下来的话,同一次"带我过去"会连着跳三四次 —— 而副作用是把用户在这几百毫秒里
  //: 自己点开的页面又抢回去。
  const doneRef = React.useRef("");
  const navigateRef = React.useRef(onNavigate);
  navigateRef.current = onNavigate;

  React.useEffect(() => {
    if (!sessionId || !pending) return;
    const stamp = `${sessionId}:${pending}:${askedAt ?? ""}`;
    if (doneRef.current === stamp) return;
    doneRef.current = stamp;
    const fresh = !askedAt || Date.now() - parseServerTime(askedAt).getTime() <= PENDING_VIEW_FRESH_MS;
    if (fresh) {
      const [view, id = ""] = pending.split(":");
      // 先递棒子再跳:跳过去的页面一登记就接得住。
      passConversation(workspaceId, sessionId);
      navigateRef.current(view, id);
    }
    void api(`/api/agent/sessions/${sessionId}/view`, { method: "DELETE" })
      // 清失败就让它下一轮再来一次:重复跳到同一页是小事,跳不动才是大事。
      .catch(() => (doneRef.current = ""))
      .finally(() => void qc.invalidateQueries({ queryKey: ["agent-session", sessionId] }));
  // dataUpdatedAt makes a failed DELETE retry after the invalidation refetches the same pending
  // value. Depending on `pending` alone cannot observe that refetch because the string is unchanged.
  }, [pending, askedAt, sessionId, workspaceId, qc, session.dataUpdatedAt]);
}
