import React from "react";
import { useQueryClient } from "@tanstack/react-query";

import { API_BASE, getAuthToken } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { readSseData } from "@/lib/sse";
import type { AgentTimelineItem } from "@/features/agent/ToolCalls";

/**
 * 「连流 → 攒状态 → 收尾失效」这一段状态机 —— **只有这一份**。
 *
 * 两个聊天面板(AI 工作台的 `ChatWorkspace`、画布/工作流的 `CanvasAgentChat`)是同一个东西
 * 的两个入口:它们已经共享了二十多个 `features/agent/*` 组件,唯独这段各写了一遍。而它**已经
 * 分岔**:
 *
 * · 收尾那一步,工作台改成了 `await Promise.all([...])` 两条失效一起 settle,旁边一段长注释
 *   解释为什么必须这样(让 running 转 false 与正式消息出现落在**同一帧**,否则答完一句会闪
 *   一下);画布助手走的是没修之前的 `void` 各发各的 —— 也就是说**画布助手每答完一句仍然
 *   闪一下**,而那个 bug 在隔壁文件里被诊断过、注释过、修好过;
 * · 事件形状两边各写一份 `as {...}` 断言,画布那份**没有 `done`**。`as` 绕过类型检查:少写
 *   一个字段不报错,多写一个也不报错。
 *
 * 修一处漏一处是必然的 —— 这次是收尾,下次就是断线重连或者取消。
 *
 * **`done` 现在真的被读**:它是后端明确发出的结束信号,而此前两个客户端都靠"流关了"来推断
 * (功能上等价,因为后端发完 done 就 break)。一个字段在协议里、在一侧的类型断言里,而没有
 * 任何一处读它 —— 那种字段迟早会被当成可以删的。读它还多一个好处:流被中间设备拖着不关时,
 * 我们不用干等。
 */
type StreamEvent = components["schemas"]["AgentStreamEvent"];

export type AgentTurnStream = {
  /** 这一轮到此刻的正文。没有在跑时是空串。 */
  streamText: string;
  /** 这一轮到此刻的执行轨迹。 */
  streamTimeline: AgentTimelineItem[];
  /** 接上某个会话的流。重复接同一个是空操作。 */
  attach: (sessionId: string) => Promise<void>;
  /** 掐掉当前的流并清空流态(切会话、关面板时用)。 */
  reset: () => void;
};

export function useAgentTurnStream(): AgentTurnStream {
  const qc = useQueryClient();
  const [streamText, setStreamText] = React.useState("");
  const [streamTimeline, setStreamTimeline] = React.useState<AgentTimelineItem[]>([]);
  const streamingRef = React.useRef<string | null>(null);
  /**
   * 掐流用。读流的那个循环此前没有任何办法停下来:切会话或者卸载视图之后它**一直读下去**,
   * 每一条泄漏钉住一个 HTTP/1.1 连接 —— 过了浏览器每域名约六条的上限,应用里**其它每一个
   * 请求**都排在它们后面,表现是整个界面卡死。
   */
  const abortRef = React.useRef<AbortController | null>(null);

  const reset = React.useCallback(() => {
    abortRef.current?.abort();
    streamingRef.current = null;
    setStreamText("");
    setStreamTimeline([]);
  }, []);

  // 卸载时一定要掐:这两个面板都是被条件挂载的,关掉它是常态而不是边缘情况。
  React.useEffect(() => () => abortRef.current?.abort(), []);

  const attach = React.useCallback(
    async (targetSessionId: string) => {
      if (streamingRef.current === targetSessionId) return;
      abortRef.current?.abort(); // 切会话必须关掉上一条流
      const controller = new AbortController();
      abortRef.current = controller;
      streamingRef.current = targetSessionId;
      setStreamText("");
      setStreamTimeline([]);
      try {
        const token = getAuthToken();
        const response = await fetch(`${API_BASE}/api/agent/sessions/${targetSessionId}/stream`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        });
        if (!response.ok || !response.body) return;
        for await (const data of readSseData(response.body)) {
          let payload: StreamEvent;
          try {
            payload = JSON.parse(data) as StreamEvent;
          } catch {
            continue; // 一条坏事件不该让同一条流后面的更新全都失效
          }
          if (streamingRef.current !== targetSessionId) continue;
          setStreamText(payload.text);
          setStreamTimeline((payload.timeline ?? []) as AgentTimelineItem[]);
          if (payload.done) break;
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        // 被中止的流是被替换或卸载了 —— 接手的那个现在拥有状态,这里再去失效就是给一个
        // 可能已经不存在的视图重新取数。
        if (streamingRef.current === targetSessionId && !controller.signal.aborted) {
          streamingRef.current = null;
          // 临时流式气泡的显示条件是 running(来自 agent-session 状态)&& streamText。要消除
          // 「回答完成那一刻整页闪烁」,得让 running 转 false(气泡消失)与正式消息出现落在
          // **同一帧**:一起 await messages + session 的 refetch,两者同时 settle → React 批处理
          // 同帧重渲染,正式气泡就位的同刻临时气泡消失,无空白也无重复。之后再清 streamText
          // 只是收尾(气泡已因 running 消失)。
          //
          // 这段此前只在工作台那一份里有,画布助手每答完一句都会闪一下。
          await Promise.all([
            qc.invalidateQueries({ queryKey: ["agent-messages", targetSessionId] }),
            qc.invalidateQueries({ queryKey: ["agent-session", targetSessionId] }),
          ]);
          setStreamText("");
          setStreamTimeline([]);
          // 回合结束后计费事件才落库,而 usage-events 只在 running 时轮询 —— 不主动失效,
          // 这条回复的 token / 费用就一直缺。
          void qc.invalidateQueries({ queryKey: ["agent-usage-events", targetSessionId] });
        }
      }
    },
    [qc],
  );

  return { streamText, streamTimeline, attach, reset };
}
