import { Box, FileText, Image, Workflow as WorkflowIcon, type LucideIcon } from "lucide-react";

import type { MessageKey } from "@/app/messages";
import { listAssets, listBoards, listWorkflows } from "@/api/client";
import { listNotes } from "@/api/domains/notes";

/**
 * 聊天里 `@` 得到的东西:**工作区里一个具体的对象**,不是一段字。
 *
 * ## 正文写名字,id 走结构化字段
 *
 * chip 序列化成 `@名字` —— 那是给模型读的句子,`把 @运镜练习 的第三个镜头改长一点` 读起来
 * 就是人话。而 id 单独收进 `references` 交给后端:名字会重、会改、会有空格,拿它当标识
 * 迟早出事;把 32 位十六进制塞进正文又会把真正的句子挤没。两件事分开做,各自都对。
 *
 * ## 为什么四类共用一个节点类型
 *
 * 画布那边(PromptEditor)是 `assetRef` 一个节点、只认素材。四类各造一个节点的话,
 * 序列化、渲染、升级旧文档、收集 id —— 每一处都要写四遍 switch,而它们的差别只有
 * "图标长什么样"和"去哪儿搜"。所以节点只有一个,`kind` 是它的属性。
 */
export const REFERENCE_KINDS = ["asset", "note", "board", "workflow"] as const;
export type ReferenceKind = (typeof REFERENCE_KINDS)[number];

export interface AgentReference {
  kind: ReferenceKind;
  id: string;
  /** 写进正文的那个名字。存下来是为了**旧消息也能渲染** —— 对象改名或删掉之后,
   *  气泡里至少还说得出当时引用的是什么,而不是变成一个空 chip。 */
  name: string;
}

/** 每一类怎么找、长什么样。加一类就在这里加一行,别处不用改。 */
export const REFERENCE_META: Record<ReferenceKind, { icon: LucideIcon; labelKey: MessageKey }> = {
  //: 分组标题用**侧边栏那套名字** —— 用户在导航里认得的就是这几个词,菜单里换一套说法
  //: 只会让他去想"素材库和素材是不是两个东西"。
  asset: { icon: Image, labelKey: "mediaTitle" },
  note: { icon: FileText, labelKey: "navNotes" },
  board: { icon: Box, labelKey: "navBoards" },
  workflow: { icon: WorkflowIcon, labelKey: "navWorkflows" },
};

/**
 * 菜单里一次摆几条。**配额按它均分给四类,菜单也按它截断 —— 所以只能有一个数。**
 *
 * 此前是两个:候选按"limit 的四倍"去取(每类配额 12),菜单再截到 12 条。素材通常就有
 * 12 条以上,于是它一家占满前 12 条,笔记/画板/工作流一条都露不出来 —— 封顶写了,却封在
 * 屏幕装不下的地方。两个数各自看都合理,凑一起才出事,而这种错写测试盯着也容易盯漏
 * (盯的是函数,漏的是调用点)。所以现在只有这一个常量,两边都从这儿取。
 */
export const REFERENCE_MENU_LIMIT = 12;

/** 一次候选查询的结果。名字为空的对象照样能引用 —— 拿它的 id 兜底,总比不出现好。 */
export async function searchReferences(workspaceId: string, query: string): Promise<AgentReference[]> {
  const needle = query.trim().toLowerCase();
  const matches = (name: string) => !needle || name.toLowerCase().includes(needle);
  // 四类并发问,慢的那一类不拖住其余的。任何一类挂掉只丢它自己(菜单是辅助,不该整块消失)。
  const [assets, notes, boards, workflows] = await Promise.all([
    listAssets(workspaceId).catch(() => []),
    listNotes(workspaceId, query).catch(() => []),
    listBoards(workspaceId).catch(() => []),
    listWorkflows(workspaceId).catch(() => []),
  ]);
  const out: AgentReference[] = [];
  const push = (kind: ReferenceKind, id: string, name: string) => {
    if (id && matches(name)) out.push({ kind, id, name: name || id.slice(0, 8) });
  };
  for (const asset of assets) push("asset", asset.id, asset.name || asset.original_filename || "");
  for (const note of notes) push("note", note.id, note.title || "");
  for (const board of boards) push("board", board.id, board.name || "");
  for (const flow of workflows) push("workflow", flow.id, flow.name || "");
  // **按类成段**,不再轮转:菜单是分组显示的(每组一个标题),轮转会把同一类拆散到各处。
  // 每类各自封顶,免得素材把其余三类挤出屏幕 —— 素材通常最多,不封顶的话笔记和工作流
  // 永远露不了面,用户会以为只能引用素材。
  const perKind = Math.max(2, Math.floor(REFERENCE_MENU_LIMIT / REFERENCE_KINDS.length));
  return REFERENCE_KINDS.flatMap((kind) => out.filter((one) => one.kind === kind).slice(0, perKind));
}
