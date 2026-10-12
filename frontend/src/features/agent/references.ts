import { Box, FileText, Image, Workflow as WorkflowIcon, type LucideIcon } from "lucide-react";

import type { MessageKey } from "@/app/messages";
import { listAssetPage, listBoards, listWorkflows } from "@/api/client";
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
 * 菜单里**每一类**最多摆几条。取回和显示都从这一个数来 —— **只能有一个数**。
 *
 * 此前是两个:候选按"上限的四倍"去取(每类 12),菜单再截到 12 条。素材通常就有 12 条以上,
 * 于是它一家占满前 12 条,笔记/画板/工作流一条都露不出来 —— 封顶写了,却封在屏幕装不下的地方。
 * 两个数各自看都合理,凑一起才出事。所以只留这一个常量,取和摆都从这儿取。
 *
 * **6 是量出来的**(别再随手改):一行 40px、一个分组抬头 23px,菜单上限 360px(见 ChatComposer
 * 那个 max-h)。一类 6 条 = 263px,加上下一组的抬头(23px)和它第一条(40px)仍在第一屏里 ——
 * 用户一眼看得见"下面还有别的类";素材再多也挤不掉其余三类(这正是这行封顶的理由)。
 *
 * 它**不是**"一屏只放得下这么多":菜单自己会滚(上限是高度,不是条数),一类再多就滚着看,
 * 而这个数之外的条数由菜单底部那行「还有 N 个」如实说出来(见 ChatComposer 的 footer 与 matched)。
 */
export const REFERENCE_KIND_LIMIT = 6;

/**
 * 一次候选查询的结果:**要摆的那几条**,加**每一类匹配到的真数**。
 *
 * 两个都要带回来。菜单底部那行「还有 N 个」说不了假话,而 `items.length` 顶替不了它:素材是
 * 服务端按 `limit` 取的(一个 312 份素材的工作区只取回 6 条),取回来的条数根本不是匹配数 ——
 * 此前那个"每组只显示 3 条、一个字都不说"就是这么来的:真数在 slice 那一步被丢掉了。
 */
export interface ReferenceCandidates {
  /** 按类成段(素材 → 笔记 → 画板 → 工作流,见下面 return),每类最多 `REFERENCE_KIND_LIMIT` 条。 */
  items: AgentReference[];
  /** 每一类**匹配到的一共多少条**(截断前)。没匹配到的记 0。 */
  matched: Record<ReferenceKind, number>;
}

/** 一条都没匹配上。菜单没开时的初值,也是替身(`search=` 那个口子)最常用的那一份 ——
 *  四处手抄 `{ asset: 0, note: 0, board: 0, workflow: 0 }`,迟早有一处漏一类。 */
export const NO_REFERENCES: ReferenceCandidates = {
  items: [],
  matched: { asset: 0, note: 0, board: 0, workflow: 0 },
};

/** 一次候选查询。名字为空的对象照样能引用 —— 拿它的 id 兜底,总比不出现好。 */
export async function searchReferences(workspaceId: string, query: string): Promise<ReferenceCandidates> {
  const needle = query.trim().toLowerCase();
  const matches = (name: string) => !needle || name.toLowerCase().includes(needle);
  // 四类并发问,慢的那一类不拖住其余的。任何一类挂掉只丢它自己(菜单是辅助,不该整块消失)。
  const [assetPage, notes, boards, workflows] = await Promise.all([
    //: 素材在服务端按名字 / 文件名 / 标签搜,只要这一类摆得下的那么几条 —— 不为了菜单里的几行拉回整个素材库。
    //: **匹配数照样拿得到**(page.total):它数的是同一个筛选条件下的全部,不只是这一页。
    listAssetPage({ workspace_id: workspaceId, q: query, limit: REFERENCE_KIND_LIMIT })
      .catch(() => ({ items: [], total: 0 })),
    listNotes(workspaceId, query).catch(() => []),
    listBoards(workspaceId).catch(() => []),
    listWorkflows(workspaceId).catch(() => []),
  ]);
  const matched: Record<ReferenceKind, number> = { asset: 0, note: 0, board: 0, workflow: 0 };
  const pushed: Record<ReferenceKind, number> = { asset: 0, note: 0, board: 0, workflow: 0 };
  const out: AgentReference[] = [];
  /** 记进匹配数;**摆不下的只记数,不进列表** —— 底部那行说的就是这批的多少。 */
  const keep = (kind: ReferenceKind, id: string, name: string) => {
    matched[kind] += 1;
    if (pushed[kind] >= REFERENCE_KIND_LIMIT) return;
    pushed[kind] += 1;
    out.push({ kind, id, name: name || id.slice(0, 8) });
  };
  const push = (kind: ReferenceKind, id: string, name: string) => {
    if (id && matches(name)) keep(kind, id, name);
  };
  //: 服务端已经按搜索词筛过(它还搜文件名和标签,名字里不一定有这几个字),这里不再按名字筛一遍。
  for (const asset of assetPage.items) keep("asset", asset.id, asset.name || asset.original_filename || "");
  //: 素材那一类的匹配数是服务端数的(**同一个筛选条件下的全部**,不只取回来的那几条)。
  //: 底下那个 max 只是不让数比摆出来的还少:真数万一缺了(接口换了、替身没给全),说"一条都不多"
  //: 也比说"还有 -3 个"强。
  matched.asset = Math.max(assetPage.total, pushed.asset);
  for (const note of notes) push("note", note.id, note.title || "");
  for (const board of boards) push("board", board.id, board.name || "");
  for (const flow of workflows) push("workflow", flow.id, flow.name || "");
  // **按类成段**,不再轮转:菜单是分组显示的(每组一个标题),轮转会把同一类拆散到各处。
  // 每类各自封顶,免得素材把其余三类挤出第一屏 —— 素材通常最多,不封顶的话笔记和工作流
  // 永远露不了面,用户会以为只能引用素材。
  return { items: out, matched };
}
