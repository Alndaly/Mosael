/**
 * 画板上文档格引用的内容:一篇笔记,或一份文档素材解析出的全文(ADR 0031)。从 BoardCanvas 拆出来的钩子。
 */
import React from "react";
import { useQueries } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Node } from "@xyflow/react";

import type { BoardItem } from "@/api/client";
import { getNoteReference, noteReferenceQuery } from "@/api/domains/notes";
import { documentText, type DocumentText } from "@/api/domains/documents";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { type BoardDocumentState } from "./boardDocumentSources";
import { boardItems } from "@/features/boards/boardCanvasModel";
import { assetReference } from "@/features/boards/boardPlacement";

export function useBoardDocuments({
  nodes,
  setNodes,
  workspaceId,
}: {
  nodes: Node[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
  workspaceId: string;
}) {
  const t = useI18n();
  const [pickingDocument, setPickingDocument] = React.useState<string | null>(null);
  const [refreshingDocument, setRefreshingDocument] = React.useState<string | null>(null);
  const documentItems = boardItems(nodes).filter(item => item.kind === "document");
  //: 文档格引用一篇笔记(可让 AI 写),或一份文档素材(ADR 0031:只读来源,喂解析出的全文)。两种都收成同一种
  //: 「引用」交给下游 —— 连进写作 / 生成格的那一侧不必分它是哪一种。
  const noteQueries = useQueries({queries: documentItems.map(item => noteReferenceQuery(workspaceId ?? "", item.note_id ?? "", item.note_revision))});
  const assetQueries = useQueries({queries: documentItems.map(item => ({
    queryKey: ["asset", item.asset_id ?? "", "document-text"] as const,
    queryFn: () => documentText(item.asset_id ?? ""),
    enabled: Boolean(item.asset_id && !item.note_id),
    //: 导入时自动解析的那一下常常还没做完:在解析就隔两秒再问。
    refetchInterval: (query: { state: { data?: DocumentText } }) => (query.state.data?.status === "parsing" ? 2000 : false),
  }))});
  const documents = new Map<string, BoardDocumentState>(documentItems.map((item, index) => {
    if (item.asset_id && !item.note_id) {
      const text = assetQueries[index].data;
      return [item.id, {
        reference: text?.status === "ready" ? assetReference(text) : undefined,
        pending: !text || text.status === "parsing",
        error: assetQueries[index].error?.message ?? (text?.status === "failed" ? text.error || t("documentUnavailable") : undefined),
      }];
    }
    return [item.id, {
      reference: noteQueries[index].data, pending: !!item.note_id && noteQueries[index].isPending,
      error: noteQueries[index].error?.message,
    }];
  }));
  //: 交出去的是一个稳定的函数(它进每一格节点的数据,换一次就是整张画布的节点都重画一遍),里面读最新的那份。
  const refreshNow = async (id: string) => {
    const item = documentItems.find(item => item.id === id);
    if (!item?.note_id || !workspaceId) return;
    setRefreshingDocument(id);
    try {
      const reference = await getNoteReference(workspaceId, item.note_id);
      setNodes(current => current.map(node => {
        const currentItem = (node.data as {item: BoardItem}).item;
        // A delayed request must not replace a different note chosen in the meantime.
        return node.id === id && currentItem.note_id === item.note_id ? {...node, data: {...node.data, item: {...currentItem, text: reference.title, note_revision: reference.revision}}} : node;
      }));
    } catch (error) { toast.error(errorText(error)); }
    finally { setRefreshingDocument(null); }
  };

  const refreshImpl = React.useRef(refreshNow);
  refreshImpl.current = refreshNow;
  const refreshDocument = React.useCallback((id: string) => refreshImpl.current(id), []);

  return { documents, pickingDocument, setPickingDocument, refreshingDocument, refreshDocument };
}
