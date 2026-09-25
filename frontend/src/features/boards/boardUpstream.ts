import type { BoardItem } from "@/api/client";
import type { NoteReference } from "@/api/domains/notes";

import { boardAssetSources } from "./boardAssetSources";
import { boardDocumentBlocked, boardSourceText, type BoardDocumentState } from "./boardDocumentSources";

/** 连到某一项上游的东西,按它们各自该起的作用分好。 */
export interface Upstream {
  /** 连进来的每一格,按连线的先后 —— 工具格按它列绑定(接哪一格由用户挑,不在这里分好)。 */
  sources: BoardItem[];
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

export const NO_UPSTREAM: Upstream = { sources: [], assets: [], texts: [], references: [], blocked: false, pending: false };

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
    sources,
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
