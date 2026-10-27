import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { assetKeys, transcriptKeys } from "@/api/queryKeys";
import { errorText } from "@/api/errorMessage";
import {
  addTrack,
  api,
  baseRevisionOf,
  cutClipRange,
  cutClipRangesBatch,
  deleteClip,
  deleteClipsBatch,
  detachClipAudio,
  duplicateClips,
  generateSubtitles,
  getAssetTranscript,
  grabSequenceFrame,
  importSubtitleFile,
  insertClip,
  insertTextClip,
  moveClip,
  moveClipsBatch,
  moveTrack,
  onSequenceConflict,
  processClipAudio,
  redoSequence,
  removeTrack,
  replaceClipMedia,
  rippleDeleteClipsBatch,
  setClipEffects,
  setClipGain,
  setClipSpeed,
  setClipText,
  setClipTexts,
  setClipTransform,
  setSequenceReframe,
  setSubtitleStyle,
  setTrackState,
  splitClip,
  splitClipAtPointsBatch,
  trimClip,
  undoSequence,
  type ClipAudioAction,
  type LinkOption,
  type Sequence,
  type TrackStatePatch,
} from "@/api/client";
import { toast } from "sonner";
import { useI18n } from "@/app/preferences";
import { frameAt, frameTime, snapToFrame } from "@/domain/timeline/geometry";
import { rippleTrimCuts, splitPointAt, splitPointsAcrossTracks } from "@/domain/timeline/editTargets";
import { projectTranscript, transcriptSegmentsFromApi, type SegmentLike } from "@/domain/timeline/transcriptProjection";
import { transcriptSourceClips } from "@/domain/timeline/transcriptSources";
import { linkOptionFor, selectedClipId as selectedClipIdOf, useEditorStore } from "@/features/editor/editorStore";
import { sequenceEditScope } from "@/features/editor/sequenceEditScope";
import { clipIdsOf, clipsOf } from "@/features/editor/sequenceClips";
import type { FillMode, TrimPayload } from "@/features/editor/sequenceEditTypes";

/**
 * 序列编辑 mutation 的组合入口。
 *
 * 所有编辑共享同一套缓存写回、409 冲突替换、拖拽草稿收尾与选区清理；各 mutation 只描述
 * 「调哪个接口、成功后怎么落缓存」。对外按用途分组，调用方不用面对一长串平铺的 mutation：
 * `runtime`（当前缓存里的序列）、`clips`（片段级编辑）、`tracks`（轨道与画幅）、
 * `subtitles`（字幕/花字/导入）、`history`（撤销重做）和 `state`（对话框与实时预览草稿）。
 */
