/**
 * 子智能体:把一段独立的调查派出去做,只把结论带回来。
 *
 * **它解决的是上下文而不是算力问题**。"把这 40 个素材都看一遍找出适合做片头的那个"——
 * 真正有用的只有最后那句结论,而 40 次 analyze_asset 的完整返回会把主对话的上下文占满,
 * 逼出一次压缩,后面用户再问别的时,早先的对话已经被摘要掉了。子智能体有自己的消息数组,
 * 中间过程留在它那里,主对话只收到一段报告。Claude Code 的 Task、Codex 的子会话是同一个思路。
 *
 * **跑在同一个进程里**,不另起 sidecar:它要用的 models/streamFn 已经在手上,再开一个进程
 * 就得把供应商解析、凭据、代理整套再传一遍,而它们随时可能不一致。
 *
 * **只给只读工具**。这是有意的限制,不是没做完:
 *   ① 确认卡是对**用户**说"要不要让它做这件事",而卡上写的是发起方——一张由用户看不见的
 *      子智能体发起的卡,用户没有上下文可以判断该不该批;
 *   ② 子智能体阻塞在确认卡上时,主智能体也跟着卡在那次工具调用里,而界面上没有任何地方
 *      能说清"现在在等谁";
 *   ③ 调查任务本来就不需要写权限。要改动仍然由主智能体自己来,那条路径上用户看得见全过程。
 */
import { Agent, type AgentMessage, type AgentTool } from "@earendil-works/pi-agent-core";
import type { Api, Model } from "@earendil-works/pi-ai";

import { log } from "./protocol.js";

/** 子智能体最多跑多少轮工具循环。跑不完就带着已有的发现回来 —— 无声地转下去更糟。 */
const MAX_STEPS = 24;

const SUBAGENT_PROMPT = `你是一个子智能体,被主智能体派来独立完成一段调查任务。

你只有**只读**工具:可以查素材、看时间线、读知识库、搜网页、分析素材,但**不能**做任何修改
(不能改时间线、不能生成、不能发布)。遇到需要修改的情况,把它写进结论让主智能体去做。

你的输出会被原样交给主智能体,它看不到你的中间过程。所以:
- 直接给结论和证据,不要复述你调用了哪些工具;
- 带上后续会用到的具体标识(素材 id、序列 id、文档 id、链接);
- 没查到就明确说没查到,不要猜 —— 主智能体会把你的话当事实用。`;

/** 只读工具的判据:manifest 的 read_only 标记。名单在后端(唯一工具注册表),这边不再维护
 *  第二份名字清单 —— 那种清单漂移过一次,代价是十九个工具静默消失。
 *
 *  判据一路收紧过两次。最早是"没有确认门就算只读",插件工具因此被整批当成只读。后来插件改成
 *  只认 manifest 里的声明,但内置工具仍然按"非确认门"**算**——而那句"会改东西的都走确认卡"
 *  是错的:browser_type / click / upload / evaluate 都不走卡(入口那张卡走过一次),于是子智能体
 *  拿得到它们,而池会话用的是用户在别人站点上的真实登录身份。现在内置工具也是**显式声明**
 *  (后端 mcp_server.READ_ONLY_TOOLS),漏声明的一律算会改东西。 */
export function readOnlyTools(tools: AgentTool[]): AgentTool[] {
  return tools.filter((tool) => (tool as { readOnly?: boolean }).readOnly === true && tool.name !== "run_subagent");
}

/**
 * 跑一个子智能体,返回它的最终报告。
 *
 * 失败不抛给主智能体的工具调用之外:子任务失败是**结果的一种**,主智能体应当读到"没做成、
 * 原因是什么"并据此决定下一步,而不是整轮对话跟着崩掉。
 */
/** 子智能体内部一步工具调用的实时上报。start 带参数,end 带结果 —— 主时间线据此
 *  在 run_subagent 卡下面嵌套显示"它此刻在干什么",而不是一段几十秒的静默。 */
export type SubagentToolEvent =
  | { phase: "start"; toolCallId: string; toolName: string; args: unknown }
  | { phase: "end"; toolCallId: string; toolName: string; result: unknown; isError: boolean };

/** 子智能体轨迹里的一条:它自己的阶段性文字,或一步工具调用。给 UI 存档用 ——
 *  **不回填给主模型**(那正是子智能体要省的上下文),只让人能事后查看它做了什么。 */
export type SubagentTraceItem =
  | { type: "text"; text: string }
  | { type: "tool"; id: string; name: string; args: unknown; result?: unknown; isError?: boolean };

