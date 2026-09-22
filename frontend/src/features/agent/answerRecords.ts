/**
 * 一次选择在对话里**只画一遍**。
 *
 * 同一次作答会留下两份痕迹:
 *
 * 1. `ask_user` 那次工具调用的**结果** —— 阻塞那条路上,用户一选,答案就作为工具结果回到它
 *    被问的那个位置,留在时间线里;
 * 2. 后端送回会话的那条**回执消息**(domain/agent/questions.deliver_to_session)。
 *
 * 第二份不能撤:等待有上限(590s),用户去想一想再回来是常事;直连 MCP 的客户端根本不阻塞;
 * 后端重启也会把那一轮掐掉。这些情形下工具结果是 `pending`,回执是**唯一**的记录。
 *
 * 但阻塞那条路上两份都在,于是界面把同一个选择紧挨着画了两遍 —— 上面一张独立的卡,下面
 * `ask_user` 那一行展开还是它。
 *
 * **判据是查证,不是猜。** 「有没有一条 answered 的 ask_user」这种猜法错的方向是把唯一的
 * 那份痕迹也藏掉,而那正是这套设计一直在避免的失败(见 deliver_to_session 的说明:
 * 「看两遍看得见,也忽略得掉;掉进空里看不见」)。所以两边都带上 `question_id` 当钥匙,
 * 对得上才认为是同一件事。
 *
 * 放在共用模块里,是因为两个聊天面板(AI Studio 的 ChatWorkspace、画板的 CanvasAgentChat)
 * 都要用它 —— 各写一遍的话,这条规矩迟早在其中一个上失效。
 */
import type { AgentTimelineItem } from "@/features/agent/ToolCalls";
import { toolResultData } from "@/features/agent/toolResultShapes";

/** 时间线里 `ask_user` 已经记下答案的那些问题 id。 */
export function questionsRecordedByTools(timeline: readonly AgentTimelineItem[] | undefined): Set<string> {
  const recorded = new Set<string>();
  for (const item of timeline ?? []) {
    if (item.type !== "tool" || item.tool.name !== "ask_user") continue;
    // **要解包。** 时间线里存的是 pi 原样的 `AgentToolResult`(`{content, details}`),
    // 而给界面看的那一份在 `details.data` 里 —— 直接读 `tool.result` 拿到的是外壳。
    const result = toolResultData(item.tool.result);
    if (!result || typeof result !== "object") continue;
    const { status, question_id: questionId } = result as { status?: unknown; question_id?: unknown };
    // 只有 answered / dismissed 才算"记下了"。`pending` 说的正是"工具没等到" ——
    // 那时回执是唯一记录,必须画。
    if (typeof questionId !== "string" || !questionId) continue;
    if (status === "answered" || status === "dismissed") recorded.add(questionId);
  }
  return recorded;
}

/** 一串消息里,所有已经被 `ask_user` 结果记下的问题 id。 */
export function recordedQuestionIds(
  messages: readonly { payload?: unknown }[],
): Set<string> {
  const all = new Set<string>();
  for (const message of messages) {
    const timeline = (message.payload as { timeline?: AgentTimelineItem[] } | null)?.timeline;
    for (const id of questionsRecordedByTools(timeline)) all.add(id);
  }
  return all;
}

/**
 * 这条回执消息是不是多余的 —— 它说的那次选择,`ask_user` 的结果里已经有了。
 *
 * 只对**纯回执**成立:消息除了这次选择没别的内容(正文是后端生成的那句「我选好了:…」,
 * 给模型读的)。所以多余时整条不画,而不是只藏掉卡片留一句自述。
 */
export function isRedundantAnswerRecord(
  message: { payload?: unknown },
  recorded: ReadonlySet<string>,
): boolean {
  const answers = (message.payload as { answers?: { question_id?: string } } | null)?.answers;
  return Boolean(answers?.question_id && recorded.has(answers.question_id));
}