export function useSequenceMutations({
  workspaceId,
  projectId,
  sequence,
}: {
  workspaceId: string;
  projectId: string;
  sequence: Sequence | null;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const refreshSequences = () => qc.invalidateQueries({ queryKey: ["sequences", projectId] });
  // Drag ops return the updated sequence — write it straight into the cache (no refetch
  // round-trip) so the clip lands at its final spot in the SAME commit the draft clears.
  // Awaiting an invalidate/refetch here instead left a stale-data window: the clip flashed
  // back to its original slot/track ("闪烁 / 换轨失败") and added drop lag.
  const applySequence = (updated: Sequence) =>
    qc.setQueryData<Sequence[]>(["sequences", projectId], (old) =>
      (old ?? []).map((item) => (item.id === updated.id ? updated : item)),
    );
  //: 一步编辑撞上 409(时间线在这期间被别人改过、和这一步对不上):服务端附上了最新的一版,直接换掉手里这份过时的。
  //: 提示那一句由发起的 mutation(或全局兜底)弹 —— 服务端那句话里说清了是谁改的。
  React.useEffect(
    () =>
      onSequenceConflict((latest) => {
        if (latest.project_id !== projectId) return;
        qc.setQueryData<Sequence[]>(["sequences", projectId], (old) =>
          (old ?? []).map((item) => (item.id === latest.id ? latest : item)),
        );
      }),
    [qc, projectId],
  );
  // 编辑请求排队执行(见 sequenceEditScope)。排在后面的那一次真正执行时,前面几次的回包已经写进
  // 了缓存 —— 所以需要「按当前时间线找片段 / 找轨道」的 mutation 在 mutationFn 里读 latestSequence,
  // 而不是按下按键那一刻闭包里的 sequence(那份可能已经过时了好几步)。
  const editScope = sequenceEditScope(sequence?.id);
  const latestSequence = (): Sequence | null =>
    qc.getQueryData<Sequence[]>(["sequences", projectId])?.find((item) => item.id === sequence?.id) ?? sequence;
  // 写回包、清掉不再存在的选中。删除类操作用它:回包里已经没有的片段不该还挂在选中里。
  const applyAndPruneSelection = (updated: Sequence) => {
    applySequence(updated);
    const present = new Set((updated.tracks ?? []).flatMap((tr) => (tr.clips ?? []).map((c) => c.id)));
    const store = useEditorStore.getState();
    const kept = store.selectedClipIds.filter((id) => present.has(id));
    if (kept.length !== store.selectedClipIds.length) store.selectClips(kept);
  };
  // Clearing the drag draft the instant a move settles renders ONE stale frame — the draft
  // (zustand) clears synchronously while the fresh sequence (react-query) propagates on a
  // deferred notification, so the clip flashes back to its old slot. Instead, arm this flag on
  // settle and let the effect below drop the draft on the render that actually shows the new
  // data. The draft pins the clip at its dropped spot the whole time → no flicker.
  // 落位动画在 Timeline 侧:那边的 collapse memo 会在缓存追平 settling 草稿的同一帧
  // 把它视作已清、让片段带过渡滑向终点;这里事后清草稿只是状态收尾,不参与动画时序。
  // Live subtitle-style preview. The sliders used to persist only on release, so the monitor
  // showed nothing until the round-trip landed and you were styling blind. Hold the in-progress
  // style here, render the monitor from it, and let the committed value clear it.
  const [styleDraft, setStyleDraft] = React.useState<Record<string, unknown> | null>(null);
  const draftSettleRef = React.useRef(false);
  const settleWith = (updated: Sequence) => {
    applySequence(updated);
    draftSettleRef.current = true;
  };
  // 拖动 / 修剪 / 换层失败:先说出来为什么(锁定轨、越界、冲突……)—— 此前只悄悄 resync,片段弹回
  // 原处而用户不知道发生了什么。草稿当场撤掉:缓存里还是失败前的真位置,片段就该回到那里;
  // 等 refetch 改变 sequence 再撤是靠不住的 —— 数据没变时结构共享给回同一个引用,草稿会卡在失败的落点上。
  const resyncAfterFailedDrag = (error: Error) => {
    toast.error(errorText(error));
    draftSettleRef.current = false;
    useEditorStore.getState().setDragDraft(null);
    void refreshSequences();
  };
  React.useEffect(() => {
    if (draftSettleRef.current) {
      draftSettleRef.current = false;
      useEditorStore.getState().setDragDraft(null);
    }
  }, [sequence]);

  const createSequence = useMutation({
    mutationFn: () =>
      api<Sequence>("/api/sequences", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId, project_id: projectId, name: t("mainSequence") }),
      }),
    onSuccess: refreshSequences,
  });
  const insertClipMutation = useMutation({
    scope: editScope,
    mutationFn: (args: { trackId: string; assetId: string; timelineStart: number; srcIn: number; srcOut: number }) =>
      insertClip(latestSequence()!, {
        track_id: args.trackId,
        asset_id: args.assetId,
        timeline_start: args.timelineStart,
        src_in: args.srcIn,
        src_out: args.srcOut,
        // 插入模式下素材落轨与移动同语义:让位(必要时切开落点上的片段)而不是覆盖。
        ripple: useEditorStore.getState().editMode === "insert",
      }),
    onSuccess: applySequence,
  });
  const moveClipMutation = useMutation({
    scope: editScope,
    mutationFn: ({
      clipId,
      timelineStart,
      trackId,
      ripple,
      link = {},
    }: {
      clipId: string;
      timelineStart: number;
      trackId?: string;
      ripple?: boolean;
      link?: LinkOption;
    }) => moveClip(latestSequence()!, clipId, { timeline_start: timelineStart, track_id: trackId ?? null, ripple, ...link }),
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  /** 框选整组拖动。与单个移动共用 settle/resync,所以落位动画与失败回滚的行为完全一致。 */
  const moveClipsMutation = useMutation({
    scope: editScope,
    mutationFn: ({ moves, link = {} }: { moves: { clipId: string; timelineStart: number; trackId?: string }[]; link?: LinkOption }) =>
      moveClipsBatch(
        latestSequence()!,
        moves.map((move) => ({
          clip_id: move.clipId,
          timeline_start: move.timelineStart,
          track_id: move.trackId ?? null,
        })),
        link,
      ),
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  const trimClipMutation = useMutation({
    scope: editScope,
    mutationFn: ({ clipId, payload }: { clipId: string; payload: TrimPayload }) =>
      trimClip(latestSequence()!, clipId, payload),
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  const deleteClipMutation = useMutation({
    scope: editScope,
    // 临时解链的选区(⌥ 单击选出来的那一段)只删它,不带链接组员;否则后端默认整组。
    mutationFn: (clipId: string) => deleteClip(latestSequence()!, clipId, linkOptionFor(useEditorStore.getState(), [clipId])),
    onSuccess: applyAndPruneSelection,
  });
  const deleteClipsMutation = useMutation({
    scope: editScope,
    // 一条请求、一条操作、一步撤销。逐个删会落成 N 条 SequenceOperation,⌘Z 一次只找回一段。
    mutationFn: (clipIds: string[]) =>
      deleteClipsBatch(latestSequence()!, clipIds, linkOptionFor(useEditorStore.getState(), clipIds)),
    onSuccess: applyAndPruneSelection,
  });
  const rippleDeleteMutation = useMutation({
    scope: editScope,
    // 顺序由后端负责(它内部从后往前删,先删靠前的会把后面的目标带偏);这里只管整批提交,
    // 换来一条操作、一步撤销。
    mutationFn: (clipIds: string[]) =>
      rippleDeleteClipsBatch(latestSequence()!, clipIds, linkOptionFor(useEditorStore.getState(), clipIds)),
    onSuccess: applyAndPruneSelection,
  });
  const addTrackMutation = useMutation({
    scope: editScope,
    mutationFn: (kind: "video" | "audio" | "subtitle") => addTrack(latestSequence()!, kind),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  const moveTrackMutation = useMutation({
    scope: editScope,
    mutationFn: ({ trackId, direction }: { trackId: string; direction: "up" | "down" }) =>
      moveTrack(latestSequence()!, trackId, direction),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  // Drag a clip above the top video track → create a new video layer and drop it there.
  const moveClipToNewLayerMutation = useMutation({
    scope: editScope,
    mutationFn: async ({ clipId, timelineStart }: { clipId: string; timelineStart: number }) => {
      const before = new Set((latestSequence()?.tracks ?? []).map((tk) => tk.id));
      const updated = await addTrack(latestSequence()!, "video");
      const created = (updated.tracks ?? []).find((tk) => tk.kind === "video" && !before.has(tk.id));
      if (!created) return updated;
      return moveClip(updated, clipId, { timeline_start: timelineStart, track_id: created.id });
    },
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  const setTextMutation = useMutation({
    scope: editScope,
    mutationFn: ({ clipId, text }: { clipId: string; text: string }) => setClipText(latestSequence()!, clipId, text),
    onSuccess: (updated) => applySequence(updated),
  });
  const setTextsMutation = useMutation({
    scope: editScope,
    mutationFn: (texts: { clip_id: string; text: string }[]) => setClipTexts(latestSequence()!, texts),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  // 加字幕 / 加花字之后选中新的那一段:下一步几乎一定是改它的文字,检查器得立刻对着它。
  const insertTextAndSelect = async (trackId: string, text: string, duration: number) => {
    const latest = latestSequence()!;
    const before = new Set(clipIdsOf(latest));
    const updated = await insertTextClip(latest, {
      track_id: trackId,
      text,
      timeline_start: snapToFrame(useEditorStore.getState().playhead, sequence!.fps),
      duration,
    });
    return { updated, created: clipIdsOf(updated).filter((id) => !before.has(id)) };
  };
  const applyAndSelectCreated = (result: { updated: Sequence; created: string[] } | undefined) => {
    if (!result) return refreshSequences();
    applySequence(result.updated);
    if (result.created.length > 0) useEditorStore.getState().selectClips(result.created);
  };
  const addSubtitleMutation = useMutation({
    scope: editScope,
    mutationFn: async () => {
      let track = (latestSequence()?.tracks ?? []).find((item) => item.kind === "subtitle" && !item.locked);
      if (!track) {
        const updated = await addTrack(latestSequence()!, "subtitle");
        track = (updated.tracks ?? []).find((item) => item.kind === "subtitle");
      }
      if (!track) return undefined;
      return insertTextAndSelect(track.id, t("subtitleDefaultText"), 2);
    },
    onSuccess: applyAndSelectCreated,
  });
  // 加花字:放到专用图层——复用一条没有画面素材的 video 轨(纯花字/空轨),没有则新建一条,
  // 避免与 base 视频在同轨重叠。花字每条自带样式、用 transform 定位,区别于底部统一字幕。
  const addTextMutation = useMutation({
    scope: editScope,
    mutationFn: async () => {
      let track = (latestSequence()?.tracks ?? []).find(
        (item) => item.kind === "video" && !item.locked && (item.clips ?? []).every((c) => !c.asset_id),
      );
      if (!track) {
        const before = new Set((latestSequence()?.tracks ?? []).map((tk) => tk.id));
        const updated = await addTrack(latestSequence()!, "video");
        track = (updated.tracks ?? []).find((tk) => tk.kind === "video" && !before.has(tk.id));
      }
      if (!track) return undefined;
      return insertTextAndSelect(track.id, t("textDefaultText"), 3);
    },
    onSuccess: applyAndSelectCreated,
  });
  // 一键从逐字稿生成字幕:拉齐所有视频/音频片段的转写,投影到时间线句子,批量插到字幕轨。
  // One pipeline, two entry points. Passing a target language inserts a translation step
  // between projecting the transcript and writing the cues — "翻译成字幕" is the same job as
  // "从逐字稿生成", not a parallel implementation of it.
  //: 生成字幕要落的那条轨:第一条没锁的字幕轨(没有就建一条)。
  const subtitleTarget = (sequence?.tracks ?? []).find((tk) => tk.kind === "subtitle" && !tk.locked);
  //: 那条轨上已经有字幕时,先问一句「替换掉原来的 N 条吗」—— 此前再点一次就整条轨每句叠成两份。
  const [regeneratePending, setRegeneratePending] = React.useState<number | null>(null);
  const generateSubtitlesMutation = useMutation({
    scope: editScope,
    mutationFn: async ({ replace }: { replace: boolean }) => {
      const seq = latestSequence()!;
      // 和逐字稿面板同一份「看哪些片段」:不算配音轨、分离出来的派生素材,同素材同位置只算一份。
      const clips = transcriptSourceClips(seq.tracks ?? []);
      const assetIds = [...new Set(clips.map((c) => c.asset_id).filter((id): id is string => Boolean(id)))];
      //: 和逐字稿面板同一个键、同一种取法:面板已经取过的直接用缓存。
      const fetched = await Promise.all(
        assetIds.map((id) => qc.fetchQuery({ queryKey: transcriptKeys.of(id), queryFn: () => getAssetTranscript(id) })),
      );
      const segmentsByAsset = new Map<string, SegmentLike[]>();
      fetched.forEach((transcript, index) => {
        // 与逐字稿面板**同一个映射函数** —— 用户在两页看到的句子数必须来自同一份投影。
        if (transcript) segmentsByAsset.set(assetIds[index], transcriptSegmentsFromApi(transcript.segments));
      });
      const sentences = projectTranscript(clips, segmentsByAsset);
      if (sentences.length === 0) throw new Error(t("subtitleNoTranscript"));
      let track = (seq.tracks ?? []).find((tk) => tk.kind === "subtitle" && !tk.locked);
      if (!track) track = (await addTrack(seq, "subtitle")).tracks?.find((tk) => tk.kind === "subtitle");
      if (!track) throw new Error(t("subtitleNoTranscript"));
      // 翻译不在这一步:生成字幕只铺原文,译成别的语言是字幕页「翻译」的事(那里一次一批、一步撤销)。
      const cues = sentences.map((s) => ({
        text: s.text.trim(),
        timeline_start: s.timelineStart,
        duration: Math.max(0.4, s.timelineEnd - s.timelineStart),
      }));
      return { updated: await generateSubtitles(seq, track.id, cues, replace), count: cues.length };
    },
    onSuccess: ({ updated, count }) => {
      setRegeneratePending(null);
      applySequence(updated);
      toast.success(t("subtitleGenerated").replace("{n}", String(count)));
    },
    onError: (error: Error) => {
      setRegeneratePending(null);
      toast.error(error.message);
    },
  });
  //: 导入 .srt / .vtt:字幕页的入口和素材库(拖进来 / 选文件时认出是字幕文件)共用这一个。
  const importSubtitleMutation = useMutation({
    scope: editScope,
    mutationFn: ({ file, trackId, replace }: { file: File; trackId?: string; replace?: boolean }) =>
      importSubtitleFile(latestSequence()!, file, { trackId, replace }),
    onSuccess: (result) => {
      applySequence(result.sequence);
      // 落在时间线内容之外的那几条没落 —— 说出来,不让人以为文件读少了。
      toast.success(
        result.dropped > 0
          ? t("subtitleFileImportedSome").replace("{n}", String(result.imported)).replace("{dropped}", String(result.dropped))
          : t("subtitleFileImported").replace("{n}", String(result.imported)),
      );
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const subtitleStyleMutation = useMutation({
    scope: editScope,
    mutationFn: (style: Record<string, unknown>) => setSubtitleStyle(latestSequence()!, style),
    onSuccess: (updated) => {
      applySequence(updated);
      setStyleDraft(null);
    },
    onError: (error: Error) => {
      setStyleDraft(null); // drop the preview so the monitor snaps back to the saved style
      toast.error(error.message);
    },
  });
  // A populated track is only removed after the user confirms, and the prompt says how many
  // clips go with it — the backend refuses the unconfirmed call as a second line of defence.
  const [trackPendingRemoval, setTrackPendingRemoval] = React.useState<{ id: string; name: string; clips: number } | null>(
    null,
  );
  const removeTrackMutation = useMutation({
    scope: editScope,
    mutationFn: ({ trackId, withClips }: { trackId: string; withClips: boolean }) =>
      removeTrack(latestSequence()!, trackId, withClips),
    onSuccess: (updated) => {
      applySequence(updated);
      setTrackPendingRemoval(null);
    },
    onError: (error: Error) => {
      setTrackPendingRemoval(null); // never leave the dialog hanging on a failure
      toast.error(error.message);
    },
  });
  const setSpeedMutation = useMutation({
    scope: editScope,
    mutationFn: ({ clipId, speed }: { clipId: string; speed: number }) => setClipSpeed(latestSequence()!, clipId, speed),
    onSuccess: applySequence,
  });
  const setGainMutation = useMutation({
    scope: editScope,
    mutationFn: ({ clipId, gain, muted }: { clipId: string; gain: number; muted: boolean }) =>
      setClipGain(latestSequence()!, clipId, gain, muted),
    onSuccess: (updated) => applySequence(updated),
  });
  const detachAudioMutation = useMutation({
    scope: editScope,
    mutationFn: (clipId: string) => detachClipAudio(latestSequence()!, clipId),
    onSuccess: (updated) => {
      applySequence(updated);
      toast.success(t("detachAudioDone"));
    },
    onError: (error) => toast.error(String((error as Error).message)),
  });
  //: 「替换媒体」对话框正对着哪一段(null = 没开)。
  const [replacingClipId, setReplacingClipId] = React.useState<string | null>(null);
  const replaceMediaMutation = useMutation({
    scope: editScope,
    mutationFn: (body: { asset_id: string; clip_ids?: string[]; from_asset_id?: string }) => replaceClipMedia(latestSequence()!, body),
    onSuccess: (updated, body) => {
      setReplacingClipId(null);
      applySequence(updated);
      const count = body.clip_ids?.length
        ?? (updated.tracks ?? []).flatMap((track) => track.clips ?? []).filter((clip) => clip.asset_id === body.asset_id).length;
      toast.success(t("replaceMediaDone").replace("{n}", String(count)));
    },
    onError: (error) => toast.error(String((error as Error).message)),
  });
  //: 片段声音处理排成任务:做完时间线怎么变由任务中心刷新(它说了改动 sequences),这里只说「开始了」。
  const clipAudioMutation = useMutation({
    scope: editScope,
    mutationFn: ({ clipId, action }: { clipId: string; action: ClipAudioAction }) => processClipAudio(latestSequence()!, clipId, action),
    onSuccess: () => toast.success(t("clipAudioQueued")),
    onError: (error) => toast.error(String((error as Error).message)),
  });
  const setEffectsMutation = useMutation({
    scope: editScope,
    mutationFn: ({ clipId, effects }: { clipId: string; effects: Record<string, unknown> }) =>
      setClipEffects(latestSequence()!, clipId, effects),
    onSuccess: applySequence,
  });
  const setTransformMutation = useMutation({
    scope: editScope,
    mutationFn: ({ clipId, transform }: { clipId: string; transform: Record<string, unknown> }) =>
      setClipTransform(latestSequence()!, clipId, transform),
    // Apply the returned sequence straight to the cache (no refetch gap) so the resized clip
    // lands at its final transform in the same tick the Monitor drops its drag draft.
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => {
      toast.error(errorText(error));
      void refreshSequences();
    },
  });
  const reframeMutation = useMutation({
    scope: editScope,
    mutationFn: ({ width, height, fillMode }: { width: number; height: number; fillMode: FillMode }) =>
      setSequenceReframe(latestSequence()!, { width, height, fill_mode: fillMode }),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  const cutRangeMutation = useMutation({
    scope: editScope,
    mutationFn: ({ clipId, srcStart, srcEnd }: { clipId: string; srcStart: number; srcEnd: number }) =>
      cutClipRange(latestSequence()!, clipId, { src_start: srcStart, src_end: srcEnd }),
    onSuccess: applyAndPruneSelection,
  });
  const cutRangesMutation = useMutation({
    scope: editScope,
    mutationFn: (cuts: Array<{ clipId: string; ranges: Array<{ srcStart: number; srcEnd: number }> }>) =>
      cutClipRangesBatch(
        latestSequence()!,
        cuts.map((cut) => ({
          clip_id: cut.clipId,
          ranges: cut.ranges.map((range) => ({ src_start: range.srcStart, src_end: range.srcEnd })),
        })),
      ),
    onSuccess: applyAndPruneSelection,
  });
  // 切分有两种说法:刀片点在某段的某个源时刻上(clipId + srcTime,点哪切哪);或者「在播放头处切」
  // (time + 可选的 trackId)—— 后者在**执行时**按最新的时间线找片段:连按 S 时,前一刀落地后
  // 片段已经换了 id,按下按键那一刻闭包里的那一段早已不是播放头下的那一段。
  const splitMutation = useMutation({
    scope: editScope,
    mutationFn: async (target: { clipId: string; srcTime: number } | { time: number; trackId: string | null }) => {
      const point = "clipId" in target ? target : splitPointAt(latestSequence()?.tracks ?? [], target.time, target.trackId);
      return point
        ? splitClip(latestSequence()!, point.clipId, point.srcTime, linkOptionFor(useEditorStore.getState(), [point.clipId]))
        : null;
    },
    onSuccess: (updated) => {
      if (updated) applySequence(updated);
    },
  });
  // , / . 微移:选中的片段整组按帧挪。目标位置在**执行时**按最新的时间线算 —— 连按几下时,
  // 每一下都要在前一下落地之后的位置上再挪一帧,按下那一刻算就会几下都落到同一处。
  const nudgeMutation = useMutation({
    scope: editScope,
    mutationFn: async (frames: number) => {
      const latest = latestSequence();
      const fps = latest?.fps ?? 30;
      const locked = new Set((latest?.tracks ?? []).filter((track) => track.locked).map((track) => track.id));
      const selected = new Set(useEditorStore.getState().selectedClipIds);
      const targets = clipsOf(latest).filter((item) => selected.has(item.id) && !locked.has(item.track_id));
      const moves = targets.map((item) => ({ clip: item, start: frameTime(frameAt(item.timeline_start, fps) + frames, fps) }));
      // 整组有一段会挪到 0 之前:整组不动(只挪一部分会把组内间距挤变形)。
      if (moves.length === 0 || moves.some((move) => move.start < 0)) return null;
      // 链接组员(没选中的那半)由后端跟着挪同样的距离 —— 临时解链的选区除外。
      return moveClipsBatch(
        latest!,
        moves.map((move) => ({ clip_id: move.clip.id, timeline_start: move.start, track_id: move.clip.track_id })),
        linkOptionFor(useEditorStore.getState(), targets.map((item) => item.id)),
      );
    },
    onSuccess: (updated) => {
      if (updated) applySequence(updated);
    },
  });
  // ⇧⌘K:播放头下每条未锁定轨各切一刀,一条操作、一步撤销。执行时按最新的时间线找片段。
  const splitAllMutation = useMutation({
    scope: editScope,
    mutationFn: async (time: number) => {
      const latest = latestSequence()!;
      const points = splitPointsAcrossTracks(latest.tracks ?? [], time);
      if (points.length === 0) return null;
      return splitClipAtPointsBatch(
        latest,
        points.map((point) => ({ clip_id: point.clipId, src_times: [point.srcTime] })),
      );
    },
    onSuccess: (updated) => {
      if (updated) applySequence(updated);
    },
  });
  // Q / W:波纹修剪上一个 / 下一个编辑点到播放头(见 editTargets.rippleTrimCuts)。剪口之后的内容
  // 跟着左移由后端的波纹语义负责(按区间剪是真正的波纹删除:同轨后面的左移,字幕跟着走);Q 之后播放头落到剪口上 —— 原来播放头下的那一帧现在就在那儿。
  const rippleTrimMutation = useMutation({
    scope: editScope,
    mutationFn: async ({ edge, time }: { edge: "start" | "end"; time: number }) => {
      const latest = latestSequence()!;
      const plan = rippleTrimCuts(latest.tracks ?? [], time, edge, useEditorStore.getState().selectedClipIds);
      if (!plan) return null;
      // 链接组员(画和它分离出去的声音)若也在目标轨上,和它剪的是同一段时间线,后端按轨合并区间,不会剪两遍。
      const updated = await cutClipRangesBatch(
        latest,
        plan.cuts.map((cut) => ({ clip_id: cut.clipId, ranges: [{ src_start: cut.srcStart, src_end: cut.srcEnd }] })),
      );
      return { updated, plan, edge };
    },
    onSuccess: (result) => {
      if (!result) return;
      applyAndPruneSelection(result.updated);
      if (result.edge === "start") useEditorStore.getState().setPlayhead(result.plan.from);
    },
  });
  // Transcript-driven split (按句切分 / 单句独立 / 在此切一刀): all named clips belong to
  // one user gesture, so the sequence Module records and undoes the whole batch atomically.
  const splitPointsMutation = useMutation({
    scope: editScope,
    mutationFn: (cuts: Array<{ clipId: string; srcTimes: number[] }>) =>
      splitClipAtPointsBatch(
        latestSequence()!,
        cuts
          .filter((cut) => cut.srcTimes.length > 0)
          .map((cut) => ({ clip_id: cut.clipId, src_times: cut.srcTimes })),
      ),
    onSuccess: (updated) => {
      if (updated) applySequence(updated);
      else void refreshSequences();
    },
    onError: (error: Error) => {
      toast.error(errorText(error));
      void refreshSequences();
    },
  });
  const trackStateMutation = useMutation({
    scope: editScope,
    mutationFn: ({ trackId, body }: { trackId: string; body: TrackStatePatch }) =>
      setTrackState(latestSequence()!, trackId, body),
    // Write the returned sequence straight into the cache. An invalidate/refetch leaves a window
    // where the rail still shows the pre-change track, and a click landing in that window targets
    // a track the server has already changed or removed — which then fails as "Track not found".
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  // 撤销/重做后,只有当选中的片段确实不存在了(如撤销一次"插入片段")才清空选中。
  // 之前无条件 selectClip(null) 会让调完属性再 ⌘Z 时 Inspector 直接关闭 —— 看起来像"关窗口
  // 而不是撤销",实则撤销发生了、只是选中被清了。属性/transform 撤销时片段还在,保留选中。
  const keepSelectionIfPresent = (updated: Sequence) => {
    applySequence(updated);
    const sel = selectedClipIdOf(useEditorStore.getState());
    const stillThere = sel != null && (updated.tracks ?? []).some((tr) => (tr.clips ?? []).some((c) => c.id === sel));
    if (sel != null && !stillThere) useEditorStore.getState().selectClip(null);
  };
  // 撤销**会**失败:轨道上还有片段时撤不掉「新建轨道」,历史里引用的片段可能已经不在了。
  // 少了 onError 的话,用户按 ⌘Z 之后什么都没发生,也没有任何提示 —— 和「按钮点了没反应」
  // 是同一个毛病,只是这次出在撤销上,而撤销恰恰是用户最需要确认「到底生效没有」的操作。
  const undoMutation = useMutation({
    scope: editScope,
    //: 只撤**自己**最近的一步:几个人一起剪时,按一下撤掉的不该是同事刚做的那一下。其间别人的改动和它冲突时服务端回 409、说清是谁。
    //: 版本号在执行时取(排在前面的编辑落地之后),连按 ⌘Z 时第二下报的是第一下之后的那一版。
    mutationFn: () => undoSequence(sequence!.id, { expectedRevision: baseRevisionOf(latestSequence()!), mine: true }),
    onSuccess: keepSelectionIfPresent,
    onError: (error: Error) => toast.error(error.message),
  });
  const redoMutation = useMutation({
    scope: editScope,
    mutationFn: () => redoSequence(sequence!.id, { expectedRevision: baseRevisionOf(latestSequence()!), mine: true }),
    onSuccess: keepSelectionIfPresent,
    onError: (error: Error) => toast.error(error.message),
  });

  /**
   * 把播放头这一帧存成一份素材。
   *
   * **走后端渲染,不抓预览的画布** —— 预览里花字和字幕是 DOM 叠上去的,画布抓不到它们:
   * 抓出来的画面看着对,只是少了一层字,而用户不会发现自己导出的是没有字幕的那一版。
   */
  const grabFrameMutation = useMutation({
    mutationFn: () => grabSequenceFrame(sequence!.id, useEditorStore.getState().playhead),
    onSuccess: (asset) => {
      void qc.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
      toast.success(t("editorGrabFrameDone"), { description: asset.name });
    },
    onError: (error) => toast.error(t("editorGrabFrameFailed"), { description: (error as Error).message }),
  });

  // 复制 / 粘贴 / ⌘D:一律走后端深拷贝(duplicateClips)—— 效果、变换、关键帧、文字原样带上,文字和
  // 字幕片段也能复制;一次手势一条操作、一步撤销。此前前端拿素材 + 源区间重新插一段:调好的色、
  // 动画、音量全丢,文字片段干脆复制不了。副本落地后选中它们,接着就能拖、能改。
  const duplicateMutation = useMutation({
    scope: editScope,
    mutationFn: async (args: { clipIds: string[]; timelineStart?: number; trackId?: string | null }) => {
      const latest = latestSequence()!;
      const before = new Set(clipIdsOf(latest));
      const updated = await duplicateClips(latest, {
        clip_ids: args.clipIds,
        ...(args.timelineStart !== undefined ? { timeline_start: Math.max(0, args.timelineStart) } : {}),
        ...(args.trackId ? { track_id: args.trackId } : {}),
      });
      return { updated, created: clipIdsOf(updated).filter((id) => !before.has(id)) };
    },
    onSuccess: ({ updated, created }) => {
      applySequence(updated);
      if (created.length > 0) useEditorStore.getState().selectClips(created);
    },
  });
  return {
    runtime: { latestSequence },
    state: {
      styleDraft,
      setStyleDraft,
      regeneratePending,
      setRegeneratePending,
      trackPendingRemoval,
      setTrackPendingRemoval,
      replacingClipId,
      setReplacingClipId,
      subtitleTarget,
    },
    createSequence,
    clips: {
      insertClipMutation,
      moveClipMutation,
      moveClipsMutation,
      trimClipMutation,
      deleteClipMutation,
      deleteClipsMutation,
      rippleDeleteMutation,
      moveClipToNewLayerMutation,
      setTextMutation,
      setTextsMutation,
      setSpeedMutation,
      setGainMutation,
      detachAudioMutation,
      replaceMediaMutation,
      clipAudioMutation,
      setEffectsMutation,
      setTransformMutation,
      cutRangeMutation,
      cutRangesMutation,
      splitMutation,
      nudgeMutation,
      splitAllMutation,
      rippleTrimMutation,
      splitPointsMutation,
      duplicateMutation,
      grabFrameMutation,
    },
    tracks: {
      addTrackMutation,
      moveTrackMutation,
      removeTrackMutation,
      trackStateMutation,
      reframeMutation,
    },
    subtitles: {
      addSubtitleMutation,
      addTextMutation,
      generateSubtitlesMutation,
      importSubtitleMutation,
      subtitleStyleMutation,
    },
    history: { undoMutation, redoMutation },
  };
}