export async function runSubagent(input: {
  task: string;
  tools: AgentTool[];
  model: Model<Api>;
  streamFn: any;
  signal?: AbortSignal;
  onToolEvent?: (event: SubagentToolEvent) => void;
}): Promise<{ report: string; steps: number; trace: SubagentTraceItem[]; error?: string }> {
  const agent = new Agent({
    initialState: {
      systemPrompt: SUBAGENT_PROMPT,
      model: input.model,
      tools: input.tools,
      messages: [],
      thinkingLevel: "off",
    },
    streamFn: input.streamFn,
    // 步数上限:子智能体没人盯着,转不出来时要能自己停下并交代进展。
    transformContext: async (messages: AgentMessage[]) => {
      const toolTurns = messages.filter((m) => m.role === "assistant").length;
      if (toolTurns > MAX_STEPS) {
        return [
          ...messages,
          { role: "user", content: "已达到步数上限。立刻停止调用工具,用现有发现写出结论。" } as AgentMessage,
        ];
      }
      return messages;
    },
  });

  let steps = 0;
  const trace: SubagentTraceItem[] = [];
  agent.subscribe((event: any) => {
    if (event?.type === "tool_execution_start") {
      steps += 1;
      trace.push({ type: "tool", id: String(event.toolCallId ?? ""), name: String(event.toolName ?? ""), args: event.args });
      input.onToolEvent?.({ phase: "start", toolCallId: String(event.toolCallId ?? ""), toolName: String(event.toolName ?? ""), args: event.args });
    } else if (event?.type === "tool_execution_end") {
      const entry = trace.find((item) => item.type === "tool" && item.id === String(event.toolCallId ?? ""));
      if (entry && entry.type === "tool") {
        entry.result = event.result;
        entry.isError = Boolean(event.isError);
      }
      input.onToolEvent?.({ phase: "end", toolCallId: String(event.toolCallId ?? ""), toolName: String(event.toolName ?? ""), result: event.result, isError: Boolean(event.isError) });
    } else if (event?.type === "message_end") {
      // 子智能体自己的阶段性文字也进轨迹:没有它,存档只是一串工具调用,
      // 看不出它每一步**为什么**这么查。
      const message = event.message as { role?: string; content?: unknown } | undefined;
      if (message?.role === "assistant" && typeof message.content === "string" && message.content.trim()) {
        trace.push({ type: "text", text: message.content });
      }
    }
  });

  try {
    await agent.prompt(input.task);
  } catch (err) {
    const message = String(err);
    log("subagent failed:", message);
    return { report: "", steps, trace, error: message };
  }
  // AgentMessage 是个联合类型(assistant / toolResult / bash 执行…),不是每一支都有 content。
  // 取最后一条**带文本正文**的 assistant 消息 —— 那就是它写给主智能体的结论。
  const messages = (agent.state?.messages ?? []) as AgentMessage[];
  const report = [...messages]
    .reverse()
    .map((message) => {
      const record = message as { role?: string; content?: unknown };
      return record.role === "assistant" && typeof record.content === "string" ? record.content.trim() : "";
    })
    .find((text) => text.length > 0) ?? "";
  if (!report) return { report: "", steps, trace, error: "子智能体没有产出结论" };
  return { report, steps, trace };
}

/** 主智能体看到的那个工具。参数刻意只有两个 —— 派活儿要说清「做什么」和「要什么结果」,
 *  再多的旋钮只会让主智能体去调参而不是描述任务。 */
export function subagentToolSpec(): { name: string; description: string; parameters: Record<string, unknown> } {
  return {
    name: "run_subagent",
    description:
      "Delegate a self-contained investigation to a sub-agent with its own context, and get back only its conclusion. " +
      "Use when the work would otherwise flood this conversation with intermediate output: scanning many assets, " +
      "reading many documents, researching across many pages. The sub-agent has READ-ONLY tools — it cannot edit the " +
      "timeline, generate media or publish, so do not delegate changes. It cannot ask you questions, so the task must " +
      "be self-contained: say what to look at, what to decide, and what to report back.",
    parameters: {
      type: "object",
      properties: {
        task: {
          type: "string",
          description:
            "The full task, self-contained. Include the concrete ids/paths to look at and exactly what to report back.",
        },
        expected_output: {
          type: "string",
          description: "What the answer should look like, e.g. 'the asset id plus one sentence of reasoning'.",
        },
      },
      required: ["task"],
    },
  };
}
