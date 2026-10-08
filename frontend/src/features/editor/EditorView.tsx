import "./editor.css";
import { assetKeys, transcriptKeys } from "@/api/queryKeys";
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, FolderPlus, Plus, Redo2, Scissors, Sparkles, Type, Undo2 } from "lucide-react";

import { toast } from "sonner";
import { errorText } from "@/api/errorMessage";
import { useRecorder } from "@/features/media/recordingContext";

import {
  addTrack,
  api,
  generateSubtitles,
  setSubtitleStyle,
  listFonts,
  uploadFont,
  deleteFont,
  cutClipRange,
  cutClipRangesBatch,
  deleteClip,
  deleteClipsBatch,
  duplicateClips,
  rippleDeleteClipsBatch,
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
  splitClipAtPointsBatch,
  setClipEffects,
  detachClipAudio,
  setClipGain,
  setClipSpeed,
  setClipTransform,
  setSequenceReframe,
  setClipText,
  setClipTexts,
  getAssetTranscript,
  importSubtitleFile,
  isSubtitleFile,
  processClipAudio,
  replaceClipMedia,
  type ClipAudioAction,
  trimClip,
  undoSequence,
  baseRevisionOf,
  onSequenceConflict,
  type AssetCard,
  type Clip,
  type LinkOption,
  type Project,
  type Sequence,
  type TrackStatePatch,
  type Workspace,
} from "@/api/client";
import { useSequenceAssets } from "@/lib/assetQueries";
import { IconButton } from "@/components/ui/icon-button";
import { formatCombo } from "@/lib/shortcuts";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { useWriteBlocked } from "@/components/layout/useWriteBlocked";
import { Hint } from "@/components/ui/tooltip";
import { CanvasAgentChat, type CanvasAgentMode } from "@/features/agent/CanvasAgentChat";
import { SectionBoundary } from "@/components/app/errorBoundary";
import { useAgentPlace } from "@/features/agent/activePlace";
import { clipEnd, frameAt, frameTime, snapToFrame } from "@/domain/timeline/geometry";
import { clipContains, rippleTrimCuts, splitPointAt, splitPointsAcrossTracks } from "@/domain/timeline/editTargets";
import { projectTranscript, transcriptSegmentsFromApi, type SegmentLike } from "@/domain/timeline/transcriptProjection";
import { transcriptSourceClips } from "@/domain/timeline/transcriptSources";
import { type LeftTab, useEditorPanels } from "@/features/editor/useEditorPanels";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { HANDLE_COLUMN, HANDLE_ROW, handleOffset, useResizableSidebar } from "@/lib/useResizableSidebar";

import { linkOptionFor, selectedClipId as selectedClipIdOf, useEditorStore } from "@/features/editor/editorStore";
import { sequenceEditScope } from "@/features/editor/sequenceEditScope";
import { useEditorShortcuts } from "@/features/editor/useEditorShortcuts";
import { ConfirmDialog } from "@/components/app/modals";
import { useImportMediaFiles } from "@/features/media/useImportMediaFiles";
import { FontFaces } from "@/features/editor/FontFaces";
import { ExportControl } from "@/features/editor/ExportControl";
import { Inspector } from "./Inspector";
import { SequenceSettings, type FillMode } from "./SequenceSettings";
import { MediaPool } from "./MediaPool";
import { Monitor } from "./Monitor";
import { SubtitlePanel } from "./SubtitlePanel";
import { ReplaceMediaDialog } from "./ReplaceMediaDialog";
import { TranscriptPanel } from "./TranscriptPanel";
import { VoicePanel } from "./VoicePanel";
import { Timeline, trackAcceptsAsset, type TrimPayload } from "./timeline/Timeline";
import { cn } from "@/lib/utils";
import { DndContext, DragOverlay, PointerSensor, pointerWithin, useSensor, useSensors, type DragStartEvent } from "@dnd-kit/core";
import { useDndAccessibility } from "@/components/app/dndAccessibility";

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
  const writeBlocked = useWriteBlocked(workspace.role);
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
            <Hint disabledReason={writeBlocked?.reason}>
              <Button onClick={onCreateProject} disabled={creatingProject || Boolean(writeBlocked)}>
                <FolderPlus size={15} /> {t("createProject")}
              </Button>
            </Hint>
          }
        />
      </div>
    );
  }
  return <Editor workspace={workspace} project={project} />;
}

