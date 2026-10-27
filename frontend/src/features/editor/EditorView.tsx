import "./editor.css";
import { assetKeys } from "@/api/queryKeys";
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Plus, Redo2, Scissors, Sparkles, Type, Undo2 } from "lucide-react";

import { toast } from "sonner";
import { useRecorder } from "@/features/media/recordingContext";

import {
  api,
  listFonts,
  uploadFont,
  deleteFont,
  isSubtitleFile,
  type AssetCard,
  type Clip,
  type Project,
  type Sequence,
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
import { clipEnd, snapToFrame } from "@/domain/timeline/geometry";
import { clipContains } from "@/domain/timeline/editTargets";
import { type LeftTab, useEditorPanels } from "@/features/editor/useEditorPanels";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { HANDLE_COLUMN, HANDLE_ROW, handleOffset, useResizableSidebar } from "@/lib/useResizableSidebar";

import { selectedClipId as selectedClipIdOf, useEditorStore } from "@/features/editor/editorStore";
import { useSequenceMutations } from "@/features/editor/useSequenceMutations";
import { clipsOf } from "@/features/editor/sequenceClips";
import { useEditorShortcuts } from "@/features/editor/useEditorShortcuts";
import { ConfirmDialog } from "@/components/app/modals";
import { useImportMediaFiles } from "@/features/media/useImportMediaFiles";
import { FontFaces } from "@/features/editor/FontFaces";
import { ExportControl } from "@/features/editor/ExportControl";
import { Inspector } from "./Inspector";
import { SequenceSettings } from "./SequenceSettings";
import { MediaPool } from "./MediaPool";
import { Monitor } from "./Monitor";
import { SubtitlePanel } from "./SubtitlePanel";
import { ReplaceMediaDialog } from "./ReplaceMediaDialog";
import { TranscriptPanel } from "./TranscriptPanel";
import { VoicePanel } from "./VoicePanel";
import { Timeline, trackAcceptsAsset } from "./timeline/Timeline";
import { cn } from "@/lib/utils";
import { DndContext, DragOverlay, PointerSensor, pointerWithin, useSensor, useSensors, type DragStartEvent } from "@dnd-kit/core";
import { useDndAccessibility } from "@/components/app/dndAccessibility";

/** `#/editor?p=…&s=…` 里点名的那条时间线。 */
function namedSequenceFromHash(): string | null {
  return new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("s");
}

/** 选中项目之后的剪辑台。没有项目时由 `app/pages.tsx` 渲染项目浏览器,这里不再有第二种空态。 */
export function EditorView({ workspace, project }: { workspace: Workspace; project: Project }) {
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
  //: **跟 hashchange 走**,不是只在挂载时读一次:人已经开着剪辑页时点另一格时间线,只改 hash
  //: 不会重新挂载 EditorView,旧代码于是什么都不发生(地址里却已经是新的 `?s=`)。
  const [namedSequence, setNamedSequence] = React.useState(namedSequenceFromHash);
  React.useEffect(() => {
    const sync = () => setNamedSequence(namedSequenceFromHash());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const sequence = sequences.data?.find((one) => one.id === namedSequence) ?? sequences.data?.[0] ?? null;
  //: 时间线、监视器、检查器读的素材:**这条时间线用到的那些**,完整字段(见 useSequenceAssets)。
  //: 素材池是另一回事 —— 它一页页列素材库(MediaPool 自己取),配音片段这类中间产物不在那里,却照样在时间线上。
  const sequenceAssetsQuery = useSequenceAssets(workspace.id, sequence);
  const sequenceAssets = React.useMemo(() => sequenceAssetsQuery.data ?? [], [sequenceAssetsQuery.data]);
  const {
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
  } = useSequenceMutations({ workspaceId: workspace.id, projectId: project.id, sequence });

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

  const importFiles = useImportMediaFiles({ workspaceId: workspace.id, projectId: project.id });
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
          {/*: 纯图标:文案只进 aria-label / Hint —— 同排已经有颗 ✨(在播放头加花字),这里用 Bot 才不会混。 */}
          <IconButton
            variant="ghost"
            size="icon-sm"
            label={t("wfAgentTitle")}
            aria-pressed={agentOpen === "on"}
            onClick={() => setAgentOpen(agentOpen === "on" ? "off" : "on")}
          >
            <Bot size={14} />
          </IconButton>

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
