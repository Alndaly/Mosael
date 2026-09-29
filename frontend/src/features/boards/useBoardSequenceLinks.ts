/**
 * 画板上的时间线格(ADR 0030):连线进来、点「+」挑素材,都是把一份素材接到时间线末尾。从 BoardCanvas 拆出来的钩子。
 */
import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Connection, ReactFlowInstance } from "@xyflow/react";

import type { BoardItem } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { appendAssetToSequence } from "@/api/domains/editor";
import { boardSequenceKey } from "@/features/boards/SequenceCell";
import { noteSequenceEdit } from "@/features/boards/sequenceCursor";
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
  const appendToSequence = React.useCallback((sequenceId: string, assetId: string) => {
    void appendAssetToSequence(sequenceId, assetId)
      .then((next) => {
        queryClient.setQueryData(boardSequenceKey(sequenceId), next);
        noteSequenceEdit(sequenceId, next.revision);
      })
      .catch((error: unknown) => toast.error(errorText(error)));
  }, [queryClient]);
  /** 连进时间线格(ADR 0030)= 把那一格的素材接到这条时间线的末尾。连线本身照常留着;断开**不**从时间线上删 ——
   *  那一段可能已经被切过、排过,自动删会丢掉这些手工。 */
  const appendOnConnect = React.useCallback((connection: Connection) => {
    const itemOf = (id: string | null) => (id ? (rf.current?.getNode(id)?.data as { item?: BoardItem } | undefined)?.item : undefined);
    const source = itemOf(connection.source);
    const target = itemOf(connection.target);
    if (target?.kind !== "sequence" || !target.sequence_id || !source?.asset_id) return;
    if (!["video", "image", "audio"].includes(source.kind)) return;
    appendToSequence(target.sequence_id, source.asset_id);
  }, [appendToSequence]);
  /** 时间线格上的「+」:挑一份素材(这张画板上已有的,或素材库里的)接到末尾,和连线进来同一件事。 */
  const pickForSequence = React.useCallback((sequenceId: string) => {
    const onBoard = [...new Set((rf.current?.getNodes() ?? [])
      .map((node) => (node.data as { item?: BoardItem }).item)
      .filter((one): one is BoardItem => Boolean(one?.asset_id && isMediaKind(one.kind)))
      .map((one) => one.asset_id as string))];
    onPickAsset("media", (assetId) => appendToSequence(sequenceId, assetId), { onBoard });
  }, [appendToSequence, onPickAsset]);

  return { appendOnConnect, pickForSequence };
}
