import type { MessageKey } from "@/app/messages";

type Translate = (key: MessageKey) => string;

/**
 * 「收件人」那一格里的值在界面上叫什么 —— 由**那一格的选项目录**回答(值 → 名字;不知道就返回空串)。
 *
 * 卡上写 `oc_01234…cdef` 和写「运营群」是两件事:前者是飞书系统里的编号,后者是人挑的时候在下拉里
 * 看见的那一行。名字只有目录知道(它现查后端),所以由画布那一层把目录取来喂进来 —— 和模型那一行
 * 现查生成选项(见 workflowCanvasModel 的 workflowNodeSubtitle)同一条做法。
 */
export type FeishuTargetNamer = (value: string) => string;

/**
 * 节点卡上那一行:**这个门(或这条消息)怎么发飞书**。
 *
 * 「等人确认」的飞书行为此前是**完全隐式**的:卡上什么也没写,人会以为它只在应用内等人的时候,
 * 它其实已经发了一张卡片出去 —— 而发到哪是运行时按"这次运行从哪来"猜的。飞书能力节点同理:
 * 一张卡上不写收件人,连线的人只能挨个点开检查器。
 *
 * 所以这一行说的是**节点上写着的那个选择**(channel / to / raw_id),不是"这一次会发到哪"
 * —— 后者要跑起来才知道(`origin` 那一档取决于这次运行从哪来)。写在卡上的作用正是让人一眼看出
 * 这个门被配成了什么,而配置在检查器里改。
 *
 * 只认这两个节点类型:别处没有"发飞书"这回事。句子在**这里**拼(前端的 t() 不做插值),
 * 词都在文案表里。
 */
export function feishuChannelSummary(
  nodeType: string,
  config: Record<string, unknown> | undefined,
  t: Translate,
  /** 收件人那一格的选项目录(值 → 名字)。不给就只写能分辨身份的那一截 id。 */
  names?: FeishuTargetNamer,
): string {
  if (nodeType !== "await_approval" && nodeType !== "feishu_message") return "";
  const values = config ?? {};
  //: 没写就是 `origin`(和后端 routing.channel_of 同一个缺省)—— 卡上不能因此什么都不说。
  const channel = String(values.channel ?? "").trim() || "origin";
  if (channel === "none") return t("wfFeishuStationOnly");
  if (channel === "origin") return t("wfFeishuOrigin");
  if (channel === "raw") {
    const typed = shortTarget(String(values.raw_id ?? ""));
    return typed ? `${t("wfFeishuRaw")} ${typed}` : t("wfFeishuRaw");
  }
  if (channel === "chat") {
    const room = targetLabel(String(values.to ?? ""), names);
    return room ? `${t("wfFeishuGroup")} ${room}` : t("wfFeishuGroup");
  }
  if (channel === "user") {
    //: `to` 是一段 `{{…}}` 引用时说不出是谁,说要给谁在检查器里挑 —— 卡上就写"发起人"这一类。
    const who = String(values.to ?? "").trim();
    const name = who && !who.includes("{{") ? targetLabel(who, names) : t("wfFeishuRequester");
    return `${t("wfFeishuDirect")} ${name}`;
  }
  return "";
}

/** 一格里的值怎么写:目录里有的写**名字**(人挑的时候看见的就是它),没有的照旧写 id —— 名字不编。 */
function targetLabel(value: string, names?: FeishuTargetNamer): string {
  const named = names ? names(value.trim()) : "";
  return named || shortTarget(value);
}

/** id 太长(open_id / chat_id 三十几位),卡上只放能分辨身份的那一截。 */
function shortTarget(value: string): string {
  const text = value.trim();
  if (!text || text.includes("{{")) return "";
  return text.length <= 18 ? text : `${text.slice(0, 8)}…${text.slice(-4)}`;
}
