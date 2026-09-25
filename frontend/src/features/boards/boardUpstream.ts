import type { BoardItem } from "@/api/client";
import type { NoteReference } from "@/api/domains/notes";

import { boardAssetSources } from "./boardAssetSources";
import { boardDocumentBlocked, boardSourceText, type BoardDocumentState } from "./boardDocumentSources";

/** 连到某一项上游的东西,按它们各自该起的作用分好。 */
export interface Upstream {
  /** 上游的图/视频 —— 当参考素材。 */
  assets: ReturnType<typeof boardAssetSources>;
  /** 上游便签/文档的文字 —— 当提示词。 */
  texts: { itemId: string; text: string }[];
  references: NoteReference[];
  /** 上游有文档取不到:这时候不该让人点生成,跑出来的东西会少一块。 */
  blocked: boolean;
  /** 上游文档还在读:等一下就有了,和「取不到」要分开说。 */
  pending: boolean;
}

export const NO_UPSTREAM: Upstream = { assets: [], texts: [], references: [], blocked: false, pending: false };

/**
 * 这一项从上游拿到什么。
 *
 * **每次都从当前的连线重新算**,不存快照 —— 判定里那句「连线后改上游,下游要跟随」靠的就是
 * 这一点:改了上游那张便签的字,下一次渲染这里重算,表单里的提示词跟着变。存一份快照的话,
 * 用户改完上游会发现下游还是旧的,而且没有任何地方提示他"这里没跟上"。
 *
 * **便签给的是提示词,不是素材。** 一张写着描述的便签连到图片节点上,用户的意思是「照这段话画」——
 * 而不是把便签当参考图(它根本没有图)。
 */
export function upstreamOf(
  targetId: string,
  items: BoardItem[],
  edges: { source: string; target: string }[],
  documents: Map<string, BoardDocumentState>,
): Upstream {
  const byId = new Map(items.map((item) => [item.id, item]));
  const sources = edges
    .filter((edge) => edge.target === targetId)
    .map((edge) => byId.get(edge.source))
    .filter((item): item is BoardItem => Boolean(item));
  return {
    references: sources
      .filter((item) => item.kind === "document")
      .map((item) => documents.get(item.id)?.reference)
      .filter((ref): ref is NoteReference => !!ref),
    blocked: sources.some((item) => boardDocumentBlocked(item, documents.get(item.id))),
    pending: sources.some((item) => item.kind === "document" && documents.get(item.id)?.pending),
    assets: boardAssetSources(sources),
    texts: sources
      .map((item) => ({ itemId: item.id, text: boardSourceText(item, documents.get(item.id)) }))
      .filter((item) => !!item.text),
  };
}

/** 每一格从连线上拿到的素材(按 boardAssetSources 的口径)。只收有上游的那几格。 */
export function upstreamAssetIds(
  items: BoardItem[],
  edges: { source: string; target: string }[],
): Map<string, Set<string>> {
  const byId = new Map(items.map((item) => [item.id, item]));
  const sources = new Map<string, BoardItem[]>();
  for (const edge of edges) {
    const from = byId.get(edge.source);
    if (from && byId.has(edge.target)) sources.set(edge.target, [...(sources.get(edge.target) ?? []), from]);
  }
  return new Map(
    [...sources].map(([target, from]) => [target, new Set(boardAssetSources(from).map((one) => one.assetId))]),
  );
}

/**
 * 上游不再给的素材,从下游表单的槽位里摘掉。回「哪一格的槽位该换成什么」。
 *
 * 面板开着时,连线一变它自己会照上游重挂一遍(见 NodeComposer 的 feedKey);可面板只在选中时
 * 才挂着 —— 没选中时删掉那条线、删掉上游那一格、给上游换一份素材,下游表单里那份引用原样留着,
 * 下次打开面板它还挂在首帧上,点生成照样发出去,而画布上早就没有那条线了。
 *
 * 所以这条规则放在画布上,和面板开没开无关:只摘**原先从连线来、现在连线不再给**的那几份,
 * 用户手动挂上去的照留。
 */
export function detachedSourcePatches(
  items: BoardItem[],
  before: Map<string, Set<string>>,
  after: Map<string, Set<string>>,
): Map<string, { asset_id: string; role: string }[]> {
  const patches = new Map<string, { asset_id: string; role: string }[]>();
  for (const item of items) {
    const was = before.get(item.id);
    const sources = item.form?.source_assets;
    if (!was || !sources?.length) continue;
    const now = after.get(item.id) ?? new Set<string>();
    const kept = sources.filter((one) => !was.has(one.asset_id) || now.has(one.asset_id));
    if (kept.length !== sources.length) patches.set(item.id, kept);
  }
  return patches;
}
