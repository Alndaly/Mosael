import React from "react";
import { useQueries } from "@tanstack/react-query";
import { AudioLines, BetweenHorizontalStart, ChevronDown, ChevronUp, CircleHelp, Copy, Film, Lock, LockOpen, Magnet, Minus, MousePointer2, Plus, Replace, Scissors, Slice, Trash2, Type, Volume2, VolumeX, Waves, X } from "lucide-react";

import { fetchWaveform, type Asset, type Sequence, type Track, type WaveformData } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  clipEnd,
  formatRulerLabel,
  formatTimecode,
  pxToTime,
  resolveMove,
  resolveTrim,
  rulerTicks,
  sequenceDuration,
  snapTimeTiered,
  timeToPx,
  trackEdgeTimes,
} from "@/domain/timeline/geometry";
import { downsamplePeaks, slicePeaks } from "@/domain/timeline/waveform";
import { MIN_PX_PER_SECOND, useEditorStore } from "@/stores/editorStore";
import { TimelineClip } from "./TimelineClip";
import { cn } from "@/lib/utils";
import { useDndMonitor, useDroppable, type DragEndEvent, type DragMoveEvent } from "@dnd-kit/core";

const TRACK_HEIGHT = 48;
const RULER_HEIGHT = 26;

// Peaks are expensive (slice + downsample over the whole waveform) and were recomputed for
// EVERY audio clip on EVERY dragDraft change — the drag felt laggy. Cache by the inputs that
// actually affect the shape; during a drag only the dragged clip's key changes, the rest hit.
function cachedPeaks(
  cache: Map<string, number[]>,
  assetId: string,
  waveform: WaveformData,
  srcIn: number,
  srcOut: number,
  clipWidth: number,
): number[] {
  const buckets = Math.max(24, Math.floor(clipWidth / 3));
  const key = `${assetId}:${srcIn.toFixed(3)}:${srcOut.toFixed(3)}:${buckets}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const value = downsamplePeaks(slicePeaks(waveform.peaks, waveform.duration, srcIn, srcOut), buckets);
  if (cache.size > 400) cache.clear();
  cache.set(key, value);
  return value;
}

export interface TrimPayload {
  timeline_start: number;
  src_in: number;
  src_out: number;
}

export function Timeline({
  sequence,
  assets,
  onInsertClip,
  onMoveClip,
  onMoveClipToNewLayer,
  onTrimClip,
  onAddTrack,
  onMoveTrack,
  onRemoveTrack,
  onDeleteClip,
  onRippleDeleteClip,
  onSplitClip,
  onSplitClipAt,
  onDuplicateClip,
  onDetachAudio,
  onSetTrackState,
  toolbarExtra,
}: {
  sequence: Sequence;
  assets: Asset[];
  onInsertClip: (args: { trackId: string; assetId: string; timelineStart: number; srcIn: number; srcOut: number }) => void;
  onMoveClip: (clipId: string, timelineStart: number, trackId?: string, ripple?: boolean) => void;
  onMoveClipToNewLayer?: (clipId: string, timelineStart: number) => void;
  onTrimClip: (clipId: string, payload: TrimPayload) => void;
  onAddTrack?: (kind: "video" | "audio" | "subtitle") => void;
  onMoveTrack?: (trackId: string, direction: "up" | "down") => void;
  /** Second argument is how many clips are on the track, so the caller can confirm first. */
  onRemoveTrack?: (trackId: string, clipCount: number) => void;
  onDeleteClip?: (clipId: string) => void;
  onRippleDeleteClip?: (clipId: string) => void;
  onSplitClip?: (clipId: string) => void;
  onSplitClipAt?: (clipId: string, srcTime: number) => void;
  onDuplicateClip?: (clipId: string) => void;
  onDetachAudio?: (clipId: string) => void;
  onSetTrackState?: (trackId: string, body: { muted?: boolean; locked?: boolean; solo?: boolean; duck?: boolean }) => void;
  toolbarExtra?: React.ReactNode;
}) {
  const t = useI18n();
  // NOTE: Timeline deliberately does NOT subscribe to playhead — during playback it ticks
  // ~25×/s and would re-render every clip + waveform (the "播放卡顿" on dense segments).
  // The moving playhead line and the toolbar readout are isolated in tiny subscriber
  // components below; handlers that need the current value read it via getState().
  const pxPerSecond = useEditorStore((state) => state.pxPerSecond);
  const rawDragDraft = useEditorStore((state) => state.dragDraft);
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds);
  const { setPlayhead, selectClip, setDragDraft, setPxPerSecond } = useEditorStore.getState();
  const [snapEnabled, setSnapEnabled] = React.useState(true);
  const canvasRef = React.useRef<HTMLDivElement | null>(null);
  const hscrollRef = React.useRef<HTMLDivElement | null>(null);
  const labelsRef = React.useRef<HTMLDivElement | null>(null);
  const peaksCache = React.useRef<Map<string, number[]>>(new Map());
  const draggingAsset = useEditorStore((state) => state.draggingAsset);
  const tool = useEditorStore((state) => state.tool);
  const editMode = useEditorStore((state) => state.editMode);
  const [dropGhost, setDropGhost] = React.useState<{ trackId: string; start: number; duration: number } | null>(null);
  const [marquee, setMarquee] = React.useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const [helpOpen, setHelpOpen] = React.useState(false);
  // True while dragging a video clip above the top track — drop creates a new layer.
  const [newLayerDrag, setNewLayerDrag] = React.useState(false);

  // Follow the playhead during playback: page-scroll the timeline so the cursor stays in view
  // (like Premiere/DaVinci). Subscribes to the store directly so the Timeline doesn't re-render
  // on the ~25×/s tick; only nudges scrollLeft when the playhead nears the edge or jumps.
  React.useEffect(() => {
    const follow = () => {
      const { playhead, playing } = useEditorStore.getState();
      if (!playing) return;
      const el = hscrollRef.current;
      if (!el) return;
      const px = timeToPx(playhead, pxPerSecond);
      const margin = el.clientWidth * 0.12;
      // Past the right edge → page forward (playhead lands near the left); before the left edge
      // (a loop or seek-back) → bring it into view.
      if (px > el.scrollLeft + el.clientWidth - margin || px < el.scrollLeft) {
        el.scrollLeft = Math.max(0, px - margin);
      }
    };
    return useEditorStore.subscribe(follow);
  }, [pxPerSecond]);

  const tracks = sequence.tracks ?? [];
  const allClips = React.useMemo(() => tracks.flatMap((track) => track.clips ?? []), [tracks]);

  // 落位动画(老 mibu-video 同款):提交回包落进缓存、而 EditorView 的效应还没清草稿的
  // 那一帧,缓存已是终值 — 把"追平了缓存的 settling 草稿"视作已清,片段在该帧带着
  // 过渡从松手位置滑向终点;涟漪预览同帧归零,不会二次位移。草稿存活期间(含这一帧)
  // 过渡类保持挂载,松手前的拖拽本体则以 duration-0 保证 1:1 跟手。
  const dragDraft = React.useMemo(() => {
    if (!rawDragDraft?.settling) return rawDragDraft;
    const committed = allClips.find((item) => item.id === rawDragDraft.clipId);
    if (!committed) return rawDragDraft;
    const committedTrack = tracks.find((track) => (track.clips ?? []).some((c) => c.id === rawDragDraft.clipId));
    const eq = (a: number, b: number) => Math.abs(a - b) < 1e-6;
    const caughtUp =
      committedTrack?.id === rawDragDraft.trackId &&
      eq(committed.timeline_start, rawDragDraft.timeline_start) &&
      eq(committed.src_in, rawDragDraft.src_in) &&
      eq(committed.src_out, rawDragDraft.src_out);
    return caughtUp ? null : rawDragDraft;
  }, [rawDragDraft, allClips, tracks]);
  // 有草稿在场才开过渡 — 平时缩放/刷新保持零动画。草稿清掉后再多挂 220ms:
  // 落位滑行正在进行,过早摘掉过渡类会把动画掐断成瞬移。
  const [animateClips, setAnimateClips] = React.useState(false);
  React.useEffect(() => {
    if (rawDragDraft) {
      setAnimateClips(true);
      return;
    }
    const timer = window.setTimeout(() => setAnimateClips(false), 220);
    return () => window.clearTimeout(timer);
  }, [rawDragDraft]);

  // Insert mode: while dragging, downstream clips on the target track visibly part
  // to make room (DaVinci "段落挤开"). This is the timeline width of the dragged clip.
  const dragMoveDuration = React.useMemo(() => {
    if (!dragDraft || dragDraft.kind !== "move") return 0;
    const src = allClips.find((item) => item.id === dragDraft.clipId);
    return src ? (dragDraft.src_out - dragDraft.src_in) / (src.speed || 1) : 0;
  }, [dragDraft, allClips]);

  // Insert-mode ripple preview: downstream clips on the target track part only by
  // the actual overlap (mirrors the backend), so a nudge doesn't shove everything.
  const insertRipple = React.useMemo(() => {
    if (editMode !== "insert" || !dragDraft || dragDraft.kind !== "move") return null;
    const start = dragDraft.timeline_start;
    const end = start + dragMoveDuration;
    const downstream = (tracks.find((t) => t.id === dragDraft.trackId)?.clips ?? []).filter(
      (c) => c.id !== dragDraft.clipId && c.timeline_start >= start - 1e-9,
    );
    if (!downstream.length) return null;
    const shift = end - Math.min(...downstream.map((c) => c.timeline_start));
    return shift > 1e-9 ? { trackId: dragDraft.trackId, from: start, shift } : null;
  }, [editMode, dragDraft, dragMoveDuration, tracks]);
  const assetById = React.useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);

  // Waveforms for audio-track clips whose assets have a cached waveform.
  const waveformAssetIds = React.useMemo(() => {
    const ids = new Set<string>();
    for (const track of tracks) {
      // Video clips carry their own audio too — show its waveform, like PR/DaVinci.
      if (track.kind !== "audio" && track.kind !== "video") continue;
      for (const clip of track.clips ?? []) {
        if (clip.asset_id && assetById.get(clip.asset_id)?.media_info.has_waveform) ids.add(clip.asset_id);
      }
    }
    return [...ids];
  }, [tracks, assetById]);
  const waveformQueries = useQueries({
    queries: waveformAssetIds.map((assetId) => ({
      queryKey: ["waveform", assetId],
      queryFn: () => fetchWaveform(assetId),
      staleTime: Infinity,
    })),
  });
  const waveformByAsset = React.useMemo(() => {
    const map = new Map<string, WaveformData>();
    waveformQueries.forEach((query, index) => {
      if (query.data) map.set(waveformAssetIds[index], query.data);
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waveformAssetIds, ...waveformQueries.map((query) => query.data)]);

  const duration = sequenceDuration(allClips) + 10;
  const contentWidth = timeToPx(duration, pxPerSecond) + 120;

  // Zoom out can't go below "the whole timeline fits the viewport" — past that is dead space.
  const applyZoom = (factor: number) => {
    const viewport = hscrollRef.current?.clientWidth ?? 0;
    const fitPx = viewport > 0 ? Math.max(MIN_PX_PER_SECOND, (viewport - 130) / Math.max(duration, 1)) : MIN_PX_PER_SECOND;
    setPxPerSecond(Math.max(fitPx, pxPerSecond * factor));
  };
  const ticks = rulerTicks(0, duration, pxPerSecond);

  const timeAtPointer = (event: { clientX: number }): number => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    return Math.max(0, pxToTime(event.clientX - rect.left, pxPerSecond));
  };

  const capturePointer = (element: Element, pointerId: number) => {
    try {
      element.setPointerCapture(pointerId);
    } catch {
      // Synthetic events and stale pointer ids can't be captured; drag still works.
    }
  };

  const handleRulerPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    capturePointer(event.currentTarget, event.pointerId);
    setPlayhead(timeAtPointer(event));
  };

  const handleRulerPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.buttons & 1) setPlayhead(timeAtPointer(event));
  };

  const laneTrackAt = (clientY: number, sourceKind: string): Track | null => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const laneIndex = Math.floor((clientY - rect.top - RULER_HEIGHT) / TRACK_HEIGHT);
    const candidate = tracks[laneIndex];
    if (!candidate || candidate.kind !== sourceKind || candidate.locked) return null;
    return candidate;
  };

  const startMarquee = (event: React.PointerEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const origin = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    let moved = false;

    const onMove = (moveEvent: PointerEvent) => {
      const x = moveEvent.clientX - rect.left;
      const y = moveEvent.clientY - rect.top;
      if (!moved && Math.abs(x - origin.x) < 4 && Math.abs(y - origin.y) < 4) return;
      moved = true;
      setMarquee({ x1: origin.x, y1: origin.y, x2: x, y2: y });
      const t1 = pxToTime(Math.min(origin.x, x), pxPerSecond);
      const t2 = pxToTime(Math.max(origin.x, x), pxPerSecond);
      const rowTop = Math.floor((Math.min(origin.y, y) - RULER_HEIGHT) / TRACK_HEIGHT);
      const rowBottom = Math.floor((Math.max(origin.y, y) - RULER_HEIGHT) / TRACK_HEIGHT);
      const hits: string[] = [];
      tracks.forEach((track, index) => {
        if (index < rowTop || index > rowBottom) return;
        for (const clip of track.clips ?? []) {
          if (clip.timeline_start < t2 && clipEnd(clip) > t1) hits.push(clip.id);
        }
      });
      useEditorStore.getState().selectClips(hits);
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      setMarquee(null);
      if (!moved) selectClip(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  /** 拖片段贴近轨道区上下边缘时纵向自动滚动,滚出视口的目标轨也够得着(老版同款,
   *  EDGE 28 / STEP 18)。只做纵向 — 横向自动滚动会让 viewport 相对的拖拽坐标漂移。 */
  const autoScrollLanes = (clientY: number) => {
    const el = hscrollRef.current;
    if (!el || el.scrollHeight - el.clientHeight <= 1) return;
    const rect = el.getBoundingClientRect();
    const EDGE = 28;
    const STEP = 18;
    if (clientY < rect.top + EDGE) el.scrollTop = Math.max(0, el.scrollTop - STEP);
    else if (clientY > rect.bottom - EDGE) el.scrollTop += STEP;
  };

  const startClipDrag = (event: React.PointerEvent, track: Track, clipId: string) => {
    const clip = (track.clips ?? []).find((item) => item.id === clipId);
    if (!clip || track.locked) return;
    if (tool === "blade") {
      // Blade (B): one click cuts the clip right where you clicked.
      if (onSplitClipAt) {
        const clickTime = timeAtPointer(event);
        const srcTime = clip.src_in + (clickTime - clip.timeline_start) * (clip.speed || 1);
        onSplitClipAt(clip.id, srcTime);
      }
      return;
    }
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      useEditorStore.getState().toggleSelectClip(clip.id);
      return;
    }
    if (!useEditorStore.getState().selectedClipIds.includes(clip.id)) selectClip(clip.id);
    const startX = event.clientX;
    const origin = { ...clip };
    // 两级吸附候选在起手时算好:每条轨一份边缘表(拖到哪条 lane,哪条就是第一
    // 优先级),播放头/零点与其余轨道的边缘降为次级 — 否则字幕轨的密集 cue 边界
    // 或播放头会比同轨邻居更近,把肉眼可见的对接"抢走"。
    const dragPlayhead = useEditorStore.getState().playhead;
    const edgesByTrack = new Map(
      snapEnabled ? tracks.map((t) => [t.id, trackEdgeTimes(t.clips ?? [], clip.id)] as const) : [],
    );
    const snapSetsFor = (laneId: string | null): { primary: number[]; secondary: number[] } => {
      if (!snapEnabled) return { primary: [], secondary: [] };
      const primary = (laneId && edgesByTrack.get(laneId)) || [];
      const secondary = [0, dragPlayhead];
      for (const [id, edges] of edgesByTrack) if (id !== laneId) secondary.push(...edges);
      return { primary, secondary };
    };

    // Listen on window, NOT the clip element: a cross-track drag hides the clip in its
    // source lane (it unmounts), which would sever element-bound listeners mid-drag and
    // freeze the drag with no pointerup. window survives the unmount. (Mirrors startMarquee.)
    let wantNewLayer = false;
    const onMove = (moveEvent: PointerEvent) => {
      autoScrollLanes(moveEvent.clientY);
      const rect = canvasRef.current?.getBoundingClientRect();
      // Dragged above the topmost lane → intent to spin up a new video layer.
      wantNewLayer = Boolean(
        rect && onMoveClipToNewLayer && track.kind === "video" && moveEvent.clientY - rect.top - RULER_HEIGHT < 0,
      );
      setNewLayerDrag(wantNewLayer);
      const lane = wantNewLayer ? null : laneTrackAt(moveEvent.clientY, track.kind);
      const rawStart = origin.timeline_start + pxToTime(moveEvent.clientX - startX, pxPerSecond);
      const sets = snapSetsFor(lane?.id ?? (wantNewLayer ? null : track.id));
      const resolved = resolveMove(origin, rawStart, sets.primary, sets.secondary, pxPerSecond);
      useEditorStore.getState().setDragDraft({
        clipId: clip.id,
        trackId: lane?.id ?? track.id,
        timeline_start: resolved,
        src_in: origin.src_in,
        src_out: origin.src_out,
        kind: "move",
      });
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      setNewLayerDrag(false);
      const draft = useEditorStore.getState().dragDraft;
      // 提交前先把草稿标成 settling(而不是清掉):回包在途的几十毫秒里草稿继续把
      // 片段钉在松手位置,不闪回原位;顶部的 collapse memo 则靠这个标记区分
      // "拖拽中经过原点"(不能折叠)和"提交已落缓存"(该折叠、放落位动画)。
      if (wantNewLayer && onMoveClipToNewLayer && draft && draft.clipId === clip.id) {
        useEditorStore.getState().setDragDraft({ ...draft, settling: true });
        onMoveClipToNewLayer(clip.id, draft.timeline_start);
      } else if (
        draft &&
        draft.clipId === clip.id &&
        (draft.timeline_start !== origin.timeline_start || draft.trackId !== track.id)
      ) {
        // Insert mode ripples the destination track's downstream clips aside.
        const ripple = useEditorStore.getState().editMode === "insert";
        useEditorStore.getState().setDragDraft({ ...draft, settling: true });
        onMoveClip(clip.id, draft.timeline_start, draft.trackId !== track.id ? draft.trackId : undefined, ripple);
      } else {
        useEditorStore.getState().setDragDraft(null);
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const startClipTrim = (event: React.PointerEvent, track: Track, clipId: string, edge: "start" | "end") => {
    const clip = (track.clips ?? []).find((item) => item.id === clipId);
    if (!clip || track.locked) return;
    event.stopPropagation();
    selectClip(clip.id);
    const origin = { ...clip };
    const asset = clip.asset_id ? assetById.get(clip.asset_id) : undefined;
    const assetDuration = typeof asset?.media_info.duration === "number" ? asset.media_info.duration : null;
    // 裁剪吸附与移动同级:本轨邻居边缘优先,播放头/零点/其他轨道次级。
    const trimPrimary = snapEnabled ? trackEdgeTimes(track.clips ?? [], clip.id) : [];
    const trimSecondary = snapEnabled
      ? [0, useEditorStore.getState().playhead, ...tracks.filter((t) => t.id !== track.id).flatMap((t) => trackEdgeTimes(t.clips ?? [], clip.id))]
      : [];
    const target = event.currentTarget as HTMLElement;
    capturePointer(target, event.pointerId);

    const onMove = (moveEvent: PointerEvent) => {
      let rawTime = timeAtPointer(moveEvent);
      if (snapEnabled) rawTime = snapTimeTiered(rawTime, trimPrimary, trimSecondary, pxPerSecond).time;
      const result = resolveTrim(origin, edge, rawTime, assetDuration);
      useEditorStore.getState().setDragDraft({
        clipId: clip.id,
        trackId: track.id,
        ...result,
        kind: edge === "start" ? "trim-start" : "trim-end",
      });
    };
    const onUp = () => {
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
      const draft = useEditorStore.getState().dragDraft;
      if (draft && draft.clipId === clip.id) {
        // 与移动同理:settling 草稿钉住裁剪结果等回包,缓存追平后由过渡完成落位。
        useEditorStore.getState().setDragDraft({ ...draft, settling: true });
        onTrimClip(clip.id, { timeline_start: draft.timeline_start, src_in: draft.src_in, src_out: draft.src_out });
      }
    };
    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
  };

  // 素材拖入:dnd-kit 指针事件(原生 HTML5 DnD 在 Electron 下不可靠,已弃用)。
  const dndPointerX = (event: DragMoveEvent | DragEndEvent): number =>
    ((event.activatorEvent as PointerEvent).clientX ?? 0) + event.delta.x;
  // 素材落轨的吸附:目标轨边缘优先,播放头/零点/其他轨道次级(与片段移动同级)。
  const snapDropStart = (start: number, target: Track): number =>
    snapTimeTiered(
      start,
      trackEdgeTimes(target.clips ?? [], null),
      [0, useEditorStore.getState().playhead, ...tracks.filter((t) => t.id !== target.id).flatMap((t) => trackEdgeTimes(t.clips ?? [], null))],
      pxPerSecond,
    ).time;
  useDndMonitor({
    onDragMove(event) {
      const asset = event.active.data.current?.asset as Asset | undefined;
      if (!asset) return;
      const track = event.over?.data.current?.track as Track | undefined;
      if (!track || track.locked || !trackAcceptsAsset(track, asset)) {
        setDropGhost(null);
        return;
      }
      const assetDuration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : 5;
      let start = timeAtPointer({ clientX: dndPointerX(event) });
      if (snapEnabled) start = snapDropStart(start, track);
      setDropGhost({ trackId: track.id, start, duration: assetDuration });
    },
    onDragEnd(event) {
      setDropGhost(null);
      const asset = event.active.data.current?.asset as Asset | undefined;
      const track = event.over?.data.current?.track as Track | undefined;
      if (!asset || !track || !trackAcceptsAsset(track, asset) || track.locked) return;
      const assetDuration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : 5;
      let start = timeAtPointer({ clientX: dndPointerX(event) });
      if (snapEnabled) start = snapDropStart(start, track);
      onInsertClip({
        trackId: track.id,
        assetId: asset.id,
        timelineStart: start,
        srcIn: 0,
        srcOut: assetDuration,
      });
    },
    onDragCancel() {
      setDropGhost(null);
    },
  });


  const handleWheel = (event: React.WheelEvent) => {
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      applyZoom(event.deltaY < 0 ? 1.15 : 1 / 1.15);
    }
  };

  return (
    <div className="grid h-full grid-rows-[auto_minmax(0,1fr)]" data-tool={tool} onWheel={handleWheel}>
      <div className="flex flex-wrap items-center justify-between gap-y-0.5 border-b border-border bg-panel px-1.5 py-0.5">
        <div className="flex min-w-0 flex-nowrap items-center gap-2">
          <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border whitespace-nowrap" role="group" aria-label={t("editTools")}>
            <button
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", tool === "select" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              title={t("toolSelectHint")}
              aria-pressed={tool === "select"}
              onClick={() => useEditorStore.getState().setTool("select")}
            >
              <MousePointer2 size={12} /> {t("toolSelect")}
            </button>
            <button
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", tool === "blade" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              title={t("toolBladeHint")}
              aria-pressed={tool === "blade"}
              onClick={() => useEditorStore.getState().setTool("blade")}
            >
              <Slice size={12} /> {t("toolBlade")}
            </button>
          </div>
          <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border whitespace-nowrap" role="group" aria-label={t("editMode")}>
            <button
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", editMode === "overwrite" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              title={t("editModeOverwriteHint")}
              aria-pressed={editMode === "overwrite"}
              onClick={() => useEditorStore.getState().setEditMode("overwrite")}
            >
              <Replace size={12} /> {t("editModeOverwrite")}
            </button>
            <button
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", editMode === "insert" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              title={t("editModeInsertHint")}
              aria-pressed={editMode === "insert"}
              onClick={() => useEditorStore.getState().setEditMode("insert")}
            >
              <BetweenHorizontalStart size={12} /> {t("editModeInsert")}
            </button>
          </div>
          <PlayheadReadout total={sequenceDuration(allClips)} />
          <span className="whitespace-nowrap text-[11px] text-muted-foreground">
            {t("clipCount").replace("{n}", String(allClips.length))} · {sequence.width}×{sequence.height} ·{" "}
            {Math.round(sequence.fps)}fps
          </span>
        </div>
        <div className="flex items-center gap-0.5">
          {toolbarExtra}
          {(onSplitClip || onDuplicateClip || onDeleteClip) && <span className="mx-[3px] h-4 w-px bg-border" />}
          {onSplitClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  disabled={!selectedClipIds.length}
                  onClick={() => selectedClipIds[0] && onSplitClip(selectedClipIds[selectedClipIds.length - 1])}
                  aria-label={t("splitAtPlayhead")}
                >
                  <Scissors size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("splitAtPlayhead")}</TooltipContent>
            </Tooltip>
          )}
          {onDuplicateClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  disabled={!selectedClipIds.length}
                  onClick={() => selectedClipIds[0] && onDuplicateClip(selectedClipIds[selectedClipIds.length - 1])}
                  aria-label={t("duplicateClip")}
                >
                  <Copy size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("duplicateClip")}</TooltipContent>
            </Tooltip>
          )}
          {onRippleDeleteClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  disabled={!selectedClipIds.length}
                  onClick={() => selectedClipIds.forEach((clipId) => onRippleDeleteClip(clipId))}
                  aria-label={t("rippleDelete")}
                >
                  <Waves size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("rippleDelete")}</TooltipContent>
            </Tooltip>
          )}
          {onDeleteClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  disabled={!selectedClipIds.length}
                  onClick={() => selectedClipIds.forEach((clipId) => onDeleteClip(clipId))}
                  aria-label={t("deleteClip")}
                >
                  <Trash2 size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("deleteClip")}</TooltipContent>
            </Tooltip>
          )}
          <span className="mx-[3px] h-4 w-px bg-border" />
          {onAddTrack && (
            <>
              <button type="button" className="inline-flex h-6 cursor-pointer items-center gap-[3px] whitespace-nowrap rounded-md border-0 bg-transparent px-1.5 text-[11.5px] text-muted-foreground transition-[background,color] duration-100 hover:bg-secondary hover:text-foreground" title={t("addVideoTrackHint")} onClick={() => onAddTrack("video")}>
                <Plus size={11} />
                <Film size={12} /> {t("trackVideoShort")}
              </button>
              <button type="button" className="inline-flex h-6 cursor-pointer items-center gap-[3px] whitespace-nowrap rounded-md border-0 bg-transparent px-1.5 text-[11.5px] text-muted-foreground transition-[background,color] duration-100 hover:bg-secondary hover:text-foreground" title={t("addAudioTrackHint")} onClick={() => onAddTrack("audio")}>
                <Plus size={11} />
                <AudioLines size={12} /> {t("trackAudioShort")}
              </button>
              <button type="button" className="inline-flex h-6 cursor-pointer items-center gap-[3px] whitespace-nowrap rounded-md border-0 bg-transparent px-1.5 text-[11.5px] text-muted-foreground transition-[background,color] duration-100 hover:bg-secondary hover:text-foreground" title={t("addSubtitleTrackHint")} onClick={() => onAddTrack("subtitle")}>
                <Plus size={11} />
                <Type size={12} /> {t("trackSubtitleShort")}
              </button>
            </>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn("h-7 w-7", snapEnabled && "bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
                onClick={() => setSnapEnabled((value) => !value)}
                aria-pressed={snapEnabled}
                aria-label="Snap"
              >
                <Magnet size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Snap</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => applyZoom(1 / 1.3)} aria-label={t("zoomOut")}>
                <Minus size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("zoomOut")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => applyZoom(1.3)} aria-label={t("zoomIn")}>
                <Plus size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("zoomIn")}</TooltipContent>
          </Tooltip>
          <Popover open={helpOpen} onOpenChange={setHelpOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn("h-7 w-7", helpOpen && "bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
                aria-label={t("shortcutsHelp")}
              >
                <CircleHelp size={14} />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="grid w-[300px] gap-1.5 px-3 py-2.5 [&_strong]:mb-0.5 [&_strong]:text-xs" aria-label={t("shortcutsHelp")}>
              <strong>{t("shortcutsHelp")}</strong>
              {[
                ["Space", t("hintPlayPause")],
                ["A / B", t("hintTools")],
                ["S", t("hintSplit")],
                ["⌘D", t("hintDuplicate")],
                ["Delete", t("hintDelete")],
                ["⇧Delete", t("hintRipple")],
                ["⌘Z / ⇧⌘Z", t("hintUndoRedo")],
                ["← / →", t("hintFrameStep")],
                ["⇧点击", t("hintMultiSelect")],
                [t("hintDragLabel"), t("hintDragBody")],
                ["↕", t("hintVerticalDrag")],
              ].map(([key, body]) => (
                <div className="grid grid-cols-[92px_minmax(0,1fr)] items-baseline gap-1.5 text-xs [&_kbd]:justify-self-start [&_kbd]:whitespace-nowrap [&_kbd]:rounded-sm [&_kbd]:border [&_kbd]:border-b-2 [&_kbd]:border-border [&_kbd]:bg-secondary [&_kbd]:px-1.5 [&_kbd]:py-px [&_kbd]:font-mono [&_kbd]:text-[10.5px] [&_span]:text-muted-foreground" key={key}>
                  <kbd>{key}</kbd>
                  <span>{body}</span>
                </div>
              ))}
            </PopoverContent>
          </Popover>
        </div>
      </div>
      <div className="grid min-h-0 grid-cols-[112px_minmax(0,1fr)] overflow-hidden">
        <div className="overflow-hidden border-r border-border bg-panel" ref={labelsRef}>
          <div className="sticky top-0 z-[6] border-b border-border bg-panel" style={{ height: RULER_HEIGHT }} />
          {tracks.map((track, trackIndex) => (
            <div className="group/label flex flex-col justify-center gap-1 border-b border-[var(--track-lane-line)] px-2 text-[11px] font-semibold text-muted-foreground" key={track.id} style={{ height: TRACK_HEIGHT }}>
              <div className="flex min-w-0 items-center gap-1.5">
                <span className={cn("h-[7px] w-[7px] rounded-sm bg-[var(--track-video-border)]", track.kind === "audio" && "bg-[var(--track-audio-border)]", track.kind === "subtitle" && "bg-[#a855f7]")} />
                <span className="truncate">{track.name}</span>
                {/* Reorder sits with the name: it answers "which layer is this", not "what does
                    this track do". That also leaves the row below wide enough for the controls. */}
                {onMoveTrack && (
                <span className="ml-auto inline-flex gap-px">
                  <button
                    type="button"
                    className="grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground opacity-0 transition-[opacity,color] duration-100 enabled:hover:text-foreground disabled:cursor-default disabled:opacity-25 group-hover/label:opacity-100"
                    aria-label={t("trackMoveUp")}
                    title={t("trackMoveUp")}
                    disabled={trackIndex === 0}
                    onClick={() => onMoveTrack(track.id, "up")}
                  >
                    <ChevronUp size={12} />
                  </button>
                  <button
                    type="button"
                    className="grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground opacity-0 transition-[opacity,color] duration-100 enabled:hover:text-foreground disabled:cursor-default disabled:opacity-25 group-hover/label:opacity-100"
                    aria-label={t("trackMoveDown")}
                    title={t("trackMoveDown")}
                    disabled={trackIndex === tracks.length - 1}
                    onClick={() => onMoveTrack(track.id, "down")}
                  >
                    <ChevronDown size={12} />
                  </button>
                </span>
                )}
              </div>
              <div className="flex items-center gap-0.5">
              {onSetTrackState && (
                <span className="inline-flex gap-0.5">
                  <button
                    type="button"
                    className={cn("grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground opacity-0 transition-[opacity,color] duration-100 enabled:hover:text-foreground disabled:cursor-default disabled:opacity-25 group-hover/label:opacity-100", track.muted && "text-destructive opacity-100 enabled:hover:text-destructive")}
                    aria-label={track.muted ? t("trackUnmute") : t("trackMute")}
                    onClick={() => onSetTrackState(track.id, { muted: !track.muted })}
                  >
                    {track.muted ? <VolumeX size={11} /> : <Volume2 size={11} />}
                  </button>
                  <button
                    type="button"
                    className={cn("grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground opacity-0 transition-[opacity,color] duration-100 enabled:hover:text-foreground disabled:cursor-default disabled:opacity-25 group-hover/label:opacity-100", track.solo && "text-destructive opacity-100 enabled:hover:text-destructive")}
                    aria-label={track.solo ? t("trackUnsolo") : t("trackSolo")}
                    onClick={() => onSetTrackState(track.id, { solo: !track.solo })}
                  >
                    <span className="text-[9px] font-bold leading-none">S</span>
                  </button>
                  {track.kind === "audio" && (
                    <button
                      type="button"
                      className={cn("grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground opacity-0 transition-[opacity,color] duration-100 enabled:hover:text-foreground disabled:cursor-default disabled:opacity-25 group-hover/label:opacity-100", track.duck && "text-destructive opacity-100 enabled:hover:text-destructive")}
                      aria-label={track.duck ? t("trackUnduck") : t("trackDuck")}
                      onClick={() => onSetTrackState(track.id, { duck: !track.duck })}
                    >
                      <span className="text-[9px] font-bold leading-none">D</span>
                    </button>
                  )}
                  <button
                    type="button"
                    className={cn("grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground opacity-0 transition-[opacity,color] duration-100 enabled:hover:text-foreground disabled:cursor-default disabled:opacity-25 group-hover/label:opacity-100", track.locked && "text-destructive opacity-100 enabled:hover:text-destructive")}
                    aria-label={track.locked ? t("trackUnlock") : t("trackLock")}
                    onClick={() => onSetTrackState(track.id, { locked: !track.locked })}
                  >
                    {track.locked ? <Lock size={11} /> : <LockOpen size={11} />}
                  </button>
                </span>
              )}
              {onRemoveTrack && (
                <button
                  type="button"
                  className="grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground opacity-0 transition-[opacity,color] duration-100 hover:bg-destructive hover:text-white group-hover/label:opacity-100"
                  aria-label={(track.clips ?? []).length > 0 ? t("removeTrackWithClips") : t("removeTrack")}
                  title={(track.clips ?? []).length > 0 ? t("removeTrackWithClips") : t("removeTrack")}
                  onClick={() => onRemoveTrack(track.id, (track.clips ?? []).length)}
                >
                  <X size={11} />
                </button>
              )}
              </div>
            </div>
          ))}
        </div>
        <div
          className="min-w-0 overflow-auto"
          ref={hscrollRef}
          onScroll={(event) => {
            // Mirror vertical scroll to the labels column so track rows stay aligned.
            if (labelsRef.current) labelsRef.current.scrollTop = event.currentTarget.scrollTop;
          }}
        >
          <div className="relative min-w-full" ref={canvasRef} style={{ width: contentWidth }}>
            <div
              className="sticky top-0 z-[5] cursor-ew-resize touch-none overflow-hidden border-b border-border bg-[var(--ruler-bg)]"
              style={{ height: RULER_HEIGHT }}
              onPointerDown={handleRulerPointerDown}
              onPointerMove={handleRulerPointerMove}
            >
              {ticks.map((tick) => (
                <div
                  key={tick.time}
                  className={cn("absolute bottom-0 h-[5px] w-px bg-[var(--ruler-tick)]", tick.major && "h-[9px] [&_span]:absolute [&_span]:bottom-2 [&_span]:left-1 [&_span]:whitespace-nowrap [&_span]:text-[10px] [&_span]:text-[var(--ruler-text)]")}
                  style={{ left: timeToPx(tick.time, pxPerSecond) }}
                >
                  {tick.major && <span className="timecode">{formatRulerLabel(tick.time)}</span>}
                </div>
              ))}
            </div>
            {newLayerDrag && (
              <div className="pointer-events-none absolute inset-x-0 z-[4] flex h-[22px] items-center justify-center gap-[5px] border-y-[1.5px] border-dashed border-primary bg-[color-mix(in_srgb,var(--primary)_16%,transparent)] text-[11px] font-semibold text-primary" style={{ top: RULER_HEIGHT }}>
                <Plus size={12} /> {t("dropNewLayer")}
              </div>
            )}
            {tracks.map((track) => (
              <DroppableLane
                accepting={Boolean(
                  draggingAsset &&
                    ((track.kind === "video" && draggingAsset.kind !== "audio") ||
                      (track.kind === "audio" && draggingAsset.kind === "audio")) &&
                    !track.locked,
                )}
                key={track.id}
                track={track}
                style={{ height: TRACK_HEIGHT }}
                onPointerDown={(event) => {
                  if (event.target === event.currentTarget && event.button === 0) startMarquee(event);
                }}
              >
                {dropGhost?.trackId === track.id && (
                  <div
                    className="pointer-events-none absolute bottom-[5px] top-[5px] z-[2] rounded-md border-[1.5px] border-dashed border-primary bg-[color-mix(in_srgb,var(--primary)_14%,transparent)]"
                    style={{
                      left: timeToPx(dropGhost.start, pxPerSecond),
                      width: Math.max(12, timeToPx(dropGhost.duration, pxPerSecond)),
                    }}
                  />
                )}
                {dragDraft &&
                  dragDraft.kind === "move" &&
                  dragDraft.trackId === track.id &&
                  !(track.clips ?? []).some((item) => item.id === dragDraft.clipId) &&
                  (() => {
                    const source = allClips.find((item) => item.id === dragDraft.clipId);
                    if (!source) return null;
                    return (
                      <TimelineClip
                        key={`draft-${source.id}`}
                        trackKind={track.kind}
                        name={source.text_override ?? (source.asset_id ? assetById.get(source.asset_id)?.name ?? "" : "")}
                        left={timeToPx(dragDraft.timeline_start, pxPerSecond)}
                        width={Math.max(10, timeToPx((dragDraft.src_out - dragDraft.src_in) / (source.speed || 1), pxPerSecond))}
                        selected
                        dragging
                        onPointerDown={() => undefined}
                        onTrimPointerDown={() => undefined}
                        onSelect={() => undefined}
                      />
                    );
                  })()}
                {(track.clips ?? []).map((clip) => {
                  if (dragDraft && dragDraft.clipId === clip.id && dragDraft.trackId !== track.id) return null;
                  const draft = dragDraft && dragDraft.clipId === clip.id ? dragDraft : null;
                  const display = draft ?? clip;
                  // Insert-mode preview: clips at/after the drop point slide right by the
                  // dragged clip's duration, showing where the ripple will land them.
                  const partingShift =
                    insertRipple &&
                    insertRipple.trackId === track.id &&
                    clip.id !== dragDraft?.clipId &&
                    clip.timeline_start >= insertRipple.from - 1e-9
                      ? insertRipple.shift
                      : 0;
                  // 位移一律走 transform、left 固定在已提交位置(老 mibu-video 手法):
                  // 拖拽本体 duration-0 跟手,松手/涟漪让位则由过渡平滑滑入。
                  // 落位帧的滑行原理:提交落缓存时 left 跳到终值、shift 同帧归零,
                  // 两个属性各自做 200ms 过渡 → 视觉位置 = left+shift 从"松手点"
                  // 平滑插值到"终点";服务端原样接受落点时两者恰好抵消,纹丝不动。
                  // 裁剪草稿仍直接渲染 left/width(裁的是边缘,transform 表达不了)。
                  const isMoveDraft = Boolean(draft && draft.kind === "move");
                  const baseLeft = isMoveDraft ? clip.timeline_start : display.timeline_start;
                  const shiftTime = isMoveDraft ? display.timeline_start - clip.timeline_start : partingShift;
                  const waveform =
                    (track.kind === "audio" || track.kind === "video") && clip.asset_id
                      ? waveformByAsset.get(clip.asset_id)
                      : undefined;
                  const clipWidth = Math.max(10, timeToPx((display.src_out - display.src_in) / (clip.speed || 1), pxPerSecond));
                  const peaks =
                    waveform && clip.asset_id
                      ? cachedPeaks(peaksCache.current, clip.asset_id, waveform, display.src_in, display.src_out, clipWidth)
                      : undefined;
                  return (
                    <TimelineClip
                      key={clip.id}
                      trackKind={track.kind}
                      name={clip.text_override ?? (clip.asset_id ? assetById.get(clip.asset_id)?.name ?? clip.asset_id.slice(0, 8) : "")}
                      left={timeToPx(baseLeft, pxPerSecond)}
                      shiftPx={timeToPx(shiftTime, pxPerSecond)}
                      width={clipWidth}
                      animate={animateClips}
                      selected={selectedClipIds.includes(clip.id)}
                      dragging={Boolean(draft)}
                      peaks={peaks}
                      onPointerDown={(event) => startClipDrag(event, track, clip.id)}
                      onTrimPointerDown={(event, edge) => startClipTrim(event, track, clip.id, edge)}
                      onSelect={() => {
                        if (!useEditorStore.getState().selectedClipIds.includes(clip.id)) selectClip(clip.id);
                      }}
                      onDelete={onDeleteClip ? () => onDeleteClip(clip.id) : undefined}
                      onRippleDelete={onRippleDeleteClip ? () => onRippleDeleteClip(clip.id) : undefined}
                      onSplit={onSplitClip ? () => onSplitClip(clip.id) : undefined}
                      onDuplicate={onDuplicateClip ? () => onDuplicateClip(clip.id) : undefined}
                      onDetachAudio={
                        onDetachAudio && track.kind === "video" && clip.asset_id
                          ? () => onDetachAudio(clip.id)
                          : undefined
                      }
                    />
                  );
                })}
              </DroppableLane>
            ))}
            {dragDraft &&
              (dragDraft.kind === "trim-start" || dragDraft.kind === "trim-end") &&
              (() => {
                const source = allClips.find((item) => item.id === dragDraft.clipId);
                if (!source) return null;
                const speed = source.speed || 1;
                const duration = (dragDraft.src_out - dragDraft.src_in) / speed;
                const edgeTime =
                  dragDraft.kind === "trim-start" ? dragDraft.timeline_start : dragDraft.timeline_start + duration;
                const trackIndex = tracks.findIndex((item) => item.id === dragDraft.trackId);
                if (trackIndex < 0) return null;
                return (
                  <div
                    className="pointer-events-none absolute top-[-1px] z-[8] -translate-x-1/2 whitespace-nowrap rounded-md border border-border-strong bg-popover px-[7px] py-px text-[10.5px] tabular-nums text-foreground"
                    style={{
                      left: timeToPx(edgeTime, pxPerSecond),
                      top: RULER_HEIGHT + trackIndex * TRACK_HEIGHT - 10,
                    }}
                  >
                    {formatTimecode(edgeTime)} · {duration.toFixed(2)}s
                  </div>
                );
              })()}
            {marquee && (
              <div
                className="pointer-events-none absolute z-30 rounded-sm border border-primary bg-[color-mix(in_oklab,var(--primary)_12%,transparent)]"
                style={{
                  left: Math.min(marquee.x1, marquee.x2),
                  top: Math.min(marquee.y1, marquee.y2),
                  width: Math.abs(marquee.x2 - marquee.x1),
                  height: Math.abs(marquee.y2 - marquee.y1),
                }}
              />
            )}
            <TimelinePlayhead pxPerSecond={pxPerSecond}>
              <div className="absolute left-[-4px] top-0 h-2.5 w-[9px] bg-[var(--playhead)] [clip-path:polygon(0_0,100%_0,100%_55%,50%_100%,0_55%)]" />
            </TimelinePlayhead>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Isolated playhead subscribers: only these re-render on the ~25×/s playhead tick,
 *  not the whole Timeline (see the note at the top of Timeline). */
function TimelinePlayhead({ pxPerSecond, children }: { pxPerSecond: number; children: React.ReactNode }) {
  const playhead = useEditorStore((state) => state.playhead);
  return (
    <div className="pointer-events-none absolute bottom-0 top-0 z-[4] w-px bg-[var(--playhead)]" style={{ left: timeToPx(playhead, pxPerSecond) }}>
      {children}
    </div>
  );
}

function PlayheadReadout({ total }: { total: number }) {
  const playhead = useEditorStore((state) => state.playhead);
  return (
    <span className="timecode whitespace-nowrap text-xs font-semibold text-foreground [&_em]:not-italic [&_em]:text-muted-foreground">
      {formatTimecode(playhead)}
      <em> / {formatTimecode(total)}</em>
    </span>
  );
}

export function trackAcceptsAsset(track: Track, asset: Asset): boolean {
  if (track.kind === "video") return asset.kind === "video" || asset.kind === "image";
  if (track.kind === "audio") return asset.kind === "audio";
  return false;
}

/** 轨道格容器:dnd-kit droppable(素材拖入的命中区),接受态提亮底色。 */
function DroppableLane({
  track,
  accepting,
  style,
  onPointerDown,
  children,
}: {
  track: Track;
  accepting: boolean;
  style: React.CSSProperties;
  onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => void;
  children: React.ReactNode;
}) {
  const { setNodeRef } = useDroppable({ id: `lane-${track.id}`, data: { track } });
  return (
    <div
      ref={setNodeRef}
      className={
        accepting
          ? "relative border-b border-[var(--track-lane-line)] bg-[color-mix(in_srgb,var(--accent)_55%,var(--track-lane))]"
          : "relative border-b border-[var(--track-lane-line)] bg-[var(--track-lane)]"
      }
      style={style}
      onPointerDown={onPointerDown}
    >
      {children}
    </div>
  );
}