function Editor({ workspace, project }: { workspace: Workspace; project: Project }) {
  const t = useI18n();
  const writeBlocked = useWriteBlocked(workspace.role);
  //: 剪辑这一处是这个项目(ADR 0044):助手面板接这个项目的对话,面板收起来时浮标和跳转也认得出你在这里。
  const agentPlace = useAgentPlace({ kind: "project", id: project.id });
  const qc = useQueryClient();
  const { openRecorder } = useRecorder();
  const selectedClipId = useEditorStore(selectedClipIdOf);
  // 在哪个 tab 是**这个人怎么用这个工具**的一部分,不是这一刻的临时值 —— 切走再回来不该重置
  // (面板宽度早就是这么存的,见 PANEL_SIZES_KEY)。用项目里已有的那个钩子,它自带白名单:
  // 哪天某个 tab 被删掉,存着旧值的用户不会卡在一个不存在的页面上。
  const panels = useEditorPanels();
  //: 字幕列表里点了某一条的配音按钮:配音页只配那一条。单独一份状态,不借时间线上的选中。
  const [dubFocusClipId, setDubFocusClipId] = React.useState<string | null>(null);
  // 剪辑助手与工作流/画板助手共用 CanvasAgentChat。开合与停靠方式属于工作台偏好，
  // 切项目或刷新时不应该无故消失，因此沿用页面级持久化状态。
  const [agentOpen, setAgentOpen] = usePersistentTab<"on" | "off">("editor-agent", "off", ["on", "off"]);
  const [agentMode, setAgentMode] = usePersistentTab<CanvasAgentMode>("editor-agent-mode", "docked", [
    "docked",
    "floating",
  ]);
  const [availableWidth, setAvailableWidth] = React.useState(Infinity);
  // 整块剪辑页:全局快捷键只接从这里面(或 body)发出的按键,见 isEditorKeyTarget。
  const workbenchRef = React.useRef<HTMLDivElement | null>(null);
  const measureWorkbench = React.useCallback((node: HTMLDivElement | null) => {
    workbenchRef.current = node;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setAvailableWidth(entry.contentRect.width);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const agentSidebar = useResizableSidebar("editor-agent", { min: 320, max: 640, fallback: 400 });


  const sequences = useQuery({
    queryKey: ["sequences", project.id],
    queryFn: () => api<Sequence[]>(`/api/projects/${project.id}/sequences`),
  });
  //: 链接里点名的那条时间线(画板上时间线格的「在剪辑里打开」,ADR 0030:一张画板的几格时间线在同一个项目里)。
  //: 只在第一次渲染时读 —— 之后地址会被路由改写成只剩 ?p=。点名的不在这个项目里就回到默认:最近改过的那条。
  const [namedSequence] = React.useState(() => new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("s"));
  const sequence = sequences.data?.find((one) => one.id === namedSequence) ?? sequences.data?.[0] ?? null;
  //: 时间线、监视器、检查器读的素材:**这条时间线用到的那些**,完整字段(见 useSequenceAssets)。
  //: 素材池是另一回事 —— 它一页页列素材库(MediaPool 自己取),配音片段这类中间产物不在那里,却照样在时间线上。
  const sequenceAssetsQuery = useSequenceAssets(workspace.id, sequence);
  const sequenceAssets = React.useMemo(() => sequenceAssetsQuery.data ?? [], [sequenceAssetsQuery.data]);

  // 换时间线 = 换内容:播放头与播放状态是全局 store 的,不重置就会带着上一条时间线的进度
  // 继续播新序列(播放头还可能停在新序列长度之外)。这里按序列 id 归零并停播,覆盖所有切换
  // 入口(项目切换器 / 首页 / 命令面板 / 深链),而不是只在某个按钮的回调里补一手。
  React.useEffect(() => {
    if (!sequence?.id) return;
    const { setPlaying, setPlayhead, clearMarks } = useEditorStore.getState();
    setPlaying(false);
    setPlayhead(0);
    // 入出点属于这一条时间线:换了时间线还留着,导出时就会按上一条的区间去切。
    clearMarks();
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
  //: 一步编辑撞上 409(时间线在这期间被别人改过、和这一步对不上):服务端附上了最新的一版,直接换掉手里这份过时的。
  //: 提示那一句由发起的 mutation(或全局兜底)弹 —— 服务端那句话里说清了是谁改的。
  React.useEffect(
    () =>
      onSequenceConflict((latest) => {
        if (latest.project_id !== project.id) return;
        qc.setQueryData<Sequence[]>(["sequences", project.id], (old) =>
          (old ?? []).map((item) => (item.id === latest.id ? latest : item)),
        );
      }),
    [qc, project.id],
  );
  // 编辑请求排队执行(见 sequenceEditScope)。排在后面的那一次真正执行时,前面几次的回包已经写进
  // 了缓存 —— 所以需要「按当前时间线找片段 / 找轨道」的 mutation 在 mutationFn 里读 latestSequence,
  // 而不是按下按键那一刻闭包里的 sequence(那份可能已经过时了好几步)。
  const editScope = sequenceEditScope(sequence?.id);
  const latestSequence = (): Sequence | null =>
    qc.getQueryData<Sequence[]>(["sequences", project.id])?.find((item) => item.id === sequence?.id) ?? sequence;
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

  const importFiles = useImportMediaFiles({ workspaceId: workspace.id, projectId: project.id });
  const createSequence = useMutation({
    mutationFn: () =>
      api<Sequence>("/api/sequences", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, project_id: project.id, name: t("mainSequence") }),
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
  const importMediaOrSubtitles = (files: File[]) => {
    const subtitleFiles = files.filter(isSubtitleFile);
    const media = files.filter((file) => !isSubtitleFile(file));
    for (const file of subtitleFiles) importSubtitleMutation.mutate({ file });
    if (media.length > 0) importFiles.mutate(media);
  };
  const requestGenerateSubtitles = () => {
    const existing = (subtitleTarget?.clips ?? []).length;
    if (existing > 0) setRegeneratePending(existing);
    else generateSubtitlesMutation.mutate({ replace: false });
  };
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
      // 切点落在帧上:播放停下来时播放头多半在两帧之间。
      const playhead = snapToFrame(useEditorStore.getState().playhead, sequence.fps);
      const targetId = clipId ?? selectedClipIdOf(useEditorStore.getState());
      const target = targetId ? (sequence.tracks ?? []).flatMap((track) => track.clips ?? []).find((item) => item.id === targetId) : null;
      if (target && !clipContains(target, playhead)) {
        // 选中的那段不在播放头下:说一声。悄悄不切,用户只会觉得 S 坏了。
        toast.message(t("splitNotUnderPlayhead"));
        return;
      }
      splitMutation.mutate({ time: playhead, trackId: target?.track_id ?? null });
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
      void qc.invalidateQueries({ queryKey: assetKeys.all(workspace.id) });
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
  /** 这几段拷到 timelineStart(整组保持相对位置);不给起点就紧接在原片段组之后(后端的默认)。 */
  const duplicateClipsAt = React.useCallback(
    (clipIds: string[], timelineStart?: number, trackId?: string | null) => {
      if (clipIds.length === 0) return;
      duplicateMutation.mutate({ clipIds, timelineStart, trackId });
    },
    [duplicateMutation],
  );
  // 作用对象:点名的那一段在选区里就是整个选区(和右键菜单同一条规矩),否则就是它自己。
  const targetsOf = React.useCallback((clipId?: string): Clip[] => {
    const selected = useEditorStore.getState().selectedClipIds;
    const ids = clipId ? (selected.includes(clipId) ? selected : [clipId]) : selected;
    const byId = new Map(clipsOf(latestSequence()).map((item) => [item.id, item]));
    return ids.map((id) => byId.get(id)).filter((item): item is Clip => Boolean(item));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence]);
  const duplicateClip = React.useCallback(
    (clipId?: string) => {
      const targets = targetsOf(clipId);
      if (targets.length === 0) return;
      // 副本紧跟在原片段(整组)之后 —— 不给起点,由后端按整组的末尾放。
      duplicateClipsAt(targets.map((item) => item.id));
    },
    [targetsOf, duplicateClipsAt],
  );

  // 剪贴板(片段级复制 / 剪切 / 粘贴)。存的是片段 id —— 粘贴时由后端从这些片段深拷贝。
  // 剪切不当场删:剪切的片段先标出来(时间线上变淡),粘贴时整段**搬**到播放头处,一步操作。
  // 当场删掉的话,粘贴时已经没有源片段可拷,只能退回「拿素材重新插一段」—— 效果全丢,文字片段贴不回来。
  const copyClip = React.useCallback(() => {
    const ids = targetsOf().map((item) => item.id);
    if (ids.length > 0) useEditorStore.getState().setClipboard({ clipIds: ids, cut: false });
  }, [targetsOf]);
  const cutClip = React.useCallback(() => {
    const ids = targetsOf().map((item) => item.id);
    if (ids.length > 0) useEditorStore.getState().setClipboard({ clipIds: ids, cut: true });
  }, [targetsOf]);
  const pasteClip = React.useCallback(() => {
    const store = useEditorStore.getState();
    const board = store.clipboard;
    if (!board || !sequence) return;
    const playhead = snapToFrame(store.playhead, sequence.fps);
    const byId = new Map(clipsOf(latestSequence()).map((item) => [item.id, item]));
    const sources = board.clipIds.map((id) => byId.get(id)).filter((item): item is Clip => Boolean(item));
    if (sources.length === 0) {
      store.setClipboard(null);
      return;
    }
    if (board.cut) {
      const delta = playhead - Math.min(...sources.map((item) => item.timeline_start));
      moveClipsMutation.mutate({
        moves: sources.map((item) => ({ clipId: item.id, timelineStart: Math.max(0, item.timeline_start + delta), trackId: item.track_id })),
      });
      store.setClipboard(null);
      return;
    }
    duplicateClipsAt(sources.map((item) => item.id), playhead);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence, moveClipsMutation, duplicateClipsAt]);
  const findSelectedClip = React.useCallback(() => targetsOf().at(-1) ?? null, [targetsOf]);
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

  const addAssetToTimeline = (asset: AssetCard) => {
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

  useEditorShortcuts(workbenchRef, sequence, {
    undo: () => undoMutation.mutate(),
    redo: () => redoMutation.mutate(),
    duplicate: () => duplicateClip(),
    copy: copyClip,
    cut: cutClip,
    paste: pasteClip,
    moveLayer: moveClipLayer,
    split: () => splitAtPlayhead(),
    splitAll: () => splitAllMutation.mutate(snapToFrame(useEditorStore.getState().playhead, sequence?.fps ?? 30)),
    nudge: (frames) => nudgeMutation.mutate(frames),
    rippleTrim: (edge) => rippleTrimMutation.mutate({ edge, time: snapToFrame(useEditorStore.getState().playhead, sequence?.fps ?? 30) }),
    deleteSelection: (ripple) => {
      const clipIds = useEditorStore.getState().selectedClipIds;
      if (ripple) rippleDeleteMutation.mutate(clipIds);
      else if (clipIds.length === 1) deleteClipMutation.mutate(clipIds[0]);
      else deleteClipsMutation.mutate(clipIds);
    },
  });

  // 素材拖入时间线走 dnd-kit(指针传感器,移动 6px 才起手,不吃普通点击/右键菜单)。
  const dndSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const dndAccessibility = useDndAccessibility();
  const [dragOverlayAsset, setDragOverlayAsset] = React.useState<AssetCard | null>(null);
  const onAssetDragStart = (event: DragStartEvent) => {
    const asset = event.active.data.current?.asset as AssetCard | undefined;
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
            <Hint disabledReason={writeBlocked?.reason}>
              <Button onClick={() => createSequence.mutate()} loading={createSequence.isPending} disabled={Boolean(writeBlocked)}>
                <Plus size={15} /> {t("createMainSequence")}
              </Button>
            </Hint>
          }
        />
      </div>
    );
  }

  // 检查器只在选中片段时占用右栏 — 空的「未选中片段」面板不该
  // 一直吃掉宽度;紧凑模式(≤1000px)下改为浮动抽屉,不占列。
  const showInspector = selectedClip !== null;
  // Contiguous panes share a boundary. Keep vertical resizers above the timeline.
  const panelsRowBottom = panels.sizes.timeline;
  const dockedAgent = agentOpen === "on" && agentMode === "docked" &&
    availableWidth >= panels.leftWidth + agentSidebar.width + 320;
  const inspectorInGrid = showInspector && !panels.compact &&
    availableWidth >= panels.leftWidth + panels.sizes.right + (dockedAgent ? agentSidebar.width : 0) + 320;
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
      accessibility={dndAccessibility}
      collisionDetection={pointerWithin}
      onDragStart={onAssetDragStart}
      onDragEnd={onAssetDragStop}
      onDragCancel={onAssetDragStop}
    >
    <div ref={measureWorkbench} data-editor-root="" className="editor-workbench flex h-full min-h-0 flex-col overflow-hidden bg-workspace">
      {/* 四周同一个内边距:32px 的控件 + 上下各 8px 正好是 48px 的条高,左右也是 8px ——
          此前左右 16px(右边导出按钮再自带 8px 外边距)、上下 8px,两端看着比上下空一截。 */}
      <div role="toolbar" aria-label={t("editTools")} className="editor-commandbar flex min-h-12 shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-divider p-2">
        <LeftTabs tab={panels.tab} onChange={panels.setTab} />
        <div className="flex shrink-0 items-center gap-1">
          <Button variant="ghost" size="sm" aria-label={t("wfAgentTitle")} aria-pressed={agentOpen === "on"} onClick={() => setAgentOpen(agentOpen === "on" ? "off" : "on")} ><Bot />{t("wfAgentTitle")}</Button>

          <IconButton
            variant="ghost"
            size="icon-sm"
            disabled={!sequence.can_undo} loading={undoMutation.isPending}
            onClick={() => undoMutation.mutate()}
            label={t("undo")}
            shortcut={formatCombo("Mod+Z")}
            disabledReason={!sequence.can_undo && t("nothingToUndo")}
          >
            <Undo2 size={14} />
          </IconButton>
          <IconButton
            variant="ghost"
            size="icon-sm"
            disabled={!sequence.can_redo} loading={redoMutation.isPending}
            onClick={() => redoMutation.mutate()}
            label={t("redoAction")}
            shortcut={formatCombo("Mod+Shift+Z")}
            disabledReason={!sequence.can_redo && t("nothingToRedo")}
          >
            <Redo2 size={14} />
          </IconButton>
          <IconButton
            variant="ghost"
            size="icon-sm"
            loading={addSubtitleMutation.isPending}
            onClick={() => addSubtitleMutation.mutate()}
            label={t("addSubtitleAtPlayhead")}
          >
            <Type size={14} />
          </IconButton>
          <IconButton
            variant="ghost"
            size="icon-sm"
            loading={addTextMutation.isPending}
            onClick={() => addTextMutation.mutate()}
            label={t("addTextAtPlayhead")}
          >
            <Sparkles size={14} />
          </IconButton>
          <ExportControl sequence={sequence} writeBlocked={writeBlocked} />

        </div>
      </div>
    <div
      data-testid="editor-layout"
      className="editor-workspace relative grid min-h-0 flex-1 grid-cols-[252px_minmax(0,1fr)_264px] grid-rows-[minmax(0,1fr)_252px]"
      style={{
        gridTemplateColumns: editorColumns,
        gridTemplateRows: `minmax(0, 1fr) ${panels.sizes.timeline}px`,
      }}
    >
      {/* Uploaded fonts must be registered before the monitor or the style panel can paint
          text in them. */}
      <FontFaces fonts={fonts.data ?? []} />
      <ReplaceMediaDialog
        sequence={sequence}
        clipId={replacingClipId}
        pending={replaceMediaMutation.isPending}
        onCancel={() => setReplacingClipId(null)}
        onReplace={(body) => replaceMediaMutation.mutate(body)}
      />
      <ConfirmDialog
        open={regeneratePending !== null}
        title={t("subtitleRegenerateTitle")}
        body={t("subtitleRegenerateBody").replace("{n}", String(regeneratePending ?? 0))}
        confirmLabel={t("subtitleRegenerateConfirm")}
        onCancel={() => setRegeneratePending(null)}
        pending={generateSubtitlesMutation.isPending}
        onConfirm={() => generateSubtitlesMutation.mutate({ replace: true })}
      />
      <ConfirmDialog
        open={trackPendingRemoval !== null}
        title={t("removeTrackConfirmTitle")}
        body={t("removeTrackConfirmBody")
          .replace("{name}", trackPendingRemoval?.name ?? "")
          .replace("{n}", String(trackPendingRemoval?.clips ?? 0))}
        onCancel={() => setTrackPendingRemoval(null)}
        pending={removeTrackMutation.isPending}
        onConfirm={() =>
          trackPendingRemoval &&
          removeTrackMutation.mutate({ trackId: trackPendingRemoval.id, withClips: true })
        }
      />
      {/* Handles straddle the shared pane boundaries without adding visual gutters. */}
      {/* A column resizer must not extend past the row whose columns it separates. These are
          absolutely positioned over the whole grid, so without an explicit bottom they run down
          through the timeline — and a drag started in the timeline, merely aligned with the
          monitor's left edge, resized the panel instead. Stop them at the panels row: grid
          padding + timeline height + row gap. */}
      <div
        className={`absolute bottom-0 top-0 z-10 ${HANDLE_COLUMN}`}
        style={{ left: handleOffset(panels.leftWidth), bottom: panelsRowBottom }}
        onPointerDown={panels.startDrag("left")}
      />
      {inspectorInGrid && (
        <div
          className={`absolute bottom-0 top-0 z-10 ${HANDLE_COLUMN}`}
          style={{
            right: handleOffset(panels.sizes.right, {
              padding: dockedAgent ? agentSidebar.width : 0,
            }),
            bottom: panelsRowBottom,
          }}
          onPointerDown={panels.startDrag("right")}
        />
      )}
      {dockedAgent && (
        <div
          className={`absolute bottom-0 top-0 z-10 ${HANDLE_COLUMN}`}
          style={{ right: handleOffset(agentSidebar.width), bottom: panelsRowBottom }}
          role="separator"
          aria-orientation="vertical"
          onPointerDown={agentSidebar.startDragFromRight}
        />
      )}
      <div
        className={`absolute left-0 right-0 z-10 ${HANDLE_ROW}`}
        style={{ bottom: handleOffset(panels.sizes.timeline) }}
        onPointerDown={panels.startDrag("timeline")}
      />
      {panels.tab === "media" ? (
        <MediaPool
          workspaceId={workspace.id}
          projectId={project.id}
          uploading={importFiles.isPending}
          writeBlocked={writeBlocked}
          onImportFiles={importMediaOrSubtitles}
          onRecord={() => openRecorder({ projectId: project.id })}
          onAddToTimeline={addAssetToTimeline}
        />
      ) : panels.tab === "voice" ? (
        <VoicePanel
          workspace={workspace}
          project={project}
          sequence={sequence}
          onOpenSubtitles={() => panels.setTab("subtitle")}
          dubFocusClipId={dubFocusClipId}
          onClearDubFocus={() => setDubFocusClipId(null)}
        />
      ) : (
        <section aria-label={t(panels.tab === "transcript" ? "transcriptTab" : "subtitleTab")} className="editor-pane min-h-0 overflow-hidden bg-workspace-panel grid grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)]">
          {panels.tab === "transcript" ? (
            <TranscriptPanel
              sequence={sequence}
              onCutSegment={(clipId, srcStart, srcEnd) => cutRangeMutation.mutate({ clipId, srcStart, srcEnd })}
              onCutRanges={(cuts) => cutRangesMutation.mutate(cuts)}
              onSplitPoints={(cuts) => splitPointsMutation.mutate(cuts)}
              onGenerateSubtitles={requestGenerateSubtitles}
              generatingSubtitles={generateSubtitlesMutation.isPending}
            />
          ) : (
            <SubtitlePanel
              sequence={sequence}
              onSetText={(clipId, text) => setTextMutation.mutate({ clipId, text })}
              onApplyTexts={(texts) => setTextsMutation.mutateAsync(texts)}
              onAddSubtitle={() => addSubtitleMutation.mutate()}
              onGenerate={requestGenerateSubtitles}
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
              onImportFile={(file, options) => importSubtitleMutation.mutate({ file, ...options })}
              onSetTiming={(clipId, payload) => trimClipMutation.mutate({ clipId, payload })}
              importingFile={importSubtitleMutation.isPending}
              onDub={(clipId) => {
                setDubFocusClipId(clipId ?? null);
                panels.setTab("voice");
              }}
            />
          )}
        </section>
      )}
      {/* 单行:`auto` 那一行原本给监视器上方的操作条,操作条搬进时间线工具栏之后,
          Monitor 落进 auto 行 —— 高度按内容算,画框直接塌成一条。 */}
      <section className="editor-monitor grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)] overflow-hidden bg-[var(--monitor-bg)]">
        <Monitor
          sequence={sequence}
          subtitleStyleOverride={styleDraft}
          assets={sequenceAssets}
          onSetTransform={(clipId, transform) => setTransformMutation.mutateAsync({ clipId, transform })}
          onSetText={(clipId, text) => setTextMutation.mutate({ clipId, text })}
          onRefreshAssets={() => void qc.invalidateQueries({ queryKey: assetKeys.all(workspace.id) })}
        />
      </section>
      {showInspector &&
        (() => {
          const inspector = (
            <Inspector
              workspaceId={workspace.id}
              selectedClip={selectedClip}
              assets={sequenceAssets}
              isTitleText={isTitleText}
              onDeleteClip={(clipId) => deleteClipMutation.mutate(clipId)}
              onSetEffects={(clipId, effects) => setEffectsMutation.mutate({ clipId, effects })}
              onSetTransform={(clipId, transform) => setTransformMutation.mutate({ clipId, transform })}
              onSetSpeed={(clipId, speed) => setSpeedMutation.mutate({ clipId, speed })}
              onSetGain={(clipId, gain, muted) => setGainMutation.mutate({ clipId, gain, muted })}
              onSetText={(clipId, text) => setTextMutation.mutate({ clipId, text })}
              fonts={fonts.data ?? []}
              onUploadFont={(file) => uploadFontMutation.mutate(file)}
              onDeleteFont={(fontId) => deleteFontMutation.mutate(fontId)}
              uploadingFont={uploadFontMutation.isPending}
              onClose={!inspectorInGrid ? () => useEditorStore.getState().selectClip(null) : undefined}
              fps={sequence.fps}
            />
          );
          return !inspectorInGrid ? <div className="canvas-overlay-surface absolute right-0 top-0 z-[60] grid w-[min(320px,90%)] border-l border-divider [&>section]:h-full [&>section]:rounded-none [&>section]:border-0" style={{ bottom: panelsRowBottom }}>{inspector}</div> : inspector;
        })()}
      {agentOpen === "on" && (
        // 停靠态是 top row 的最后一列：监视器真实让出宽度，而不是被一块 absolute 面板盖住。
        // 浮动态由 CanvasAgentChat 自己 fixed 定位；contents 防止外层生成一个空 grid 单元。
        <div
          data-testid="editor-agent-slot"
          className={dockedAgent ? "editor-agent-inline z-30 grid min-h-0 min-w-0 border-l border-divider" : agentMode === "docked" ? "absolute right-2 top-2 z-40 grid w-[min(400px,90%)]" : "contents"}
          style={!dockedAgent && agentMode === "docked" ? { bottom: panelsRowBottom + 8 } : undefined}
        >
          <SectionBoundary onClose={() => setAgentOpen("off")}>
          <CanvasAgentChat
            contextLine={agentContext}
            emptyHint={t("editorAgentEmpty")}
            placeholder={t("editorAgentPlaceholder")}
            rectKey="mosael.editor.agent.rect.v1"
            dockedLayout={dockedAgent ? "inline" : "overlay"}
            workspaceId={workspace.id}
            place={agentPlace}
            mode={agentMode}
            onModeChange={setAgentMode}
            onClose={() => setAgentOpen("off")}
          />
          </SectionBoundary>
        </div>
      )}
      <section className="editor-timeline col-span-full min-h-0 overflow-hidden border-t border-divider bg-[var(--timeline-bg)]">
        <Timeline
          sequence={sequence}
          assets={sequenceAssets}
          onInsertClip={(args) => insertClipMutation.mutate(args)}
          onMoveClip={(clipId, timelineStart, trackId, ripple, link) =>
            moveClipMutation.mutate({ clipId, timelineStart, trackId, ripple, link })
          }
          onMoveClips={(moves, link) => moveClipsMutation.mutate({ moves, link })}
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
          onDeleteClips={(clipIds) => deleteClipsMutation.mutate(clipIds)}
          onRippleDeleteClips={(clipIds) => rippleDeleteMutation.mutate(clipIds)}
          onSplitClip={(clipId) => splitAtPlayhead(clipId)}
          onGrabFrame={() => grabFrameMutation.mutate()}
          grabbingFrame={grabFrameMutation.isPending}
          onSplitClipAt={(clipId, srcTime) => splitMutation.mutate({ clipId, srcTime })}
          onDuplicateClip={(clipId) => duplicateClip(clipId)}
          onDuplicateClipsAt={duplicateClipsAt}
          onDetachAudio={(clipId) => detachAudioMutation.mutate(clipId)}
          onReplaceMedia={setReplacingClipId}
          onClipAudio={(clipId, action) => clipAudioMutation.mutate({ clipId, action })}
          onSetTrackState={(trackId, body) => trackStateMutation.mutate({ trackId, body })}
          toolbarExtra={
            <SequenceSettings
              sequence={sequence}
              pending={reframeMutation.isPending}
              onReframe={(width, height, fillMode) => reframeMutation.mutate({ width, height, fillMode })}
            />
          }
        />
      </section>
    </div>
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

/** Working modes share the command bar; panel actions stay inside their own pane. */
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
    <div ref={ref} className="flex min-w-0 flex-wrap items-center gap-1">
      {tabs.map((item) => (
        <button
          key={item.key}
          type="button"
          data-active={item.key === tab || undefined}
          aria-pressed={item.key === tab}
          className={cn("editor-mode-tab", item.key === tab && "is-active")}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function clipsOf(sequence: Sequence | null): Clip[] {
  return (sequence?.tracks ?? []).flatMap((track) => track.clips ?? []);
}

function clipIdsOf(sequence: Sequence | null): string[] {
  return clipsOf(sequence).map((item) => item.id);
}
