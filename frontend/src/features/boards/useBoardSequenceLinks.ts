/**
 * 画板上的时间线格(ADR 0030):连线进来、点「+」挑素材,都是把一份素材接到时间线末尾。从 BoardCanvas 拆出来的钩子。
 */
import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { ReactFlowInstance } from "@xyflow/react";

import type { BoardCanvas, BoardItem } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { appendAssetToSequence } from "@/api/domains/editor";
import { boardSequenceKey } from "@/features/boards/SequenceCell";
import { noteSequenceEdit, type SequenceEditLink } from "@/features/boards/sequenceCursor";
import { isMediaKind } from "@/features/boards/boardNodes";
import type { BoardPickAsset } from "@/features/boards/boardCanvasModel";

export function useBoardSequenceLinks({
  rf,
  onPickAsset,
}: {
  rf: React.RefObject<ReactFlowInstance | null>;
  onPickAsset: BoardPickAsset;
}) {
  const queryClient = useQueryClient();

  /** 一份素材接到时间线末尾(视频、图片进主视频轨,音频进音频轨),格子读的缓存换成回来的那条,记进撤销。 */
  const appendToSequence = React.useCallback(async (sequenceId: string, assetId: string, link?: SequenceEditLink) => {
    try {
      const next = await appendAssetToSequence(sequenceId, assetId);
      queryClient.setQueryData(boardSequenceKey(sequenceId), next);
      noteSequenceEdit(sequenceId, next.revision, link);
    } catch (error) {
      toast.error(errorText(error));
    }
  }, [queryClient]);
  /**
   * 连进时间线格(ADR 0030)= 把那一格的素材接到这条时间线的末尾。连线本身照常留着;断开**不**从时间线上删 ——
   * 那一段可能已经被切过、排过,自动删会丢掉这些手工。
   *
   * 一次连好几根(多选几格连到一格上):**按先后一段一段接**(并发接的话几段抢同一个版本号),带着同一个批次,
   * 撤销里和画布上那几根线并成一步(见 canvasHistory.joinSequenceToCanvas)。还是空槽的那几格现在不接 ——
   * 产出落下时服务端补接。
   */
  const appendLinks = React.useCallback((links: readonly { source: string; target: string }[]) => {
    const itemOf = (id: string) => (rf.current?.getNode(id)?.data as { item?: BoardItem } | undefined)?.item;
    const batch = links.length > 1 ? `links-${Date.now().toString(36)}` : undefined;
    const pending = links.flatMap((link) => {
      const source = itemOf(link.source);
      const target = itemOf(link.target);
      if (target?.kind !== "sequence" || !target.sequence_id || !source?.asset_id) return [];
      if (!["video", "image", "audio"].includes(source.kind)) return [];
      return [{ sequence: target.sequence_id, asset: source.asset_id, link: { ...link, ...(batch ? { batch } : {}) } }];
    });
    if (pending.length === 0) return;
    void (async () => {
      for (const one of pending) await appendToSequence(one.sequence, one.asset, one.link);
    })();
  }, [appendToSequence]);
  /** 时间线格上的「+」:挑一份素材(这张画板上已有的,或素材库里的)接到末尾,和连线进来同一件事。 */
  const pickForSequence = React.useCallback((sequenceId: string) => {
    const onBoard = [...new Set((rf.current?.getNodes() ?? [])
      .map((node) => (node.data as { item?: BoardItem }).item)
      .filter((one): one is BoardItem => Boolean(one?.asset_id && isMediaKind(one.kind)))
      .map((one) => one.asset_id as string))];
    onPickAsset("media", (assetId) => void appendToSequence(sequenceId, assetId), { onBoard });
  }, [appendToSequence, onPickAsset]);

  return { appendLinks, pickForSequence };
}

/**
 * 服务端新的一版里**产出刚落进来**、又连着时间线格的那几格,喂的是哪几条时间线:服务端落回执时已经把产出接到了
 * 这些时间线末尾(后端 timelines.append_filled_media),格子读的缓存要跟着刷新。
 */
export function sequencesFilledFrom(before: BoardCanvas, after: BoardCanvas): string[] {
  const had = new Map(before.items.map((item) => [item.id, item.asset_id]));
  const filled = new Set(after.items.filter((item) => item.asset_id && !had.get(item.id)).map((item) => item.id));
  if (filled.size === 0) return [];
  const byId = new Map(after.items.map((item) => [item.id, item]));
  return [...new Set(after.edges
    .filter((edge) => filled.has(edge.source))
    .map((edge) => byId.get(edge.target))
    .filter((item): item is BoardItem => item?.kind === "sequence" && Boolean(item.sequence_id))
    .map((item) => item.sequence_id as string))];
}
