import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Camera, CircleAlert, CircleCheck, Download, FolderPlus, Loader2, Plus, Redo2, Scissors, Sparkles, Type, Undo2 } from "lucide-react";

import { toast } from "sonner";
import { useRecorder } from "@/features/media/RecordingProvider";

import {
  API_BASE,
  addTrack,
  api,
  generateSubtitles,
  getAuthToken,
  setSubtitleStyle,
  listFonts,
  uploadFont,
  deleteFont,
  cutClipRange,
  cutClipRanges,
  deleteClip,
  deleteClipsBatch,
  rippleDeleteClip,
  rippleDeleteClipsBatch,
  exportSequence,
  type ExportParams,
  importAsset,
  insertClip,
  insertTextClip,
  moveClip,
  moveClipsBatch,
  redoSequence,
  moveTrack,
  removeTrack,
  setTrackState,
  grabSequenceFrame,
  splitClip,
  splitClipAtPoints,
  setClipEffects,
  detachClipAudio,
  setClipGain,
  setClipSpeed,
  setClipTransform,
  setSequenceReframe,
  setClipText,
  setClipTexts,
  translateTexts,
  trimClip,
  undoSequence,
  type Asset,
  type Font,
  type Job,
  type Project,
  type Sequence,
  type Workspace,
} from "@/api/client";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { CanvasAgentChat, type CanvasAgentMode } from "@/components/agent/CanvasAgentChat";
import { clipEnd } from "@/domain/timeline/geometry";
import { projectTranscript, type SegmentLike } from "@/domain/timeline/transcriptProjection";
import { type LeftTab, useEditorPanels } from "@/features/editor/useEditorPanels";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { HANDLE_COLUMN, HANDLE_ROW, handleOffset, useResizableSidebar } from "@/lib/useResizableSidebar";

//: 剪辑页的 grid **自己**带 p-2(别的页面是外层 flex 带,grid 自己是 0)。
//: 手柄绝对定位在这个 grid 里,所以偏移要算上它。
const EDITOR_GRID = { padding: 8 };
import { useEditorStore } from "@/stores/editorStore";
import { ConfirmDialog } from "@/components/app/modals";
import { FontFaces } from "@/features/editor/FontFaces";
import { Inspector } from "./Inspector";
import { MediaPool } from "./MediaPool";
import { Monitor } from "./Monitor";
import { SubtitlePanel } from "./SubtitlePanel";
import { TranscriptPanel } from "./TranscriptPanel";
import { VoicePanel } from "./VoicePanel";
import { Timeline, trackAcceptsAsset, type TrimPayload } from "./timeline/Timeline";
import { cn } from "@/lib/utils";
import { DndContext, DragOverlay, PointerSensor, pointerWithin, useSensor, useSensors, type DragStartEvent } from "@dnd-kit/core";

export function EditorView({
  workspace,
  project,
  onCreateProject,
  creatingProject,
}: {
  workspace: Workspace;
  project: Project | null;
  onCreateProject: () => void;
  creatingProject: boolean;
}) {
  const t = useI18n();
  if (!project) {
    // 空态必须给出口:一个项目都没有时顶栏的项目切换器压根不渲染(AppShell 里
    // `projects.length > 0` 才挂),这个按钮就是剪辑页唯一能新建的地方——否则用户
    // 只看到「没有项目」,得自己猜要回首页。
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2 [&>*]:shrink-0">
        <EmptyState
          icon={<Scissors size={22} />}
          title={t("emptyProject")}
          body={t("homeEmptyBody")}
          action={
            <Button onClick={onCreateProject} disabled={creatingProject}>
              <FolderPlus size={15} /> {t("createProject")}
            </Button>
          }
        />
      </div>
    );
  }
  return <Editor workspace={workspace} project={project} />;
}

