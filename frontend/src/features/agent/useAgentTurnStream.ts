import React from "react";
import { useQueryClient } from "@tanstack/react-query";

import { streamAgentTurn } from "@/api/domains/sessions";
import type { components } from "@/api/generated/schema";
import { readSseData } from "@/lib/sse";
import { parseServerTime } from "@/lib/time";
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
  /** 这一轮从什么时候开始跑(后端给的,不是「看到 running 的那一刻」)。还没收到第一帧时是 null。 */
  turnStartedAt: Date | null;
  /** 接上某个会话的流。重复接同一个是空操作。发送之后立刻接用它;跑着的会话不用调,这里自己接。 */
  attach: (sessionId: string) => Promise<void>;
};

/** 一条流结束了而会话还在跑 —— 下一轮已经(或马上)起来了 —— 隔这么久再接,别在两轮交接的
 *  那几毫秒里空转。 */
const REATTACH_DELAY_MS = 300;

/**
 * `viewedSessionId`:面板此刻显示的会话。流只属于它 —— 换成别的会话(不管是这个面板里点的、
 * 另一个面板里点的、还是浮标新建的),手上那条流就掐掉、流态清空。
 *
 * 规则放在这里而不是让面板在「切会话」的地方各调一次 reset:当前会话现在可以从面板外面换掉
 * (见 currentAgentSession),面板里已经没有一个"切会话"的时刻可以挂这一步。只掐**别的会话**
 * 的流:发送时新建的会话会先被选中、再接流,两步的先后不该让刚接上的流被自己掐掉。
 *
 * `running`:面板读到的会话状态。**跑着就接,一条流结束了还跑着就再接** —— 一条流只属于一轮
 * (后端换轮就关流),而一轮紧接一轮时(回执、答完问题、后端重启后重新起的一轮)会话一直是
 * running,看 running 的跳变来接流就永远接不上后面那一轮:界面停在上一轮最后那一行,
 * 「已用」一路累加(维护者截图:ask_user 一直转、已用 12 分钟,实际新的一轮早跑了很多步)。
 */
export function useAgentTurnStream(viewedSessionId: string | null, running: boolean): AgentTurnStream {
  const qc = useQueryClient();
  const [streamText, setStreamText] = React.useState("");
  const [streamTimeline, setStreamTimeline] = React.useState<AgentTimelineItem[]>([]);
  const [turnStartedAt, setTurnStartedAt] = React.useState<Date | null>(null);
  //: 自然结束(不是被掐)的流的个数。它一变,下面那个跟随的 effect 重看一眼:还在跑就再接。
  const [endedStreams, setEndedStreams] = React.useState(0);
  const streamingRef = React.useRef<string | null>(null);
  /**
   * 掐流用。读流的那个循环此前没有任何办法停下来:切会话或者卸载视图之后它**一直读下去**,
   * 每一条泄漏钉住一个 HTTP/1.1 连接 —— 过了浏览器每域名约六条的上限,应用里**其它每一个
   * 请求**都排在它们后面,表现是整个界面卡死。
   */
  const abortRef = React.useRef<AbortController | null>(null);
  const segmentRef = React.useRef(0);

  const reset = React.useCallback(() => {
    abortRef.current?.abort();
    streamingRef.current = null;
    setStreamText("");
    setStreamTimeline([]);
    setTurnStartedAt(null);
  }, []);

  // 卸载时一定要掐:这两个面板都是被条件挂载的,关掉它是常态而不是边缘情况。
  React.useEffect(() => () => abortRef.current?.abort(), []);

  React.useEffect(() => {
    if (streamingRef.current && streamingRef.current !== viewedSessionId) reset();
  }, [viewedSessionId, reset]);

  const attach = React.useCallback(
    async (targetSessionId: string) => {
      if (streamingRef.current === targetSessionId) return;
      abortRef.current?.abort(); // 切会话必须关掉上一条流
      const controller = new AbortController();
      abortRef.current = controller;
      streamingRef.current = targetSessionId;
      segmentRef.current = 0;
      setStreamText("");
      setStreamTimeline([]);
      setTurnStartedAt(null);
      try {
        for await (const data of readSseData(await streamAgentTurn(targetSessionId, controller.signal))) {
          let payload: StreamEvent;
          try {
            payload = JSON.parse(data) as StreamEvent;
          } catch {
            continue; // 一条坏事件不该让同一条流后面的更新全都失效
          }
          if (streamingRef.current !== targetSessionId) continue;
          const segment = Number(payload.segment ?? 0);
          if (segment !== segmentRef.current) {
            segmentRef.current = segment;
            // steer 被模型消费：上一段和插话已经落库，立即取回，避免实时气泡清空的空窗。
            void qc.invalidateQueries({ queryKey: ["agent-messages", targetSessionId] });
            void qc.invalidateQueries({ queryKey: ["agent-queue", targetSessionId] });
          }
          setStreamText(payload.text);
          setStreamTimeline((payload.timeline ?? []) as AgentTimelineItem[]);
          setTurnStartedAt(payload.started_at ? parseServerTime(payload.started_at) : null);
          if (payload.done) break;
        }
      } catch {
        // 流断了、被掐了、根本没连上,都不是要报给人看的错:调用方是 `void attach(...)`,而回合的
        // 真实状态由 agent-session 的轮询兜底 —— 没被掐的话,下面照样失效一遍把正式消息取回来。
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
          setTurnStartedAt(null);
          setEndedStreams((count) => count + 1);
          // 回合结束后计费事件才落库,而 usage-events 只在 running 时轮询 —— 不主动失效,
          // 这条回复的 token / 费用就一直缺。
          void qc.invalidateQueries({ queryKey: ["agent-usage-events", targetSessionId] });
        }
      }
    },
    [qc],
  );

  React.useEffect(() => {
    if (!running || !viewedSessionId) return;
    const timer = window.setTimeout(() => void attach(viewedSessionId), endedStreams ? REATTACH_DELAY_MS : 0);
    return () => window.clearTimeout(timer);
  }, [running, viewedSessionId, endedStreams, attach]);

  return { streamText, streamTimeline, turnStartedAt, attach };
}