function Editor({ workspace, project }: { workspace: Workspace; project: Project }) {
  const t = useI18n();
  const qc = useQueryClient();
  const { openRecorder } = useRecorder();
  const selectedClipId = useEditorStore((state) => state.selectedClipId);
  // 在哪个 tab 是**这个人怎么用这个工具**的一部分,不是这一刻的临时值 —— 切走再回来不该重置
  // (面板宽度早就是这么存的,见 PANEL_SIZES_KEY)。用项目里已有的那个钩子,它自带白名单:
  // 哪天某个 tab 被删掉,存着旧值的用户不会卡在一个不存在的页面上。
  const panels = useEditorPanels();
  // 剪辑助手与工作流/画板助手共用 CanvasAgentChat。开合与停靠方式属于工作台偏好，
  // 切项目或刷新时不应该无故消失，因此沿用页面级持久化状态。
  const [agentOpen, setAgentOpen] = usePersistentTab<"on" | "off">("editor-agent", "off", ["on", "off"]);
  const [agentMode, setAgentMode] = usePersistentTab<CanvasAgentMode>("editor-agent-mode", "docked", [
    "docked",
    "floating",
  ]);
  const agentSidebar = useResizableSidebar("editor-agent", { min: 320, max: 640, fallback: 400 });


  const assets = useQuery({
    queryKey: ["assets", workspace.id, project.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}&project_id=${project.id}`),
  });
  const sequences = useQuery({
    queryKey: ["sequences", project.id],
    queryFn: () => api<Sequence[]>(`/api/projects/${project.id}/sequences`),
  });
  const sequence = sequences.data?.[0] ?? null;

  // 换时间线 = 换内容:播放头与播放状态是全局 store 的,不重置就会带着上一条时间线的进度
  // 继续播新序列(播放头还可能停在新序列长度之外)。这里按序列 id 归零并停播,覆盖所有切换
  // 入口(项目切换器 / 首页 / 命令面板 / 深链),而不是只在某个按钮的回调里补一手。
  React.useEffect(() => {
    if (!sequence?.id) return;
    const { setPlaying, setPlayhead } = useEditorStore.getState();
    setPlaying(false);
    setPlayhead(0);
  }, [sequence?.id]);

  // Uploaded subtitle fonts are workspace-level, like assets and LUTs.
  const fonts = useQuery({
    queryKey: ["fonts", workspace.id],
    queryFn: () => listFonts(workspace.id),
    staleTime: 5 * 60_000,
  });
  const refreshFonts = () => qc.invalidateQueries({ queryKey: ["fonts", workspace.id] });
  const uploadFontMutation = useMutation({
    mutationFn: (file: File) => uploadFont({ workspaceId: workspace.id, file }),
    onSuccess: () => void refreshFonts(),
    onError: (error: Error) => toast.error(error.message),
  });
  const deleteFontMutation = useMutation({
    mutationFn: (fontId: string) => deleteFont(fontId),
    onSuccess: () => void refreshFonts(),
    onError: (error: Error) => toast.error(error.message),
  });

  const refreshSequences = () => qc.invalidateQueries({ queryKey: ["sequences", project.id] });
  // Drag ops return the updated sequence — write it straight into the cache (no refetch
  // round-trip) so the clip lands at its final spot in the SAME commit the draft clears.
  // Awaiting an invalidate/refetch here instead left a stale-data window: the clip flashed
  // back to its original slot/track ("闪烁 / 换轨失败") and added drop lag.
  const applySequence = (updated: Sequence) =>
    qc.setQueryData<Sequence[]>(["sequences", project.id], (old) =>
      (old ?? []).map((item) => (item.id === updated.id ? updated : item)),
    );
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
  const resyncAfterFailedDrag = () => {
    draftSettleRef.current = true;
    void refreshSequences();
  };
  React.useEffect(() => {
    if (draftSettleRef.current) {
      draftSettleRef.current = false;
      useEditorStore.getState().setDragDraft(null);
    }
  }, [sequence]);

  const uploadAsset = useMutation({
    mutationFn: (file: File) => importAsset({ workspaceId: workspace.id, projectId: project.id, file }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", workspace.id, project.id] }),
  });
  const createSequence = useMutation({
    mutationFn: () =>
      api<Sequence>("/api/sequences", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, project_id: project.id, name: t("mainSequence") }),
      }),
    onSuccess: refreshSequences,
  });
  const insertClipMutation = useMutation({
    mutationFn: (args: { trackId: string; assetId: string; timelineStart: number; srcIn: number; srcOut: number }) =>
      insertClip(sequence!.id, {
        track_id: args.trackId,
        asset_id: args.assetId,
        timeline_start: args.timelineStart,
        src_in: args.srcIn,
        src_out: args.srcOut,
        // 插入模式下素材落轨与移动同语义:让位(必要时切开落点上的片段)而不是覆盖。
        ripple: useEditorStore.getState().editMode === "insert",
      }),
    onSuccess: refreshSequences,
  });
  const moveClipMutation = useMutation({
    mutationFn: ({
      clipId,
      timelineStart,
      trackId,
      ripple,
    }: {
      clipId: string;
      timelineStart: number;
      trackId?: string;
      ripple?: boolean;
    }) => moveClip(sequence!.id, clipId, { timeline_start: timelineStart, track_id: trackId ?? null, ripple }),
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  /** 框选整组拖动。与单个移动共用 settle/resync,所以落位动画与失败回滚的行为完全一致。 */
  const moveClipsMutation = useMutation({
    mutationFn: (moves: { clipId: string; timelineStart: number; trackId?: string }[]) =>
      moveClipsBatch(
        sequence!.id,
        moves.map((move) => ({
          clip_id: move.clipId,
          timeline_start: move.timelineStart,
          track_id: move.trackId ?? null,
        })),
      ),
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  const trimClipMutation = useMutation({
    mutationFn: ({ clipId, payload }: { clipId: string; payload: TrimPayload }) =>
      trimClip(sequence!.id, clipId, payload),
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  const deleteClipMutation = useMutation({
    mutationFn: (clipId: string) => deleteClip(sequence!.id, clipId),
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const deleteClipsMutation = useMutation({
    // 一条请求、一条操作、一步撤销。逐个删会落成 N 条 SequenceOperation,⌘Z 一次只找回一段。
    mutationFn: (clipIds: string[]) => deleteClipsBatch(sequence!.id, clipIds),
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const rippleDeleteMutation = useMutation({
    // 顺序由后端负责(它内部从后往前删,先删靠前的会把后面的目标带偏);这里只管整批提交,
    // 换来一条操作、一步撤销。
    mutationFn: (clipIds: string[]) => rippleDeleteClipsBatch(sequence!.id, clipIds),
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const addTrackMutation = useMutation({
    mutationFn: (kind: "video" | "audio" | "subtitle") => addTrack(sequence!.id, kind),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  const moveTrackMutation = useMutation({
    mutationFn: ({ trackId, direction }: { trackId: string; direction: "up" | "down" }) =>
      moveTrack(sequence!.id, trackId, direction),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  // Drag a clip above the top video track → create a new video layer and drop it there.
  const moveClipToNewLayerMutation = useMutation({
    mutationFn: async ({ clipId, timelineStart }: { clipId: string; timelineStart: number }) => {
      const before = new Set((sequence!.tracks ?? []).map((tk) => tk.id));
      const updated = await addTrack(sequence!.id, "video");
      const created = (updated.tracks ?? []).find((tk) => tk.kind === "video" && !before.has(tk.id));
      if (!created) return updated;
      return moveClip(sequence!.id, clipId, { timeline_start: timelineStart, track_id: created.id });
    },
    onSuccess: settleWith,
    onError: resyncAfterFailedDrag,
  });
  const setTextMutation = useMutation({
    mutationFn: ({ clipId, text }: { clipId: string; text: string }) => setClipText(sequence!.id, clipId, text),
    onSuccess: (updated) => applySequence(updated),
  });
  const setTextsMutation = useMutation({
    mutationFn: (texts: { clip_id: string; text: string }[]) => setClipTexts(sequence!.id, texts),
    onSuccess: (updated) => applySequence(updated),
    onError: (error: Error) => toast.error(error.message),
  });
  const addSubtitleMutation = useMutation({
    mutationFn: async () => {
      let track = (sequence!.tracks ?? []).find((item) => item.kind === "subtitle" && !item.locked);
      if (!track) {
        const updated = await addTrack(sequence!.id, "subtitle");
        track = (updated.tracks ?? []).find((item) => item.kind === "subtitle");
      }
      if (!track) return;
      await insertTextClip(sequence!.id, {
        track_id: track.id,
        text: t("subtitleDefaultText"),
        timeline_start: useEditorStore.getState().playhead,
        duration: 2,
      });
    },
    onSuccess: refreshSequences,
  });
  // 加花字:放到专用图层——复用一条没有画面素材的 video 轨(纯花字/空轨),没有则新建一条,
  // 避免与 base 视频在同轨重叠。花字每条自带样式、用 transform 定位,区别于底部统一字幕。
  const addTextMutation = useMutation({
    mutationFn: async () => {
      let track = (sequence!.tracks ?? []).find(
        (item) => item.kind === "video" && !item.locked && (item.clips ?? []).every((c) => !c.asset_id),
      );
      if (!track) {
        const before = new Set((sequence!.tracks ?? []).map((tk) => tk.id));
        const updated = await addTrack(sequence!.id, "video");
        track = (updated.tracks ?? []).find((tk) => tk.kind === "video" && !before.has(tk.id));
      }
      if (!track) return undefined;
      return insertTextClip(sequence!.id, {
        track_id: track.id,
        text: t("textDefaultText"),
        timeline_start: useEditorStore.getState().playhead,
        duration: 3,
      });
    },
    onSuccess: (updated) => {
      if (updated) applySequence(updated);
      refreshSequences();
    },
  });
  // 一键从逐字稿生成字幕:拉齐所有视频/音频片段的转写,投影到时间线句子,批量插到字幕轨。
  // One pipeline, two entry points. Passing a target language inserts a translation step
  // between projecting the transcript and writing the cues — "翻译成字幕" is the same job as
  // "从逐字稿生成", not a parallel implementation of it.
  const generateSubtitlesMutation = useMutation({
    mutationFn: async (targetLang?: string) => {
      const seq = sequence!;
      const tracks = seq.tracks ?? [];
      const clips = [
        ...(tracks.find((tk) => tk.kind === "video")?.clips ?? []),
        ...tracks.filter((tk) => tk.kind === "audio").flatMap((tk) => tk.clips ?? []),
      ];
      const assetIds = [...new Set(clips.map((c) => c.asset_id).filter((id): id is string => Boolean(id)))];
      const token = getAuthToken();
      const fetched = await Promise.all(
        assetIds.map(async (id) => {
          const res = await fetch(`${API_BASE}/api/assets/${id}/transcript`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          });
          return res.ok ? await res.json() : null;
        }),
      );
      const segmentsByAsset = new Map<string, SegmentLike[]>();
      fetched.forEach((tr, index) => {
        if (tr) {
          segmentsByAsset.set(
            assetIds[index],
            (tr.segments ?? []).map((s: { id: string; start_time: number; end_time: number; text: string; speaker?: string }) => ({
              id: s.id,
              start_time: s.start_time,
              end_time: s.end_time,
              text: s.text,
              speaker: s.speaker,
              tokens: [],
            })),
          );
        }
      });
      const sentences = projectTranscript(clips, segmentsByAsset);
      if (sentences.length === 0) throw new Error(t("subtitleNoTranscript"));
      let track = tracks.find((tk) => tk.kind === "subtitle" && !tk.locked);
      if (!track) track = (await addTrack(seq.id, "subtitle")).tracks?.find((tk) => tk.kind === "subtitle");
      if (!track) throw new Error(t("subtitleNoTranscript"));
      // Translated in one batched, concurrent request — the same path the subtitle panel uses,
      // so a 200-cue transcript costs one round-trip's latency rather than 200.
      const texts = targetLang
        ? (await translateTexts(workspace.id, sentences.map((s) => s.text), targetLang)).translations
        : sentences.map((s) => s.text);
      const cues = sentences.map((s, i) => ({
        text: (texts[i] || s.text).trim() || s.text,
        timeline_start: s.timelineStart,
        duration: Math.max(0.4, s.timelineEnd - s.timelineStart),
      }));
      return { updated: await generateSubtitles(seq.id, track.id, cues), count: cues.length };
    },
    onSuccess: ({ updated, count }) => {
      applySequence(updated);
      toast.success(t("subtitleGenerated").replace("{n}", String(count)));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const subtitleStyleMutation = useMutation({
    mutationFn: (style: Record<string, unknown>) => setSubtitleStyle(sequence!.id, style),
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
    mutationFn: ({ trackId, withClips }: { trackId: string; withClips: boolean }) =>
      removeTrack(sequence!.id, trackId, withClips),
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
    mutationFn: ({ clipId, speed }: { clipId: string; speed: number }) => setClipSpeed(sequence!.id, clipId, speed),
    onSuccess: refreshSequences,
  });
  const setGainMutation = useMutation({
    mutationFn: ({ clipId, gain, muted }: { clipId: string; gain: number; muted: boolean }) =>
      setClipGain(sequence!.id, clipId, gain, muted),
    onSuccess: (updated) => applySequence(updated),
  });
  const detachAudioMutation = useMutation({
    mutationFn: (clipId: string) => detachClipAudio(sequence!.id, clipId),
    onSuccess: (updated) => {
      applySequence(updated);
      toast.success(t("detachAudioDone"));
    },
    onError: (error) => toast.error(String((error as Error).message)),
  });
  const setEffectsMutation = useMutation({
    mutationFn: ({ clipId, effects }: { clipId: string; effects: Record<string, unknown> }) =>
      setClipEffects(sequence!.id, clipId, effects),
    onSuccess: refreshSequences,
  });
  const setTransformMutation = useMutation({
    mutationFn: ({ clipId, transform }: { clipId: string; transform: Record<string, unknown> }) =>
      setClipTransform(sequence!.id, clipId, transform),
    // Apply the returned sequence straight to the cache (no refetch gap) so the resized clip
    // lands at its final transform in the same tick the Monitor drops its drag draft.
    onSuccess: (updated) => applySequence(updated),
    onError: refreshSequences,
  });
  const reframeMutation = useMutation({
    mutationFn: ({ width, height, fillMode }: { width: number; height: number; fillMode: string }) =>
      setSequenceReframe(sequence!.id, { width, height, fill_mode: fillMode }),
    onSuccess: refreshSequences,
  });
  const cutRangeMutation = useMutation({
    mutationFn: ({ clipId, srcStart, srcEnd }: { clipId: string; srcStart: number; srcEnd: number }) =>
      cutClipRange(sequence!.id, clipId, { src_start: srcStart, src_end: srcEnd }),
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const cutRangesMutation = useMutation({
    mutationFn: async (cuts: Array<{ clipId: string; ranges: Array<{ srcStart: number; srcEnd: number }> }>) => {
      for (const cut of cuts) {
        await cutClipRanges(
          sequence!.id,
          cut.clipId,
          cut.ranges.map((range) => ({ src_start: range.srcStart, src_end: range.srcEnd })),
        );
      }
    },
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const splitMutation = useMutation({
    mutationFn: ({ clipId, srcTime }: { clipId: string; srcTime: number }) => splitClip(sequence!.id, clipId, srcTime),
    onSuccess: refreshSequences,
  });
  // Transcript-driven split (按句切分 / 单句独立 / 在此切一刀): divide each named clip at
  // its source-time points. Per-clip try/catch so a clip with no interior cut just no-ops.
  const splitPointsMutation = useMutation({
    mutationFn: async (cuts: Array<{ clipId: string; srcTimes: number[] }>) => {
      let latest: Sequence | null = null;
      for (const cut of cuts) {
        if (cut.srcTimes.length === 0) continue;
        try {
          latest = await splitClipAtPoints(sequence!.id, cut.clipId, cut.srcTimes);
        } catch {
          /* clip had no valid interior split point — skip it */
        }
      }
      return latest;
    },
    onSuccess: (updated) => {
      if (updated) applySequence(updated);
      else void refreshSequences();
    },
    onError: () => void refreshSequences(),
  });
  const trackStateMutation = useMutation({
    mutationFn: ({
      trackId,
      body,
    }: {
      trackId: string;
      body: { muted?: boolean; locked?: boolean; solo?: boolean; duck?: boolean };
    }) => setTrackState(sequence!.id, trackId, body),
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
    const sel = useEditorStore.getState().selectedClipId;
    const stillThere = sel != null && (updated.tracks ?? []).some((tr) => (tr.clips ?? []).some((c) => c.id === sel));
    if (sel != null && !stillThere) useEditorStore.getState().selectClip(null);
  };
  // 撤销**会**失败:轨道上还有片段时撤不掉「新建轨道」,历史里引用的片段可能已经不在了。
  // 少了 onError 的话,用户按 ⌘Z 之后什么都没发生,也没有任何提示 —— 和「按钮点了没反应」
  // 是同一个毛病,只是这次出在撤销上,而撤销恰恰是用户最需要确认「到底生效没有」的操作。
  const undoMutation = useMutation({
    mutationFn: () => undoSequence(sequence!.id),
    onSuccess: keepSelectionIfPresent,
    onError: (error: Error) => toast.error(error.message),
  });
  const redoMutation = useMutation({
    mutationFn: () => redoSequence(sequence!.id),
    onSuccess: keepSelectionIfPresent,
    onError: (error: Error) => toast.error(error.message),
  });

  const allClips = React.useMemo(
    () => (sequence?.tracks ?? []).flatMap((track) => track.clips ?? []),
    [sequence],
  );
  const selectedClip = allClips.find((clip) => clip.id === selectedClipId) ?? null;
  // 花字 = video 轨上的文本片段(无 asset、有 text_override)。它复用画面元素的 transform(定位/
  // 缩放/旋转/透明度 + 关键帧);而字幕轨的文本走序列级统一样式,不做 per-clip transform。
  const isTitleText = React.useMemo(() => {
    if (!selectedClip || !sequence) return false;
    if (selectedClip.asset_id || selectedClip.text_override == null) return false;
    return (sequence.tracks ?? []).find((track) => track.id === selectedClip.track_id)?.kind === "video";
  }, [selectedClip, sequence]);

  const splitAtPlayhead = React.useCallback(
    (clipId?: string) => {
      if (!sequence) return;
      const playhead = useEditorStore.getState().playhead;
      const targetId = clipId ?? useEditorStore.getState().selectedClipId;
      const all = (sequence.tracks ?? []).flatMap((track) => track.clips ?? []);
      const clip = targetId
        ? all.find((item) => item.id === targetId)
        : all.find((item) => playhead > item.timeline_start && playhead < clipEnd(item));
      if (!clip) return;
      if (!(playhead > clip.timeline_start && playhead < clipEnd(clip))) return;
      const srcTime = clip.src_in + (playhead - clip.timeline_start);
      splitMutation.mutate({ clipId: clip.id, srcTime });
    },
    [sequence, splitMutation],
  );

  /**
   * 把播放头这一帧存成一份素材。
   *
   * **走后端渲染,不抓预览的画布** —— 预览里花字和字幕是 DOM 叠上去的,画布抓不到它们:
   * 抓出来的画面看着对,只是少了一层字,而用户不会发现自己导出的是没有字幕的那一版。
   */
  const grabFrameMutation = useMutation({
    mutationFn: () => grabSequenceFrame(sequence!.id, useEditorStore.getState().playhead),
    onSuccess: (asset) => {
      void qc.invalidateQueries({ queryKey: ["assets", workspace.id, project.id] });
      toast.success(t("editorGrabFrameDone"), { description: asset.name });
    },
    onError: (error) => toast.error(t("editorGrabFrameFailed"), { description: (error as Error).message }),
  });

  const duplicateClip = React.useCallback(
    (clipId?: string) => {
      if (!sequence) return;
      const targetId = clipId ?? useEditorStore.getState().selectedClipId;
      if (!targetId) return;
      for (const track of sequence.tracks ?? []) {
        const clip = (track.clips ?? []).find((item) => item.id === targetId);
        if (clip) {
          if (!clip.asset_id) return;
          const trackEnd = (track.clips ?? []).reduce((end, item) => Math.max(end, clipEnd(item)), 0);
          insertClipMutation.mutate({
            trackId: track.id,
            assetId: clip.asset_id,
            timelineStart: trackEnd,
            srcIn: clip.src_in,
            srcOut: clip.src_out,
          });
          return;
        }
      }
    },
    [sequence, insertClipMutation],
  );

  // 剪贴板(片段级复制/剪切/粘贴)+ 图层上下移。
  const clipboardRef = React.useRef<{ assetId: string; srcIn: number; srcOut: number; trackId: string } | null>(null);
  const findSelectedClip = React.useCallback(() => {
    if (!sequence) return null;
    const id = useEditorStore.getState().selectedClipId;
    if (!id) return null;
    for (const track of sequence.tracks ?? []) {
      const clip = (track.clips ?? []).find((item) => item.id === id);
      if (clip) return clip;
    }
    return null;
  }, [sequence]);
  const copyClip = React.useCallback(() => {
    const clip = findSelectedClip();
    if (!clip?.asset_id) return;
    clipboardRef.current = { assetId: clip.asset_id, srcIn: clip.src_in, srcOut: clip.src_out, trackId: clip.track_id };
  }, [findSelectedClip]);
  const pasteClip = React.useCallback(() => {
    const cb = clipboardRef.current;
    if (!cb || !sequence) return;
    const playhead = useEditorStore.getState().playhead;
    const track =
      (sequence.tracks ?? []).find((item) => item.id === cb.trackId) ??
      (sequence.tracks ?? []).find((item) => item.kind === "video");
    if (!track) return;
    insertClipMutation.mutate({ trackId: track.id, assetId: cb.assetId, timelineStart: playhead, srcIn: cb.srcIn, srcOut: cb.srcOut });
  }, [sequence, insertClipMutation]);
  const cutClip = React.useCallback(() => {
    const clip = findSelectedClip();
    if (!clip?.asset_id) return;
    clipboardRef.current = { assetId: clip.asset_id, srcIn: clip.src_in, srcOut: clip.src_out, trackId: clip.track_id };
    deleteClipMutation.mutate(clip.id);
  }, [findSelectedClip, deleteClipMutation]);
  const moveClipLayer = React.useCallback(
    (direction: -1 | 1) => {
      const clip = findSelectedClip();
      if (!clip || !sequence) return;
      const videoTracks = (sequence.tracks ?? []).filter((item) => item.kind === "video").sort((a, b) => a.position - b.position);
      const index = videoTracks.findIndex((item) => item.id === clip.track_id);
      const target = index >= 0 ? videoTracks[index + direction] : undefined;
      if (!target) return;
      moveClipMutation.mutate({ clipId: clip.id, timelineStart: clip.timeline_start, trackId: target.id });
    },
    [findSelectedClip, sequence, moveClipMutation],
  );

  const addAssetToTimeline = (asset: Asset) => {
    if (!sequence) return;
    const track = (sequence.tracks ?? []).find((item) => trackAcceptsAsset(item, asset));
    if (!track) return;
    const trackEnd = (track.clips ?? []).reduce((end, clip) => Math.max(end, clipEnd(clip)), 0);
    const duration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : 5;
    insertClipMutation.mutate({
      trackId: track.id,
      assetId: asset.id,
      timelineStart: trackEnd,
      srcIn: 0,
      srcOut: duration,
    });
  };

  // Keyboard: space toggles playback, delete removes selection.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redoMutation.mutate();
        else undoMutation.mutate();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "d") {
        event.preventDefault();
        duplicateClip();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "c") {
        event.preventDefault();
        copyClip();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "x") {
        event.preventDefault();
        cutClip();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "v") {
        event.preventDefault();
        pasteClip();
      } else if ((event.metaKey || event.ctrlKey) && event.key === "]") {
        event.preventDefault();
        moveClipLayer(1);
      } else if ((event.metaKey || event.ctrlKey) && event.key === "[") {
        event.preventDefault();
        moveClipLayer(-1);
      } else if (event.key.toLowerCase() === "s" && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        splitAtPlayhead();
      } else if (event.key.toLowerCase() === "a" && !event.metaKey && !event.ctrlKey) {
        useEditorStore.getState().setTool("select");
      } else if (event.key.toLowerCase() === "b" && !event.metaKey && !event.ctrlKey) {
        useEditorStore.getState().setTool("blade");
      } else if (event.code === "Space") {
        event.preventDefault();
        useEditorStore.getState().togglePlaying();
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const fps = sequence?.fps || 30;
        const step = (event.shiftKey ? 10 : 1) / fps;
        const store = useEditorStore.getState();
        store.setPlayhead(store.playhead + (event.key === "ArrowLeft" ? -step : step));
      } else if (event.key === "Delete" || event.key === "Backspace") {
        const clipIds = useEditorStore.getState().selectedClipIds;
        if (clipIds.length > 0 && sequence) {
          event.preventDefault();
          if (event.shiftKey) rippleDeleteMutation.mutate(clipIds);
          else if (clipIds.length === 1) deleteClipMutation.mutate(clipIds[0]);
          else deleteClipsMutation.mutate(clipIds);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence?.id, splitAtPlayhead, duplicateClip, copyClip, cutClip, pasteClip, moveClipLayer]);

  // 素材拖入时间线走 dnd-kit(指针传感器,移动 6px 才起手,不吃普通点击/右键菜单)。
  const dndSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const [dragOverlayAsset, setDragOverlayAsset] = React.useState<Asset | null>(null);
  const onAssetDragStart = (event: DragStartEvent) => {
    const asset = event.active.data.current?.asset as Asset | undefined;
    if (!asset) return;
    setDragOverlayAsset(asset);
    useEditorStore.getState().setDraggingAsset({
      id: asset.id,
      kind: asset.kind,
      duration: typeof asset.media_info.duration === "number" ? asset.media_info.duration : 5,
    });
  };
  const onAssetDragStop = () => {
    setDragOverlayAsset(null);
    useEditorStore.getState().setDraggingAsset(null);
  };

  if (!sequence) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2 [&>*]:shrink-0">
        <EmptyState
          icon={<Scissors size={22} />}
          title={t("emptyTimeline")}
          body={t("mediaEmptyBody")}
          action={
            <Button onClick={() => createSequence.mutate()} loading={createSequence.isPending}>
              <Plus size={15} /> {t("createMainSequence")}
            </Button>
          }
        />
      </div>
    );
  }

  // 检查器只在选中片段时占用右栏 — 空的「未选中片段」面板不该
  // 一直吃掉宽度;紧凑模式(≤1000px)下改为浮动抽屉,不占列。
  const showInspector = selectedClip !== null;
  // Where the panels row ends, measured from the grid's bottom edge: padding (8) + the
  // timeline's height + the row gap (8). Keeps the column resizers out of the timeline.
  const panelsRowBottom = panels.sizes.timeline + 16;
  const inspectorInGrid = showInspector && !panels.compact;
  const dockedAgent = agentOpen === "on" && agentMode === "docked";
  const editorColumns = [
    `${panels.leftWidth}px`,
    "minmax(0, 1fr)",
    inspectorInGrid ? `${panels.sizes.right}px` : null,
    dockedAgent ? `${agentSidebar.width}px` : null,
  ]
    .filter((column): column is string => column !== null)
    .join(" ");
  const agentContext = t("editorAgentContext")
    .replace("{project}", project.name)
    .replace("{projectId}", project.id)
    .replace("{sequence}", sequence.name)
    .replace("{sequenceId}", sequence.id);

  return (
    <DndContext
      sensors={dndSensors}
      collisionDetection={pointerWithin}
      onDragStart={onAssetDragStart}
      onDragEnd={onAssetDragStop}
      onDragCancel={onAssetDragStop}
    >
    <div
      data-testid="editor-layout"
      className="relative grid h-full grid-cols-[252px_minmax(0,1fr)_264px] grid-rows-[minmax(0,1fr)_252px] gap-2 p-2"
      style={{
        gridTemplateColumns: editorColumns,
        gridTemplateRows: `minmax(0, 1fr) ${panels.sizes.timeline}px`,
      }}
    >
      {/* Uploaded fonts must be registered before the monitor or the style panel can paint
          text in them. */}
      <FontFaces fonts={fonts.data ?? []} />
      <ConfirmDialog
        open={trackPendingRemoval !== null}
        title={t("removeTrackConfirmTitle")}
        body={t("removeTrackConfirmBody")
          .replace("{name}", trackPendingRemoval?.name ?? "")
          .replace("{n}", String(trackPendingRemoval?.clips ?? 0))}
        onCancel={() => setTrackPendingRemoval(null)}
        onConfirm={() =>
          trackPendingRemoval &&
          removeTrackMutation.mutate({ trackId: trackPendingRemoval.id, withClips: true })
        }
      />
      {/* Resizers sit on the 8px gap centers; grid pads 12px (Global rhythm). */}
      {/* A column resizer must not extend past the row whose columns it separates. These are
          absolutely positioned over the whole grid, so without an explicit bottom they run down
          through the timeline — and a drag started in the timeline, merely aligned with the
          monitor's left edge, resized the panel instead. Stop them at the panels row: grid
          padding + timeline height + row gap. */}
      <div
        className={`absolute bottom-3 top-3 z-10 ${HANDLE_COLUMN}`}
        style={{ left: handleOffset(panels.leftWidth, EDITOR_GRID), bottom: panelsRowBottom }}
        onPointerDown={panels.startDrag("left")}
      />
      {inspectorInGrid && (
        <div
          className={`absolute bottom-3 top-3 z-10 ${HANDLE_COLUMN}`}
          style={{
            right: handleOffset(panels.sizes.right, {
              padding: EDITOR_GRID.padding + (dockedAgent ? agentSidebar.width + 8 : 0),
            }),
            bottom: panelsRowBottom,
          }}
          onPointerDown={panels.startDrag("right")}
        />
      )}
      {dockedAgent && (
        <div
          className={`absolute bottom-3 top-3 z-10 ${HANDLE_COLUMN}`}
          style={{ right: handleOffset(agentSidebar.width, EDITOR_GRID), bottom: panelsRowBottom }}
          role="separator"
          aria-orientation="vertical"
          onPointerDown={agentSidebar.startDragFromRight}
        />
      )}
      <div
        className={`absolute left-3 right-3 z-10 ${HANDLE_ROW}`}
        style={{ bottom: handleOffset(panels.sizes.timeline, EDITOR_GRID) }}
        onPointerDown={panels.startDrag("timeline")}
      />
      {panels.tab === "media" ? (
        <MediaPool
          assets={assets.data ?? []}
          uploading={uploadAsset.isPending}
          onImportFile={(file) => uploadAsset.mutate(file)}
          onRecord={() => openRecorder({ projectId: project.id })}
          onAddToTimeline={addAssetToTimeline}
          tabs={<LeftTabs tab={panels.tab} onChange={panels.setTab} />}
        />
      ) : panels.tab === "voice" ? (
        <VoicePanel workspace={workspace} project={project} tabs={<LeftTabs tab={panels.tab} onChange={panels.setTab} />} />
      ) : (
        <section className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)]">
          <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-ui-xs [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
            <LeftTabs tab={panels.tab} onChange={panels.setTab} />
          </div>
          {panels.tab === "transcript" ? (
            <TranscriptPanel
              sequence={sequence}
              onCutSegment={(clipId, srcStart, srcEnd) => cutRangeMutation.mutate({ clipId, srcStart, srcEnd })}
              onCutRanges={(cuts) => cutRangesMutation.mutate(cuts)}
              onSplitPoints={(cuts) => splitPointsMutation.mutate(cuts)}
              onGenerateSubtitles={() => generateSubtitlesMutation.mutate(undefined)}
              generatingSubtitles={generateSubtitlesMutation.isPending}
            />
          ) : (
            <SubtitlePanel
              sequence={sequence}
              onSetText={(clipId, text) => setTextMutation.mutate({ clipId, text })}
              onApplyTexts={(texts) => setTextsMutation.mutateAsync(texts)}
              onAddSubtitle={() => addSubtitleMutation.mutate()}
              onGenerate={() => generateSubtitlesMutation.mutate(undefined)}
              generating={generateSubtitlesMutation.isPending}
              style={styleDraft ?? ((sequence.subtitle_style ?? {}) as Record<string, unknown>)}
              fonts={fonts.data ?? []}
              onUploadFont={(file) => uploadFontMutation.mutate(file)}
              onDeleteFont={(fontId) => deleteFontMutation.mutate(fontId)}
              uploadingFont={uploadFontMutation.isPending}
              onPreviewStyle={setStyleDraft}
              onSetStyle={(style) => {
                setStyleDraft(style);
                subtitleStyleMutation.mutate(style);
              }}
              onDeleteClip={(clipId) => deleteClipMutation.mutate(clipId)}
            />
          )}
        </section>
      )}
      <section className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-md border border-border shadow-[var(--shadow-panel)] bg-[var(--monitor-bg)]">
        {/* 监视器上方的操作条:**只放和「此刻这一画面」有关的动作**。
            播放/快进那些在下面的走带条上,和这里不是一类事:那些是「走到哪一帧」,
            这里是「拿这一帧做什么」。

            **颜色不跟应用主题走。** 监视器这块底是恒定深色的(画面要在中性底上看),所以
            这里和下面的走带条用同一套写死的浅灰/白 —— 跟主题走的话,浅色模式下就是深字
            压在深底上,一个字都看不清。

            分割线写成 `border-b-[color:…]` 而不是 `border-white/10`:这个项目用的是自定义
            色板,**没有 `white` 这个色阶**,那条类根本不会生成 —— 于是边框退回 preflight 的
            主题色(浅色模式下是一条不透明的浅灰),看着又粗又亮。加 `color:` 前缀是因为
            `border-b-[…]` 的方括号里放长度会被当成边框宽度。 */}
        <div className="flex items-center gap-1 border-b border-b-[color:rgb(255_255_255/0.08)] px-2 py-1 [&_button]:text-[#c6cbd2] [&_button:hover]:bg-[rgb(255_255_255/0.08)] [&_button:hover]:text-white">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-ui-2xs"
            title={t("editorSplitHere")}
            onClick={() => splitAtPlayhead()}
          >
            <Scissors size={12} /> {t("editorSplitHere")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-ui-2xs"
            title={t("editorGrabFrameTitle")}
            loading={grabFrameMutation.isPending}
            onClick={() => grabFrameMutation.mutate()}
          >
            <Camera size={12} /> {t("editorGrabFrame")}
          </Button>
          {/* 助手针对整条时间线，不属于左边那组“当前帧动作”；推到最右并用分割线隔开，
              入口始终可见，同时不会让它看起来像第三种截帧工具。 */}
          <div className="ml-auto border-l border-l-[color:rgb(255_255_255/0.08)] pl-1">
            <Button
              variant="ghost"
              size="sm"
              className={cn(
                "h-7 gap-1 px-2 text-ui-2xs",
                agentOpen === "on" && "!bg-[rgb(255_255_255/0.12)] !text-white",
              )}
              title={t("wfAgentTitle")}
              aria-label={t("wfAgentTitle")}
              aria-pressed={agentOpen === "on"}
              onClick={() => setAgentOpen(agentOpen === "on" ? "off" : "on")}
            >
              <Bot size={12} /> {t("wfAgentTitle")}
            </Button>
          </div>
        </div>
        <Monitor
          sequence={sequence}
          subtitleStyleOverride={styleDraft}
          assets={assets.data ?? []}
          onSetTransform={(clipId, transform) => setTransformMutation.mutate({ clipId, transform })}
          onSetText={(clipId, text) => setTextMutation.mutate({ clipId, text })}
          onRefreshAssets={() => void qc.invalidateQueries({ queryKey: ["assets", workspace.id, project.id] })}
        />
      </section>
      {showInspector &&
        (() => {
          const inspector = (
            <Inspector
              sequence={sequence}
              workspaceId={workspace.id}
              selectedClip={selectedClip}
              assets={assets.data ?? []}
              isTitleText={isTitleText}
              onDeleteClip={(clipId) => deleteClipMutation.mutate(clipId)}
              onSetEffects={(clipId, effects) => setEffectsMutation.mutate({ clipId, effects })}
              onSetTransform={(clipId, transform) => setTransformMutation.mutate({ clipId, transform })}
              onReframe={(width, height, fillMode) => reframeMutation.mutate({ width, height, fillMode })}
              onSetSpeed={(clipId, speed) => setSpeedMutation.mutate({ clipId, speed })}
              onSetGain={(clipId, gain, muted) => setGainMutation.mutate({ clipId, gain, muted })}
              onSetText={(clipId, text) => setTextMutation.mutate({ clipId, text })}
              fonts={fonts.data ?? []}
              onUploadFont={(file) => uploadFontMutation.mutate(file)}
              onDeleteFont={(fontId) => deleteFontMutation.mutate(fontId)}
              uploadingFont={uploadFontMutation.isPending}
              onClose={panels.compact ? () => useEditorStore.getState().selectClip(null) : undefined}
            />
          );
          return panels.compact ? <div className="fixed bottom-0 right-0 top-11 z-[60] grid w-[min(320px,calc(100vw-96px))] border-l border-border-strong bg-panel [&>section]:h-full [&>section]:rounded-none [&>section]:border-0">{inspector}</div> : inspector;
        })()}
      {agentOpen === "on" && (
        // 停靠态是 top row 的最后一列：监视器真实让出宽度，而不是被一块 absolute 面板盖住。
        // 浮动态由 CanvasAgentChat 自己 fixed 定位；contents 防止外层生成一个空 grid 单元。
        <div
          data-testid="editor-agent-slot"
          className={dockedAgent ? "z-30 grid min-h-0 min-w-0" : "contents"}
        >
          <CanvasAgentChat
            contextLine={agentContext}
            emptyHint={t("editorAgentEmpty")}
            placeholder={t("editorAgentPlaceholder")}
            rectKey="mosael.editor.agent.rect.v1"
            workspaceId={workspace.id}
            mode={agentMode}
            onModeChange={setAgentMode}
            onClose={() => setAgentOpen("off")}
          />
        </div>
      )}
      <section className="col-span-full min-h-0 overflow-hidden rounded-md border border-border shadow-[var(--shadow-panel)] bg-[var(--timeline-bg)]">
        <Timeline
          sequence={sequence}
          assets={assets.data ?? []}
          onInsertClip={(args) => insertClipMutation.mutate(args)}
          onMoveClip={(clipId, timelineStart, trackId, ripple) =>
            moveClipMutation.mutate({ clipId, timelineStart, trackId, ripple })
          }
          onMoveClips={(moves) => moveClipsMutation.mutate(moves)}
          onMoveClipToNewLayer={(clipId, timelineStart) =>
            moveClipToNewLayerMutation.mutate({ clipId, timelineStart })
          }
          onTrimClip={(clipId, payload) => trimClipMutation.mutate({ clipId, payload })}
          onAddTrack={(kind) => addTrackMutation.mutate(kind)}
          onMoveTrack={(trackId, direction) => moveTrackMutation.mutate({ trackId, direction })}
          onRemoveTrack={(trackId, clipCount) => {
            if (clipCount === 0) {
              removeTrackMutation.mutate({ trackId, withClips: false });
              return;
            }
            const track = (sequence.tracks ?? []).find((item) => item.id === trackId);
            setTrackPendingRemoval({ id: trackId, name: track?.name ?? "", clips: clipCount });
          }}
          onDeleteClip={(clipId) => deleteClipMutation.mutate(clipId)}
          onRippleDeleteClip={(clipId) => rippleDeleteMutation.mutate([clipId])}
          onDeleteClips={(clipIds) => deleteClipsMutation.mutate(clipIds)}
          onRippleDeleteClips={(clipIds) => rippleDeleteMutation.mutate(clipIds)}
          onSplitClip={(clipId) => splitAtPlayhead(clipId)}
          onSplitClipAt={(clipId, srcTime) => splitMutation.mutate({ clipId, srcTime })}
          onDuplicateClip={(clipId) => duplicateClip(clipId)}
          onDetachAudio={(clipId) => detachAudioMutation.mutate(clipId)}
          onSetTrackState={(trackId, body) => trackStateMutation.mutate({ trackId, body })}
          toolbarExtra={
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    disabled={!sequence.can_undo} loading={undoMutation.isPending}
                    onClick={() => undoMutation.mutate()}
                    aria-label={t("undo")}
                  >
                    <Undo2 size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("undo")} (⌘Z)</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    disabled={!sequence.can_redo} loading={redoMutation.isPending}
                    onClick={() => redoMutation.mutate()}
                    aria-label={t("redoAction")}
                  >
                    <Redo2 size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("redoAction")} (⇧⌘Z)</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    loading={addSubtitleMutation.isPending}
                    onClick={() => addSubtitleMutation.mutate()}
                    aria-label={t("addSubtitleAtPlayhead")}
                  >
                    <Type size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("addSubtitleAtPlayhead")}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    loading={addTextMutation.isPending}
                    onClick={() => addTextMutation.mutate()}
                    aria-label={t("addTextAtPlayhead")}
                  >
                    <Sparkles size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("addTextAtPlayhead")}</TooltipContent>
              </Tooltip>
              <ExportControl workspaceId={workspace.id} projectId={project.id} sequence={sequence} />
            </>
          }
        />
      </section>
    </div>
    <DragOverlay dropAnimation={null}>
      {dragOverlayAsset && (
        <div className="pointer-events-none flex max-w-52 items-center gap-1.5 rounded-lg border border-primary bg-panel px-2.5 py-1.5 text-xs [&_span]:truncate">
          <span>{dragOverlayAsset.name}</span>
        </div>
      )}
    </DragOverlay>
    </DndContext>
  );
}

/**
 * 左栏顶部的四个页签。
 *
 * **占满余宽 + 自己横向滚**,而不是 `shrink-0`:面板拖窄时,四个中文页签会把右边的导入 /
 * 录制两个图标按钮顶出可视区 —— 那两个按钮是这个面板最常用的动作,不该被页签挤走。
 * 现在页签滚,按钮钉在右侧。
 *
 * 切页签时把选中的那个滚进视野:面板重新挂载时滚动位置归零,而选中的可能是最后一个,
 * 不滚的话会看到一条"没有任何一项高亮"的页签栏。
 */
function LeftTabs({
  tab,
  onChange,
}: {
  tab: LeftTab;
  onChange: (tab: LeftTab) => void;
}) {
  const t = useI18n();
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tab]);

  const tabs: { key: LeftTab; label: string }[] = [
    { key: "media", label: t("media") },
    { key: "transcript", label: t("transcriptTab") },
    { key: "subtitle", label: t("subtitleTab") },
    { key: "voice", label: t("voiceTab") },
  ];

  return (
    <div ref={ref} className="flex min-w-0 flex-1 gap-0.5 overflow-x-auto">
      {tabs.map((item) => (
        <button
          key={item.key}
          type="button"
          data-active={item.key === tab || undefined}
          className={cn(
            "shrink-0 cursor-pointer whitespace-nowrap rounded-full border-0 bg-transparent px-2 py-1 text-ui-xs font-semibold uppercase tracking-[0.03em] text-muted-foreground transition-[background-color,color] duration-100 hover:text-foreground",
            item.key === tab && "bg-secondary text-foreground hover:bg-secondary",
          )}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

const EXPORT_PARAMS_KEY = "mosael.export.params";

function ExportControl({
  workspaceId,
  projectId,
  sequence,
}: {
  workspaceId: string;
  projectId: string;
  sequence: Sequence;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const sequenceId = sequence.id;
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [configOpen, setConfigOpen] = React.useState(false);
  // 参数记住上次选择:批量出片时不必每次重选。
  const [params, setParams] = React.useState<ExportParams>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(EXPORT_PARAMS_KEY) ?? "{}") as Partial<ExportParams>;
      return {
        resolution: ["original", "1080p", "720p", "480p"].includes(saved.resolution ?? "") ? saved.resolution! : "original",
        fps: typeof saved.fps === "number" ? saved.fps : null,
        quality: ["high", "standard", "compact"].includes(saved.quality ?? "") ? saved.quality! : "standard",
      };
    } catch {
      return { resolution: "original", fps: null, quality: "standard" };
    }
  });
  const updateParams = (patch: Partial<ExportParams>) => {
    setParams((current) => {
      const next = { ...current, ...patch };
      localStorage.setItem(EXPORT_PARAMS_KEY, JSON.stringify(next));
      return next;
    });
  };
  const startExport = useMutation({
    mutationFn: (body: ExportParams) => exportSequence(sequenceId, body),
    onSuccess: (job) => setJobId(job.id),
  });
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: Boolean(jobId),
    queryFn: () => api<Job>(`/api/jobs/${jobId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 700;
    },
    refetchOnWindowFocus: true,
  });

  const status = jobId ? (job.data?.status ?? "queued") : null;
  React.useEffect(() => {
    if (status === "succeeded") {
      void qc.invalidateQueries({ queryKey: ["assets", workspaceId, projectId] });
      void qc.invalidateQueries({ queryKey: ["assets", workspaceId] });
    }
  }, [status, qc, workspaceId, projectId]);

  const busy = startExport.isPending || status === "queued" || status === "running";

  return (
    <span className="mr-2 inline-flex items-center gap-1.5">
      {status === "running" && (
        <span className="inline-flex items-center gap-1.5 text-ui-xs text-muted-foreground" title={job.data?.message ?? undefined}>
          {job.data?.message && <span className="max-w-[190px] truncate">{job.data.message}</span>}
          <span className="timecode tabular-nums">{Math.round((job.data?.progress ?? 0) * 100)}%</span>
        </span>
      )}
      {status === "succeeded" && (
        <span className="inline-flex items-center gap-1 text-ui-xs text-[var(--track-audio-text)]">
          <CircleCheck size={13} /> {t("exportDone")}
        </span>
      )}
      {status === "failed" && (
        <span className="inline-flex items-center gap-1 text-ui-xs text-destructive" title={job.data?.error ?? undefined}>
          <CircleAlert size={13} /> {t("exportFailed")}
        </span>
      )}
      <Button size="sm" variant="outline" className="h-7" disabled={busy} onClick={() => setConfigOpen(true)}>
        {busy ? <Loader2 size={13} className="animate-mosael-spin" /> : <Download size={13} />}
        {busy ? t("exporting") : t("exportVideo")}
      </Button>
      <ModalShell
        open={configOpen}
        onOpenChange={setConfigOpen}
        title={t("exportConfigTitle")}
        className="w-[380px]"
        footer={
          <>
            <span className="mr-auto text-ui-xs text-muted-foreground">{t("exportConfigHint")}</span>
            <Button size="sm" onClick={() => { setConfigOpen(false); startExport.mutate(params); }}>
              <Download size={13} /> {t("exportStart")}
            </Button>
          </>
        }
      >
        <div className="grid w-full gap-3.5">
          <div className="grid gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t("exportResolution")}</span>
            <Select value={params.resolution} onValueChange={(v) => updateParams({ resolution: v as ExportParams["resolution"] })}>
              <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="original">{t("exportResolutionOriginal")}({sequence.width}×{sequence.height})</SelectItem>
                <SelectItem value="1080p">1080p</SelectItem>
                <SelectItem value="720p">720p</SelectItem>
                <SelectItem value="480p">480p</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t("exportFps")}</span>
            <Select
              value={params.fps == null ? "follow" : String(params.fps)}
              onValueChange={(v) => updateParams({ fps: v === "follow" ? null : Number(v) })}
            >
              <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="follow">{t("exportFpsFollow")}({sequence.fps}fps)</SelectItem>
                {[24, 25, 30, 50, 60].map((rate) => (
                  <SelectItem key={rate} value={String(rate)}>{rate} fps</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t("exportQuality")}</span>
            <Select value={params.quality} onValueChange={(v) => updateParams({ quality: v as ExportParams["quality"] })}>
              <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="high">{t("exportQualityHigh")}</SelectItem>
                <SelectItem value="standard">{t("exportQualityStandard")}</SelectItem>
                <SelectItem value="compact">{t("exportQualityCompact")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </ModalShell>
    </span>
  );
}
