import React from "react";
import { useQueries } from "@tanstack/react-query";
import { AudioLines, AudioWaveform, BetweenHorizontalStart, Camera, ChevronDown, ChevronUp, CircleHelp, Copy, Eye, EyeOff, Film, Lock, LockOpen, Magnet, Maximize2, Mic, Minus, MousePointer2, Plus, Replace, Scissors, Slice, Split, Trash2, Type, Volume2, VolumeX, Waves, X } from "lucide-react";

import { fetchWaveform, type Asset, type Clip, type Sequence, type Track, type TrackStatePatch, type WaveformData } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  clipDuration,
  clipEnd,
  formatFrameTimecode,
  formatRulerLabel,
  pxToTime,
  resolveMove,
  resolveTrim,
  rulerStep,
  rulerTicks,
  sequenceDuration,
  snapTimeTiered,
  snapToFrame,
  timeToPx,
  timelineToSrc,
  trackEdgeTimes,
  trimLimits,
  uncoveredPieces,
} from "@/domain/timeline/geometry";
import { downsamplePeaks, slicePeaks } from "@/domain/timeline/waveform";
import { MAX_PX_PER_SECOND, MIN_PX_PER_SECOND, markedRange, useEditorStore } from "@/features/editor/editorStore";
import { isEditorKeyTarget } from "@/features/editor/editorKeys";
import { livePlayhead } from "@/features/editor/playback/playbackClock";
import { TimelineClip } from "./TimelineClip";
import { kindHasSound } from "@/lib/assetKinds";
import { listenKeys } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";
import { useDndMonitor, useDroppable } from "@dnd-kit/core";

const TRACK_HEIGHT = 48;
const RULER_HEIGHT = 26;

/**
 * 时间线只画视口里(含两侧缓冲)的片段与刻度。
 *
 * 一小时的访谈切成几千段、或者放到 240px/s,此前每一段、每一根刻度都在 DOM 里(1 小时 240px/s 的
 * 标尺是 28801 个 div),拖一下、点一下都要整树协调几百毫秒。缓冲取「至少一屏」:横向滚半个缓冲以内
 * 不重算窗口,滚得再远才换一批 —— 滚动本身不触发 React。
 */
const VIRTUAL_MIN_BUFFER_PX = 600;
/** 视口还没量到(首帧、测试环境)时按这个宽度开窗,而不是退回全量渲染。 */
const FALLBACK_VIEWPORT_PX = 1600;

/** 回调身份恒定、调用时总读到最新闭包 —— memo 过的片段拿它当手柄,不会因为父组件重渲而失效。 */
function useStableHandler<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = React.useRef(fn);
  React.useLayoutEffect(() => {
    ref.current = fn;
  });
  return React.useCallback((...args: A) => ref.current(...args), []);
}

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
  onMoveClips,
  onMoveClipToNewLayer,
  onTrimClip,
  onAddTrack,
  onMoveTrack,
  onRemoveTrack,
  onDeleteClips,
  onRippleDeleteClips,
  onSplitClip,
  onSplitClipAt,
  onGrabFrame,
  grabbingFrame = false,
  onDuplicateClip,
  onDuplicateClipsAt,
  onDetachAudio,
  onReplaceMedia,
  onClipAudio,
  onSetTrackState,
  toolbarExtra,
}: {
  sequence: Sequence;
  assets: Asset[];
  onInsertClip: (args: { trackId: string; assetId: string; timelineStart: number; srcIn: number; srcOut: number }) => void;
  onMoveClip: (clipId: string, timelineStart: number, trackId?: string, ripple?: boolean) => void;
  /** 组拖(框选多个后拖动)整组提交:一条操作、一步撤销。缺省时组拖降级为只移动锚点。 */
  onMoveClips?: (moves: { clipId: string; timelineStart: number; trackId?: string }[]) => void;
  onMoveClipToNewLayer?: (clipId: string, timelineStart: number) => void;
  onTrimClip: (clipId: string, payload: TrimPayload) => void;
  onAddTrack?: (kind: "video" | "audio" | "subtitle") => void;
  onMoveTrack?: (trackId: string, direction: "up" | "down") => void;
  /** Second argument is how many clips are on the track, so the caller can confirm first. */
  onRemoveTrack?: (trackId: string, clipCount: number) => void;
  /** 删掉这几段(一段也走它):一条操作、一步撤销。不给就不出删除入口。 */
  onDeleteClips?: (clipIds: string[]) => void;
  /** 波纹删除这几段,下游跟着前移。同样一条操作、一步撤销。 */
  onRippleDeleteClips?: (clipIds: string[]) => void;
  /** 不给 clipId 就切播放头下的那一段(没选中东西时也能用)。 */
  onSplitClip?: (clipId?: string) => void;
  onSplitClipAt?: (clipId: string, srcTime: number) => void;
  /** 把播放头这一帧存成素材。和剪刀一样是**播放头**的动作,所以排在它旁边。 */
  onGrabFrame?: () => void;
  grabbingFrame?: boolean;
  onDuplicateClip?: (clipId: string) => void;
  /** 按住 ⌥ 拖动松手:把这几段复制到落点(整组最早的一段落在 timelineStart);只拖一段且换了轨时给 trackId。 */
  onDuplicateClipsAt?: (clipIds: string[], timelineStart: number, trackId: string | null) => void;
  onDetachAudio?: (clipId: string) => void;
  /** 片段换成另一份素材(位置、时长、属性都不动)。 */
  onReplaceMedia?: (clipId: string) => void;
  /** 片段声音处理(降噪 / 只留人声 / 拆成人声和背景音),做完直接换到时间线上。 */
  onClipAudio?: (clipId: string, action: "denoise" | "isolate_voice" | "separate") => void;
  onSetTrackState?: (trackId: string, body: TrackStatePatch) => void;
  toolbarExtra?: React.ReactNode;
}) {
  const t = useI18n();
  //: 时间线上哪些素材是 AI 生成的(后端算好给的,见 SequenceOut.ai_asset_ids):片段上标「AI」角标。
  const aiAssetIds = React.useMemo(() => new Set(sequence.ai_asset_ids ?? []), [sequence.ai_asset_ids]);
  // NOTE: Timeline deliberately does NOT subscribe to playhead — during playback it ticks
  // ~25×/s and would re-render every clip + waveform (the "播放卡顿" on dense segments).
  // The moving playhead line and the toolbar readout are isolated in tiny subscriber
  // components below; handlers that need the current value read it via getState().
  const pxPerSecond = useEditorStore((state) => state.pxPerSecond);
  const rawDragDraft = useEditorStore((state) => state.dragDraft);
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds);
  const { setPlayhead, selectClip, setPxPerSecond } = useEditorStore.getState();
  const snapEnabled = useEditorStore((state) => state.snapEnabled);
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
  // 视口(横向滚动位置 + 可见宽度,px)。只在滚出半个缓冲时才写 state,见 VIRTUAL_MIN_BUFFER_PX。
  const [viewport, setViewport] = React.useState<{ left: number; width: number }>({ left: 0, width: 0 });
  React.useLayoutEffect(() => {
    const el = hscrollRef.current;
    if (!el) return;
    let raf = 0;
    const measure = () => {
      raf = 0;
      const left = el.scrollLeft;
      const width = el.clientWidth;
      const slack = Math.max(VIRTUAL_MIN_BUFFER_PX, width) / 2;
      setViewport((prev) => (prev.width === width && Math.abs(prev.left - left) < slack ? prev : { left, width }));
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(measure);
    };
    measure();
    el.addEventListener("scroll", schedule, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    observer?.observe(el);
    return () => {
      el.removeEventListener("scroll", schedule);
      observer?.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

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

  // 按 position 从上到下排,不信数组先后:后端改了 position(上移一条轨、新视频轨放到最上)之后,
  // 回包里的数组顺序不一定跟着变。监视器的合成层序(sceneLayersAt)同样按 position —— 两边各信
  // 各的,时间线上看着在上面的那层,画面里可能被压在下面。
  const tracks = React.useMemo(() => [...(sequence.tracks ?? [])].sort((a, b) => a.position - b.position), [sequence.tracks]);
  const allClips = React.useMemo(() => tracks.flatMap((track) => track.clips ?? []), [tracks]);

  /**
   * 右键菜单作用在谁身上:点的那一段在选区里就是整个选区,不在就只是它自己。删除 / 波纹删除因此和
   * 工具栏一样作用在整个选区上 —— 多选后右键只删被点的那一段,看着像只删了一半。
   */
  const menuTargets = (clipId: string) => {
    const selected = useEditorStore.getState().selectedClipIds;
    return selected.includes(clipId) ? selected : [clipId];
  };
  // 键盘可达:Tab 进时间线只停一站(roving tabindex)—— 选中的那段;没选中时是界面上第一段。
  const tabbableClipId = React.useMemo(() => {
    const selected = selectedClipIds[selectedClipIds.length - 1];
    if (selected && allClips.some((clip) => clip.id === selected)) return selected;
    for (const track of tracks) {
      const first = [...(track.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start)[0];
      if (first) return first.id;
    }
    return null;
  }, [selectedClipIds, allClips, tracks]);
  // 鼠标按下也会让片段拿到焦点。那次聚焦不是「用键盘走到这段」,不能拿来改选中 —— ⇧ 点击刚把它
  // 从选区里拿掉,紧跟着的聚焦又把它选回来。按下时记一笔,紧随其后的聚焦就认得出来。
  const pointerFocusRef = React.useRef(0);
  // 焦点在某一段上时,选中挪到哪(⌥ + 方向键),焦点跟到哪 —— 屏幕阅读器和下一次 Tab 都从那儿接着走。
  // 时间线只画视口里的片段:要去的那段在视口外时先把它滚进来,等它画出来(视口窗口更新)再聚焦。
  const pendingFocusRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    const root = canvasRef.current;
    if (!root || !tabbableClipId) return;
    const focused = document.activeElement as HTMLElement | null;
    const focusInClips = Boolean(focused && root.contains(focused) && focused.dataset.clipId);
    if (!focusInClips && pendingFocusRef.current !== tabbableClipId) return;
    if (focused?.dataset.clipId === tabbableClipId) {
      pendingFocusRef.current = null;
      return;
    }
    const element = root.querySelector<HTMLElement>(`[data-clip-id="${CSS.escape(tabbableClipId)}"]`);
    if (element) {
      pendingFocusRef.current = null;
      element.focus();
      return;
    }
    const target = allClips.find((clip) => clip.id === tabbableClipId);
    const scroller = hscrollRef.current;
    if (!target || !scroller) return;
    pendingFocusRef.current = tabbableClipId;
    scroller.scrollLeft = Math.max(0, timeToPx(target.timeline_start, pxPerSecond) - scroller.clientWidth / 3);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabbableClipId, viewport]);
  // 复制走后端深拷贝,文字、字幕片段一样能复制。
  const duplicateTarget = allClips.find((clip) => clip.id === selectedClipIds[selectedClipIds.length - 1]);
  // 剪切了还没粘贴的片段:标出来(变淡、虚线框),用户知道粘贴时会搬走的是哪几段。
  const clipboard = useEditorStore((state) => state.clipboard);
  const cutIds = React.useMemo(() => new Set(clipboard?.cut ? clipboard.clipIds : []), [clipboard]);

  // 落位动画(前身项目同款):提交回包落进缓存、而 EditorView 的效应还没清草稿的
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
  // 草稿投影:clipId → 它此刻该画在哪。组拖时锚点与跟随者都在里面,渲染只查这张表,
  // 不再逐处比对 `draft.clipId === clip.id`——那种写法天然只认一个片段,正是"框选后只拖动
  // 鼠标底下那个"的来源。锚点带 src_in/src_out(裁剪也用这张表),跟随者只改位置。
  const draftByClip = React.useMemo(() => {
    const map = new Map<string, { trackId: string; timeline_start: number; src_in: number; src_out: number }>();
    if (!dragDraft) return map;
    map.set(dragDraft.clipId, {
      trackId: dragDraft.trackId,
      timeline_start: dragDraft.timeline_start,
      src_in: dragDraft.src_in,
      src_out: dragDraft.src_out,
    });
    for (const follower of dragDraft.followers ?? []) {
      const source = allClips.find((item) => item.id === follower.clipId);
      if (!source) continue;
      map.set(follower.clipId, {
        trackId: follower.trackId,
        timeline_start: follower.timeline_start,
        src_in: source.src_in,
        src_out: source.src_out,
      });
    }
    return map;
  }, [dragDraft, allClips]);
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
    return src ? clipDuration({ ...src, src_in: dragDraft.src_in, src_out: dragDraft.src_out }) : 0;
  }, [dragDraft, allClips]);

  // Insert-mode ripple preview: downstream clips on the target track part only by
  // the actual overlap (mirrors the backend), so a nudge doesn't shove everything.
  // 落点插进某个片段身体里时,后端会把它切开(头段留在原地、尾段并入右移)——预览
  // 必须同步演出来,否则拖动时看着是覆盖、松手才弹开。split 口径与后端 coverage.make_room
  // 一致:切点贴边 0.05s 内不切,只按重叠量右移(贴着尾巴时后端把那一点尾巴裁掉)。
  const insertRipple = React.useMemo(() => {
    if (editMode !== "insert" || !dragDraft || dragDraft.kind !== "move") return null;
    const start = dragDraft.timeline_start;
    const end = start + dragMoveDuration;
    const others = (tracks.find((t) => t.id === dragDraft.trackId)?.clips ?? []).filter(
      (c) => c.id !== dragDraft.clipId,
    );
    const MIN_CUT_REMAINDER = 0.05; // 与后端同值(src 秒)
    let split: { clipId: string; cutSrc: number; tailDuration: number } | null = null;
    const straddler = others.find((c) => c.timeline_start < start - 1e-9 && clipEnd(c) > start + 1e-9);
    if (straddler) {
      const cutSrc = timelineToSrc(straddler, start);
      if (straddler.src_in + MIN_CUT_REMAINDER < cutSrc && cutSrc < straddler.src_out - MIN_CUT_REMAINDER) {
        split = { clipId: straddler.id, cutSrc, tailDuration: clipEnd(straddler) - start };
      }
    }
    // 切出的尾段落在落点上,和既有下游片段一起按同一重叠量右移(间距保留)。
    const downstreamStarts = others.filter((c) => c.timeline_start >= start - 1e-9).map((c) => c.timeline_start);
    if (split) downstreamStarts.push(start);
    if (!downstreamStarts.length) return null;
    const shift = end - Math.min(...downstreamStarts);
    return shift > 1e-9 ? { trackId: dragDraft.trackId, from: start, shift, split } : null;
  }, [editMode, dragDraft, dragMoveDuration, tracks]);
  // 覆盖模式的落点预览:被拖着的片段盖住的部分,松手后后端会挖掉(coverage.carve)—— 预览里提前挖。
  // clipId → 还露在外面的几截(时间线区间);整段被盖住就是空数组。没受影响的片段不在表里。
  const overwriteCarve = React.useMemo(() => {
    const carved = new Map<string, Array<{ start: number; end: number }>>();
    if (editMode !== "overwrite" || !dragDraft || dragDraft.kind !== "move") return carved;
    const spansByTrack = new Map<string, Array<{ start: number; end: number }>>();
    for (const [clipId, at] of draftByClip) {
      const source = allClips.find((item) => item.id === clipId);
      if (!source) continue;
      const end = at.timeline_start + clipDuration({ ...source, src_in: at.src_in, src_out: at.src_out });
      spansByTrack.set(at.trackId, [...(spansByTrack.get(at.trackId) ?? []), { start: at.timeline_start, end }]);
    }
    for (const track of tracks) {
      const spans = spansByTrack.get(track.id);
      if (!spans) continue;
      for (const other of track.clips ?? []) {
        if (draftByClip.has(other.id)) continue;
        const pieces = uncoveredPieces(other, spans);
        const untouched = pieces.length === 1 && pieces[0].start === other.timeline_start && pieces[0].end === clipEnd(other);
        if (!untouched) carved.set(other.id, pieces);
      }
    }
    return carved;
  }, [editMode, dragDraft, draftByClip, allClips, tracks]);
  const assetById = React.useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);

  //: 有声音的片段画波形 —— 视频也带声音(和 PR / DaVinci 一样),图片没有,放在视频轨上也不画。
  //: 按片段的素材类型收,不按轨道;下面画的时候只按素材查这张表。
  const waveformAssetIds = React.useMemo(() => {
    const ids = new Set<string>();
    for (const clip of allClips) {
      if (clip.asset_id && kindHasSound(clip.asset_kind) && assetById.get(clip.asset_id)?.media_info.has_waveform) {
        ids.add(clip.asset_id);
      }
    }
    return [...ids];
  }, [allClips, assetById]);
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

  // 缩放要有锚:放大缩小后,锚点(播放头,或滚轮缩放时的指针)停在屏幕上原来的位置。此前只改
  // 比例尺、不动滚动位置 —— 放大一下,正看着的那一段就被推出视口,得自己去找。
  // 新的滚动位置要等这次缩放渲染出更宽的画布之后才能写进去,先存着,由下面的 layout effect 落地。
  const pendingScrollRef = React.useRef<number | null>(null);
  React.useLayoutEffect(() => {
    const el = hscrollRef.current;
    if (el && pendingScrollRef.current !== null) el.scrollLeft = Math.max(0, pendingScrollRef.current);
    pendingScrollRef.current = null;
  }, [pxPerSecond]);
  /** 锚在播放头上:播放头在视口里就停在原处,不在视口里就把它放到视口正中。 */
  const playheadAnchor = (): { time: number; screenX: number } => {
    const el = hscrollRef.current;
    const time = useEditorStore.getState().playhead;
    const width = el?.clientWidth ?? 0;
    const screenX = timeToPx(time, pxPerSecond) - (el?.scrollLeft ?? 0);
    return { time, screenX: screenX >= 0 && screenX <= width ? screenX : width / 2 };
  };
  // 视口换算成时间窗:片段与刻度只画落在 [windowStart, windowEnd] 里的。
  const viewportWidth = viewport.width || FALLBACK_VIEWPORT_PX;
  const bufferPx = Math.max(VIRTUAL_MIN_BUFFER_PX, viewportWidth);
  const windowStart = Math.max(0, pxToTime(viewport.left - bufferPx, pxPerSecond));
  const windowEnd = pxToTime(viewport.left + viewportWidth + bufferPx, pxPerSecond);
  const ticks = rulerTicks(windowStart, Math.min(duration, windowEnd), pxPerSecond);
  const inWindow = (start: number, end: number) => end >= windowStart && start <= windowEnd;
  const zoomAround = (nextPxPerSecond: number, anchor: { time: number; screenX: number }) => {
    // Zoom out can't go below "the whole timeline fits the viewport" — past that is dead space.
    const viewportPx = hscrollRef.current?.clientWidth ?? 0;
    const floor = viewportPx > 0 ? Math.max(MIN_PX_PER_SECOND, (viewportPx - 130) / Math.max(duration, 1)) : MIN_PX_PER_SECOND;
    const next = Math.min(MAX_PX_PER_SECOND, Math.max(floor, nextPxPerSecond));
    pendingScrollRef.current = timeToPx(anchor.time, next) - anchor.screenX;
    setPxPerSecond(next);
  };
  const applyZoom = (factor: number) => zoomAround(pxPerSecond * factor, playheadAnchor());
  /** 适配窗口:整条时间线正好铺满视口,回到开头。 */
  const zoomToFit = () => {
    const viewportPx = hscrollRef.current?.clientWidth ?? 0;
    if (viewportPx <= 0) return;
    const fit = (viewportPx - 40) / Math.max(sequenceDuration(allClips), 1);
    pendingScrollRef.current = 0;
    setPxPerSecond(Math.min(MAX_PX_PER_SECOND, Math.max(MIN_PX_PER_SECOND, fit)));
  };
  // 缩放快捷键:+ / -(以播放头为锚)、⇧Z 适配窗口。只接冲着剪辑页来的按键(isEditorKeyTarget)。
  // 处理函数每次渲染都换新(它们读当前比例尺),经 ref 调,监听只挂一次。
  const zoomKeysRef = React.useRef({ applyZoom, zoomToFit });
  zoomKeysRef.current = { applyZoom, zoomToFit };
  const rootRef = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(
    () =>
      listenKeys(window, (event) => {
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        const root = rootRef.current?.closest("[data-editor-root]") ?? rootRef.current;
        if (!isEditorKeyTarget(event, root)) return;
        if (event.key === "=" || event.key === "+") zoomKeysRef.current.applyZoom(1.3);
        else if (event.key === "-" || event.key === "_") zoomKeysRef.current.applyZoom(1 / 1.3);
        else if (event.shiftKey && event.code === "KeyZ") zoomKeysRef.current.zoomToFit();
        else return;
        event.preventDefault();
      }),
    [],
  );
  const tickStep = rulerStep(pxPerSecond);

  // 指针能放下的每一个时刻(标尺、修剪、刀片、素材落点)都吸到序列的帧上:落在两帧之间的点
  // 导出时会被吞成某一帧,预览里看到的却是另一处。
  const fps = sequence.fps;
  const timeAtPointer = (event: { clientX: number }): number => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    return snapToFrame(Math.max(0, pxToTime(event.clientX - rect.left, pxPerSecond)), fps);
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
        onSplitClipAt(clip.id, timelineToSrc(clip, timeAtPointer(event)));
      }
      return;
    }
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      useEditorStore.getState().toggleSelectClip(clip.id);
      return;
    }
    if (!useEditorStore.getState().selectedClipIds.includes(clip.id)) selectClip(clip.id);
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...clip };
    // 组拖:按住的那个是锚点,其余选中片段按**同一个时间增量**跟随(框选后拖动应当整组一起走,
    // 而不是只拖鼠标底下那一个)。这里在起手时把跟随者连同它们的轨道索引一并快照——拖拽过程中
    // 轨道数组会因跨轨预览而变化,现算会漂。
    const laneIndexOf = (trackId: string) => tracks.findIndex((t) => t.id === trackId);
    const anchorLane = laneIndexOf(track.id);
    const followerOrigins = useEditorStore
      .getState()
      .selectedClipIds.filter((id) => id !== clip.id)
      .map((id) => {
        const owner = tracks.find((t) => (t.clips ?? []).some((c) => c.id === id));
        const found = owner?.clips?.find((c) => c.id === id);
        return owner && found ? { clip: found, trackId: owner.id, lane: laneIndexOf(owner.id) } : null;
      })
      .filter((entry): entry is { clip: Clip; trackId: string; lane: number } => entry !== null);
    // 两级吸附候选在起手时算好:每条轨一份边缘表(拖到哪条 lane,哪条就是第一
    // 优先级),播放头/零点与其余轨道的边缘降为次级 — 否则字幕轨的密集 cue 边界
    // 或播放头会比同轨邻居更近,把肉眼可见的对接"抢走"。
    // 链接组员(画和它分离出去的声音)跟着一起挪、轨道不变 —— 后端移动时整组走同样的时间差,预览照着画。
    const movingIds = new Set([clip.id, ...followerOrigins.map((entry) => entry.clip.id)]);
    const groups = new Set(
      [clip, ...followerOrigins.map((entry) => entry.clip)].map((item) => item.link_group).filter((group): group is string => Boolean(group)),
    );
    const linkedOrigins =
      groups.size === 0
        ? []
        : tracks
            .filter((t) => !t.locked)
            .flatMap((t) =>
              (t.clips ?? [])
                .filter((c) => c.link_group && groups.has(c.link_group) && !movingIds.has(c.id))
                .map((c) => ({ clip: c, trackId: t.id })),
            );
    for (const entry of linkedOrigins) movingIds.add(entry.clip.id);
    const dragPlayhead = useEditorStore.getState().playhead;
    // 跟着动的片段(自己、组拖的其余几段、链接组员)不当吸附目标:往自己原来的位置上吸没有意义。
    const edgesByTrack = new Map(
      snapEnabled
        ? tracks.map((t) => [t.id, trackEdgeTimes((t.clips ?? []).filter((c) => !movingIds.has(c.id)), null)] as const)
        : [],
    );
    // 按住 ⌘ / Ctrl 拖:这一下临时不吸附(想贴着某条边但又不想被吸过去的时候)。
    const snapSetsFor = (laneId: string | null, suspended: boolean): { primary: number[]; secondary: number[] } => {
      if (!snapEnabled || suspended) return { primary: [], secondary: [] };
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
      // 按住 ⇧ 锁轴:位移以横向为主就只改时间(不换轨),以纵向为主就只换轨(时间不动)。
      const dx = moveEvent.clientX - startX;
      const dy = moveEvent.clientY - startY;
      const lockToTime = moveEvent.shiftKey && Math.abs(dx) >= Math.abs(dy);
      const lockToLane = moveEvent.shiftKey && !lockToTime;
      // Dragged above the topmost lane → intent to spin up a new video layer.
      wantNewLayer = Boolean(
        !lockToTime && rect && onMoveClipToNewLayer && track.kind === "video" && moveEvent.clientY - rect.top - RULER_HEIGHT < 0,
      );
      setNewLayerDrag(wantNewLayer);
      const lane = wantNewLayer || lockToTime ? null : laneTrackAt(moveEvent.clientY, track.kind);
      const rawStart = lockToLane
        ? origin.timeline_start
        : snapToFrame(origin.timeline_start + pxToTime(dx, pxPerSecond), fps);
      const sets = snapSetsFor(lane?.id ?? (wantNewLayer ? null : track.id), lockToLane || moveEvent.metaKey || moveEvent.ctrlKey);
      const resolved = resolveMove(origin, rawStart, sets.primary, sets.secondary, pxPerSecond);
      const anchorTrackId = lane?.id ?? track.id;
      // 跟随者用锚点**吸附之后**的增量,整组保持相对位置——各自再吸附一次会让组内间距被拉变形。
      const deltaTime = resolved - origin.timeline_start;
      // 轨道位移同理取自锚点。只有当**每个**跟随者都能落到合法轨(存在、同类、未锁)时才整体换轨;
      // 但凡有一个落不下,整组就只平移时间——部分换轨会把选中集拆散到不同轨上,比不换更难理解。
      const laneDelta = wantNewLayer ? 0 : laneIndexOf(anchorTrackId) - anchorLane;
      const followerTracks = followerOrigins.map((entry) => {
        const target = tracks[entry.lane + laneDelta];
        const ownerTrack = tracks[entry.lane];
        return target && ownerTrack && target.kind === ownerTrack.kind && !target.locked ? target.id : null;
      });
      const groupCanChangeLane = laneDelta !== 0 && followerTracks.every((id) => id !== null);
      useEditorStore.getState().setDragDraft({
        clipId: clip.id,
        trackId: anchorTrackId,
        timeline_start: resolved,
        src_in: origin.src_in,
        src_out: origin.src_out,
        kind: "move",
        followers: followerOrigins.map((entry, index) => ({
          clipId: entry.clip.id,
          trackId: groupCanChangeLane ? (followerTracks[index] as string) : entry.trackId,
          // 时间不能为负:整组左移撞到 0 时,锚点已被 resolveMove 夹住,跟随者也要各自夹一次。
          timeline_start: Math.max(0, entry.clip.timeline_start + deltaTime),
        })).concat(
          linkedOrigins.map((entry) => ({
            clipId: entry.clip.id,
            trackId: entry.trackId,
            timeline_start: Math.max(0, entry.clip.timeline_start + deltaTime),
            linked: true,
          })),
        ),
      });
    };
    const detach = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", cancel);
      stopKeys();
      setNewLayerDrag(false);
    };
    // Esc / 指针被系统收回(pointercancel):整次拖动作废,片段回到原处,什么都不提交。
    const cancel = () => {
      detach();
      useEditorStore.getState().setDragDraft(null);
    };
    const stopKeys = listenEscape(cancel);
    const onUp = (upEvent: PointerEvent) => {
      detach();
      const draft = useEditorStore.getState().dragDraft;
      // 按住 ⌥ 松手:复制到落点,原片段留在原处(和 PR / 达芬奇一样)。草稿直接撤掉 —— 原片段没动,
      // 副本等回包落进缓存后出现。
      if (upEvent.altKey && onDuplicateClipsAt && draft && draft.clipId === clip.id && !wantNewLayer) {
        useEditorStore.getState().setDragDraft(null);
        const starts = [draft.timeline_start, ...(draft.followers ?? []).map((f) => f.timeline_start)];
        const singleOnOtherTrack = !draft.followers?.length && draft.trackId !== track.id ? draft.trackId : null;
        onDuplicateClipsAt(
          [clip.id, ...(draft.followers ?? []).map((f) => f.clipId)],
          Math.min(...starts),
          singleOnOtherTrack,
        );
        return;
      }
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
        useEditorStore.getState().setDragDraft({ ...draft, settling: true });
        // 链接组员只为预览:后端移动这几段时整组跟着走,不用(也不该)再交一遍。
        const groupFollowers = (draft.followers ?? []).filter((f) => !f.linked);
        if (groupFollowers.length && onMoveClips) {
          // 组拖走批量接口:一次手势落成一条操作,撤销一步还原整组。逐个调 onMoveClip 会产生
          // N 条操作,用户得按 N 次 ⌘Z——与"一次拖动"的心智完全对不上。
          // 组拖不支持插入模式的涟漪:一组(可能还跨轨)的片段要"挤开"什么没有唯一解,一律按覆盖。
          onMoveClips([
            { clipId: clip.id, timelineStart: draft.timeline_start, trackId: draft.trackId },
            ...groupFollowers.map((f) => ({ clipId: f.clipId, timelineStart: f.timeline_start, trackId: f.trackId })),
          ]);
        } else {
          // Insert mode ripples the destination track's downstream clips aside.
          const ripple = useEditorStore.getState().editMode === "insert";
          onMoveClip(clip.id, draft.timeline_start, draft.trackId !== track.id ? draft.trackId : undefined, ripple);
        }
      } else {
        useEditorStore.getState().setDragDraft(null);
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", cancel);
  };

  const startClipTrim = (event: React.PointerEvent, track: Track, clipId: string, edge: "start" | "end") => {
    const clip = (track.clips ?? []).find((item) => item.id === clipId);
    if (!clip || track.locked) return;
    event.stopPropagation();
    selectClip(clip.id);
    const origin = { ...clip };
    const asset = clip.asset_id ? assetById.get(clip.asset_id) : undefined;
    // 图片是静态帧,没有固有时长——可自由拉伸到任意长度(渲染时按该时长定格显示);
    // 视频/音频有真实源帧,裁剪受源时长上限约束。null = 上限无限。
    const assetDuration =
      asset?.kind === "image" ? null : typeof asset?.media_info.duration === "number" ? asset.media_info.duration : null;
    // 裁剪吸附与移动同级:本轨邻居边缘优先,播放头/零点/其他轨道次级。
    const trimPrimary = snapEnabled ? trackEdgeTimes(track.clips ?? [], clip.id) : [];
    const trimSecondary = snapEnabled
      ? [0, useEditorStore.getState().playhead, ...tracks.filter((t) => t.id !== track.id).flatMap((t) => trackEdgeTimes(t.clips ?? [], clip.id))]
      : [];
    // 同轨不重叠:头边停在左邻居的尾巴上、尾边停在右邻居的头上(后端修剪同样夹到邻居)。
    const limits = trimLimits(track.clips ?? [], clip);
    const target = event.currentTarget as HTMLElement;
    capturePointer(target, event.pointerId);

    const onMove = (moveEvent: PointerEvent) => {
      let rawTime = timeAtPointer(moveEvent);
      // 按住 ⌘ / Ctrl:这一下临时不吸附。
      if (snapEnabled && !(moveEvent.metaKey || moveEvent.ctrlKey)) {
        rawTime = snapTimeTiered(rawTime, trimPrimary, trimSecondary, pxPerSecond).time;
      }
      const result = resolveTrim(origin, edge, rawTime, assetDuration, undefined, limits);
      useEditorStore.getState().setDragDraft({
        clipId: clip.id,
        trackId: track.id,
        ...result,
        kind: edge === "start" ? "trim-start" : "trim-end",
      });
    };
    const detach = () => {
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
      target.removeEventListener("pointercancel", cancel);
      target.removeEventListener("lostpointercapture", cancel);
      stopKeys();
    };
    // 修剪被打断 —— Esc、系统收回指针(pointercancel,如触控板手势、弹出的系统对话框)、指针捕获
    // 在松手之前丢了 —— 一律作废:不提交,草稿撤掉。此前这几种情况下草稿留在原地、监听也没摘,
    // 片段停在半截修剪的样子,下一次指针移动还会接着改它。
    const cancel = () => {
      detach();
      useEditorStore.getState().setDragDraft(null);
    };
    const stopKeys = listenEscape(cancel);
    const onUp = () => {
      detach();
      const draft = useEditorStore.getState().dragDraft;
      if (draft && draft.clipId === clip.id) {
        // 与移动同理:settling 草稿钉住裁剪结果等回包,缓存追平后由过渡完成落位。
        useEditorStore.getState().setDragDraft({ ...draft, settling: true });
        onTrimClip(clip.id, { timeline_start: draft.timeline_start, src_in: draft.src_in, src_out: draft.src_out });
      }
    };
    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
    target.addEventListener("pointercancel", cancel);
    target.addEventListener("lostpointercapture", cancel);
  };

  // 给 memo 过的片段的手柄:身份恒定,按 (trackId, clipId) 找回此刻的轨道再分派。
  const handleClipPointerDown = useStableHandler((event: React.PointerEvent, trackId: string, clipId: string) => {
    pointerFocusRef.current = performance.now();
    const track = tracks.find((item) => item.id === trackId);
    if (track) startClipDrag(event, track, clipId);
  });
  const handleClipTrimPointerDown = useStableHandler(
    (event: React.PointerEvent, trackId: string, clipId: string, edge: "start" | "end") => {
      pointerFocusRef.current = performance.now();
      const track = tracks.find((item) => item.id === trackId);
      if (track) startClipTrim(event, track, clipId, edge);
    },
  );
  const handleClipSelect = React.useCallback((clipId: string) => {
    if (!useEditorStore.getState().selectedClipIds.includes(clipId)) useEditorStore.getState().selectClip(clipId);
  }, []);
  // 键盘 Tab 到片段上 = 选中它;紧跟在鼠标按下之后的那次聚焦不算(见 pointerFocusRef)。
  const handleClipFocus = React.useCallback(
    (clipId: string) => {
      if (performance.now() - pointerFocusRef.current < 500) return;
      handleClipSelect(clipId);
    },
    [handleClipSelect],
  );

  // 右键菜单是**一个**单例:右键时按事件目标认出是哪一段,再按那一段生成菜单项。此前每段各包一棵
  // Radix ContextMenu,几千段就是几千棵,拖动时每棵都跟着协调。点在空白处(不是片段)不开菜单。
  const [menuClipId, setMenuClipId] = React.useState<string | null>(null);
  const handleCanvasContextMenu = (event: React.MouseEvent) => {
    const clipId = (event.target as HTMLElement).closest<HTMLElement>("[data-clip-id]")?.dataset.clipId;
    if (!clipId || !onDeleteClips) {
      // 先于 Radix 的处理器拦下:它看到 defaultPrevented 就不开菜单。
      event.preventDefault();
      return;
    }
    handleClipSelect(clipId);
    setMenuClipId(clipId);
  };
  const menuClip = menuClipId ? allClips.find((item) => item.id === menuClipId) : undefined;
  const menuTrack = menuClip ? tracks.find((track) => (track.clips ?? []).some((c) => c.id === menuClip.id)) : undefined;

  // 素材拖入落点的指针 X:直接取实时指针的视口 clientX(与标尺/框选/移动片段同一套),
  // 而不是 dnd-kit 的 activatorEvent.clientX + event.delta.x。delta 里已含 dnd-kit 对滚动容器
  // 的滚动补偿,再和 timeAtPointer 里「随滚动实时变化的 canvasRef 矩形」相减,会把横向滚动量
  // 算两遍——时间线在拖拽中/拖拽前滚动过,落点就偏(「有时候位置不对」)。实时 clientX 配实时
  // 矩形,滚动只计一次,落点稳。dragStart 先用 activator 兜底,之后由 window pointermove 刷新。
  const dragPointerXRef = React.useRef<number | null>(null);
  React.useEffect(() => {
    if (!draggingAsset) {
      dragPointerXRef.current = null;
      return;
    }
    const onMove = (event: PointerEvent) => {
      dragPointerXRef.current = event.clientX;
    };
    window.addEventListener("pointermove", onMove, { capture: true });
    return () => window.removeEventListener("pointermove", onMove, { capture: true });
  }, [draggingAsset]);
  // 素材落轨的吸附:目标轨边缘优先,播放头/零点/其他轨道次级(与片段移动同级)。
  const snapDropStart = (start: number, target: Track): number =>
    snapTimeTiered(
      start,
      trackEdgeTimes(target.clips ?? [], null),
      [0, useEditorStore.getState().playhead, ...tracks.filter((t) => t.id !== target.id).flatMap((t) => trackEdgeTimes(t.clips ?? [], null))],
      pxPerSecond,
    ).time;
  useDndMonitor({
    onDragStart(event) {
      dragPointerXRef.current = (event.activatorEvent as PointerEvent).clientX ?? null;
    },
    onDragMove(event) {
      const asset = event.active.data.current?.asset as Asset | undefined;
      if (!asset) return;
      const track = event.over?.data.current?.track as Track | undefined;
      if (!track || track.locked || !trackAcceptsAsset(track, asset)) {
        setDropGhost(null);
        return;
      }
      const assetDuration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : 5;
      let start = timeAtPointer({ clientX: dragPointerXRef.current ?? 0 });
      if (snapEnabled) start = snapDropStart(start, track);
      setDropGhost({ trackId: track.id, start, duration: assetDuration });
    },
    onDragEnd(event) {
      setDropGhost(null);
      const asset = event.active.data.current?.asset as Asset | undefined;
      const track = event.over?.data.current?.track as Track | undefined;
      if (!asset || !track || !trackAcceptsAsset(track, asset) || track.locked) return;
      const assetDuration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : 5;
      let start = timeAtPointer({ clientX: dragPointerXRef.current ?? 0 });
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
      // 滚轮缩放以指针为锚:指针下的那一刻留在指针下。
      const el = hscrollRef.current;
      const screenX = event.clientX - (el?.getBoundingClientRect().left ?? 0);
      const time = pxToTime((el?.scrollLeft ?? 0) + screenX, pxPerSecond);
      zoomAround(pxPerSecond * (event.deltaY < 0 ? 1.15 : 1 / 1.15), { time, screenX });
    }
  };

  return (
    <div ref={rootRef} className="grid h-full grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto]" data-tool={tool} onWheel={handleWheel}>
      <div className="editor-timeline-toolbar flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-divider bg-workspace-panel px-3 py-1.5">
        <div className="flex min-w-0 flex-nowrap items-center gap-2">
          <div className="inline-flex h-8 items-stretch gap-0.5 whitespace-nowrap" role="group" aria-label={t("editTools")}>
            <button
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-2 py-1 text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", tool === "select" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              title={t("toolSelectHint")}
              aria-pressed={tool === "select"}
              onClick={() => useEditorStore.getState().setTool("select")}
            >
              <MousePointer2 size={12} /> {t("toolSelect")}
            </button>
            <button
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-2 py-1 text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", tool === "blade" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              title={t("toolBladeHint")}
              aria-pressed={tool === "blade"}
              onClick={() => useEditorStore.getState().setTool("blade")}
            >
              <Slice size={12} /> {t("toolBlade")}
            </button>
          </div>
          <div className="inline-flex h-8 items-stretch gap-0.5 whitespace-nowrap" role="group" aria-label={t("editMode")}>
            <button
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-2 py-1 text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", editMode === "overwrite" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              title={t("editModeOverwriteHint")}
              aria-pressed={editMode === "overwrite"}
              onClick={() => useEditorStore.getState().setEditMode("overwrite")}
            >
              <Replace size={12} /> {t("editModeOverwrite")}
            </button>
            <button
              type="button"
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-2 py-1 text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", editMode === "insert" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              title={t("editModeInsertHint")}
              aria-pressed={editMode === "insert"}
              onClick={() => useEditorStore.getState().setEditMode("insert")}
            >
              <BetweenHorizontalStart size={12} /> {t("editModeInsert")}
            </button>
          </div>
        </div>
        <div className="flex items-center gap-0.5">
          {toolbarExtra}
          {(onSplitClip || onDuplicateClip || onDeleteClips) && <span className="mx-[3px] h-4 w-px bg-divider" />}
          {onSplitClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  // **没选中东西时也能用**:切的是播放头下的那一段。这一条原本只在监视器上方
                  // 那排里有(「在此切一刀」),而这里的剪刀灰着 —— 同一个动作两个入口、两种
                  // 可用条件,用户只会觉得剪刀坏了。
                  onClick={() => onSplitClip(selectedClipIds[selectedClipIds.length - 1])}
                  aria-label={t("splitAtPlayhead")}
                >
                  <Scissors size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("splitAtPlayhead")}</TooltipContent>
            </Tooltip>
          )}
          {onGrabFrame && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" loading={grabbingFrame} onClick={onGrabFrame} aria-label={t("editorGrabFrame")}>
                  <Camera size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("editorGrabFrameTitle")}</TooltipContent>
            </Tooltip>
          )}
          {onDuplicateClip && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={!duplicateTarget}
                  onClick={() => duplicateTarget && onDuplicateClip(duplicateTarget.id)}
                  aria-label={t("duplicateClip")}
                >
                  <Copy size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("duplicateClip")}</TooltipContent>
            </Tooltip>
          )}
          {onRippleDeleteClips && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={!selectedClipIds.length}
                  onClick={() => onRippleDeleteClips(selectedClipIds)}
                  aria-label={t("rippleDelete")}
                >
                  <Waves size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("rippleDelete")}</TooltipContent>
            </Tooltip>
          )}
          {onDeleteClips && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={!selectedClipIds.length}
                  onClick={() => onDeleteClips(selectedClipIds)}
                  aria-label={t("deleteClip")}
                >
                  <Trash2 size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("deleteClip")}</TooltipContent>
            </Tooltip>
          )}
          <span className="mx-[3px] h-4 w-px bg-divider" />
          {onAddTrack && (
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="ghost" size="sm"><Plus size={14} />{t("editorAddTrack")}<ChevronDown size={12} /></Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="grid w-44 gap-1 p-1.5">
                {(["video", "audio", "subtitle"] as const).map((kind) => (
                  <PopoverClose asChild key={kind}>
                    <Button variant="ghost" size="sm" className="justify-start" title={t(kind === "video" ? "addVideoTrackHint" : kind === "audio" ? "addAudioTrackHint" : "addSubtitleTrackHint")} onClick={() => onAddTrack(kind)}>
                      {kind === "video" ? <Film /> : kind === "audio" ? <AudioLines /> : <Type />}
                      {t(kind === "video" ? "trackVideoShort" : kind === "audio" ? "trackAudioShort" : "trackSubtitleShort")}
                    </Button>
                  </PopoverClose>
                ))}
              </PopoverContent>
            </Popover>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className={cn(snapEnabled && "bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
                onClick={() => useEditorStore.getState().toggleSnap()}
                aria-pressed={snapEnabled}
                aria-label={t("timelineSnap")}
              >
                <Magnet size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent className="flex items-center gap-2">{t("timelineSnap")}<Kbd>N</Kbd></TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={() => applyZoom(1 / 1.3)} aria-label={t("zoomOut")}>
                <Minus size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent className="flex items-center gap-2">{t("zoomOut")}<Kbd>-</Kbd></TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={() => applyZoom(1.3)} aria-label={t("zoomIn")}>
                <Plus size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent className="flex items-center gap-2">{t("zoomIn")}<Kbd>+</Kbd></TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={zoomToFit} aria-label={t("zoomToFit")}>
                <Maximize2 size={14} />
              </Button>
            </TooltipTrigger>
            <TooltipContent className="flex items-center gap-2">{t("zoomToFit")}<Kbd>⇧Z</Kbd></TooltipContent>
          </Tooltip>
          <Popover open={helpOpen} onOpenChange={setHelpOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className={cn(helpOpen && "bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
                aria-label={t("shortcutsHelp")}
              >
                <CircleHelp size={14} />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="grid max-h-[70vh] w-[340px] gap-1.5 overflow-y-auto px-3 py-2.5 [&_strong]:mb-0.5 [&_strong]:text-xs" aria-label={t("shortcutsHelp")}>
              <strong>{t("shortcutsHelp")}</strong>
              {(
                [
                  [["Space"], t("hintPlayPause")],
                  [["J", "K", "L"], t("hintShuttle")],
                  [["←", "→"], t("hintFrameStep")],
                  [["↑", "↓"], t("hintEditPoints")],
                  [["Home", "End"], t("hintHomeEnd")],
                  [["I", "O"], t("hintMarks")],
                  [["A", "B"], t("hintTools")],
                  [["S"], t("hintSplit")],
                  [["⇧⌘K"], t("hintSplitAll")],
                  [["Q", "W"], t("hintRippleTrim")],
                  [["⌘D"], t("hintDuplicate")],
                  [["⌘C", "⌘X", "⌘V"], t("hintClipboard")],
                  [["Delete"], t("hintDelete")],
                  [["⇧Delete"], t("hintRipple")],
                  [["⌘Z", "⇧⌘Z"], t("hintUndoRedo")],
                  [["⌘A"], t("hintSelectAll")],
                  [["⌥←→↑↓"], t("hintSelectMove")],
                  [[",", "."], t("hintNudge")],
                  [["N"], t("hintSnapToggle")],
                  [["+", "-", "⇧Z"], t("hintZoom")],
                  [["Esc"], t("hintEscape")],
                  [[t("hintShiftClickKey")], t("hintMultiSelect")],
                  [[t("hintDragLabel")], t("hintDragBody")],
                  [[t("hintModifiersLabel")], t("hintDragModifiers")],
                  [["↕"], t("hintVerticalDrag")],
                ] as const
              ).map(([keys, body]) => (
                <div className="grid grid-cols-[92px_minmax(0,1fr)] items-start gap-1.5 text-xs" key={keys.join("/")}>
                  <KbdGroup className="justify-self-start" keys={keys} />
                  <span className="leading-[17px] text-muted-foreground">{body}</span>
                </div>
              ))}
            </PopoverContent>
          </Popover>
        </div>
      </div>
      <div className="grid min-h-0 grid-cols-[112px_minmax(0,1fr)] overflow-hidden">
        <div className="overflow-hidden border-r border-border bg-workspace-panel" ref={labelsRef}>
          <div className="workspace-sticky sticky top-0 z-[6] border-b border-border bg-panel" style={{ height: RULER_HEIGHT }} />
          {tracks.map((track, trackIndex) => (
            <div className="group/label flex flex-col justify-center gap-1 border-b border-[var(--track-lane-line)] px-2 text-ui-xs font-semibold text-muted-foreground" key={track.id} style={{ height: TRACK_HEIGHT }}>
              <div className="flex min-w-0 items-center gap-1.5">
                <span className={cn("h-[7px] w-[7px] rounded-sm bg-[var(--track-video-border)]", track.kind === "audio" && "bg-[var(--track-audio-border)]", track.kind === "subtitle" && "bg-[var(--track-subtitle-border)]")} />
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
                  {/* 静音 / 独奏 / 闪避只管声音。字幕轨没有声音(在它上面按独奏,「有轨在独奏」成立
                      而它自己不出声,结果是整片静音),它头上只有「隐藏」:预览和成片里都不画这条字幕。 */}
                  {track.kind === "subtitle" ? (
                    <TrackToggle
                      active={Boolean(track.hidden)}
                      activeClassName="text-destructive enabled:hover:text-destructive"
                      label={track.hidden ? t("trackShow") : t("trackHide")}
                      onToggle={() => onSetTrackState(track.id, { hidden: !track.hidden })}
                    >
                      {track.hidden ? <EyeOff size={11} /> : <Eye size={11} />}
                    </TrackToggle>
                  ) : (
                    <>
                      <TrackToggle
                        active={Boolean(track.muted)}
                        activeClassName="text-destructive enabled:hover:text-destructive"
                        label={track.muted ? t("trackUnmute") : t("trackMute")}
                        onToggle={() => onSetTrackState(track.id, { muted: !track.muted })}
                      >
                        {track.muted ? <VolumeX size={11} /> : <Volume2 size={11} />}
                      </TrackToggle>
                      <TrackToggle
                        active={Boolean(track.solo)}
                        activeClassName="bg-warning/15 text-warning enabled:hover:text-warning"
                        label={track.solo ? t("trackUnsolo") : t("trackSolo")}
                        hint={t("trackSoloHint")}
                        onToggle={() => onSetTrackState(track.id, { solo: !track.solo })}
                      >
                        <span className="text-[9px] font-bold leading-none">S</span>
                      </TrackToggle>
                      <TrackToggle
                        active={Boolean(track.duck)}
                        activeClassName="bg-primary/15 text-primary enabled:hover:text-primary"
                        label={track.duck ? t("trackUnduck") : t("trackDuck")}
                        hint={t("trackDuckHint")}
                        onToggle={() => onSetTrackState(track.id, { duck: !track.duck })}
                      >
                        <span className="text-[9px] font-bold leading-none">D</span>
                      </TrackToggle>
                    </>
                  )}
                  <TrackToggle
                    active={Boolean(track.locked)}
                    activeClassName="text-destructive enabled:hover:text-destructive"
                    label={track.locked ? t("trackUnlock") : t("trackLock")}
                    onToggle={() => onSetTrackState(track.id, { locked: !track.locked })}
                  >
                    {track.locked ? <Lock size={11} /> : <LockOpen size={11} />}
                  </TrackToggle>
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
          data-testid="timeline-scroll"
          onScroll={(event) => {
            // Mirror vertical scroll to the labels column so track rows stay aligned.
            if (labelsRef.current) labelsRef.current.scrollTop = event.currentTarget.scrollTop;
          }}
        >
          <ContextMenu>
          <ContextMenuTrigger asChild>
          <div className="relative min-w-full" ref={canvasRef} style={{ width: contentWidth }} onContextMenu={handleCanvasContextMenu}>
            <div
              className="workspace-sticky sticky top-0 z-[5] cursor-ew-resize touch-none overflow-hidden border-b border-border bg-[var(--ruler-bg)]"
              data-testid="timeline-ruler"
              style={{ height: RULER_HEIGHT }}
              onPointerDown={handleRulerPointerDown}
              onPointerMove={handleRulerPointerMove}
            >
              {ticks.map((tick) => (
                <div
                  key={tick.time}
                  className={cn("absolute bottom-0 h-[5px] w-px bg-[var(--ruler-tick)]", tick.major && "h-[9px] [&_span]:absolute [&_span]:bottom-2 [&_span]:left-1 [&_span]:whitespace-nowrap [&_span]:text-ui-2xs [&_span]:text-[var(--ruler-text)]")}
                  style={{ left: timeToPx(tick.time, pxPerSecond) }}
                >
                  {tick.major && <span className="timecode">{formatRulerLabel(tick.time, tickStep)}</span>}
                </div>
              ))}
              <MarkedRangeBand pxPerSecond={pxPerSecond} duration={sequenceDuration(allClips)} />
            </div>
            {newLayerDrag && (
              <div className="pointer-events-none absolute inset-x-0 z-[4] flex h-[22px] items-center justify-center gap-[5px] border-y-[1.5px] border-dashed border-primary bg-[color-mix(in_srgb,var(--primary)_16%,transparent)] text-ui-xs font-semibold text-primary" style={{ top: RULER_HEIGHT }}>
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
                {/* 跨轨拖拽时,片段还留在原轨的数据里,得在目标轨先画一个草稿本体。
                    组拖要对**每个**落到本轨的成员都画,不只锚点。 */}
                {dragDraft?.kind === "move" &&
                  [...draftByClip.entries()]
                    .filter(([clipId, at]) => at.trackId === track.id && !(track.clips ?? []).some((c) => c.id === clipId))
                    .map(([clipId, at]) => {
                      const source = allClips.find((item) => item.id === clipId);
                      if (!source) return null;
                      return (
                        <TimelineClip
                          key={`draft-${clipId}`}
                          trackKind={track.kind}
                          name={source.text_override ?? (source.asset_id ? assetById.get(source.asset_id)?.name ?? "" : "")}
                          left={timeToPx(at.timeline_start, pxPerSecond)}
                          width={Math.max(10, timeToPx((at.src_out - at.src_in) / (source.speed || 1), pxPerSecond))}
                          selected
                          dragging
                        />
                      );
                    })}
                {(track.clips ?? []).map((clip) => {
                  const at = draftByClip.get(clip.id);
                  // 已被拖到别的轨:本轨不画(目标轨的草稿本体负责显示)。
                  if (at && at.trackId !== track.id) return null;
                  // 视口外的不画。正在拖/裁的那几段例外:它们的指针监听挂在自己身上(裁剪手柄),
                  // 卸载会掐断手势;插入预览里被挤开的下游可能从左边被推进视口,窗口按位移放宽。
                  if (!at) {
                    const reach = insertRipple?.trackId === track.id ? insertRipple.shift : 0;
                    if (!inWindow(clip.timeline_start, clipEnd(clip) + reach)) return null;
                  }
                  const draft = at ?? null;
                  // 覆盖预览:被拖着的片段盖住的部分挖掉。整段盖住就不画;露出好几截的,第一截画在本体上、
                  // 其余几截由 lane 末尾的幽灵段画。
                  const carved = at ? undefined : overwriteCarve.get(clip.id);
                  if (carved && carved.length === 0) return null;
                  const firstPiece = carved?.[0];
                  const display = draft ?? (firstPiece
                    ? {
                        ...clip,
                        timeline_start: firstPiece.start,
                        src_in: timelineToSrc(clip, firstPiece.start),
                        src_out: timelineToSrc(clip, firstPiece.end),
                      }
                    : clip);
                  // Insert-mode preview: clips at/after the drop point slide right by the
                  // dragged clip's duration, showing where the ripple will land them.
                  const partingShift =
                    insertRipple &&
                    insertRipple.trackId === track.id &&
                    !draftByClip.has(clip.id) &&
                    clip.timeline_start >= insertRipple.from - 1e-9
                      ? insertRipple.shift
                      : 0;
                  // 位移一律走 transform、left 固定在已提交位置(前身项目手法):
                  // 拖拽本体 duration-0 跟手,松手/涟漪让位则由过渡平滑滑入。
                  // 落位帧的滑行原理:提交落缓存时 left 跳到终值、shift 同帧归零,
                  // 两个属性各自做 200ms 过渡 → 视觉位置 = left+shift 从"松手点"
                  // 平滑插值到"终点";服务端原样接受落点时两者恰好抵消,纹丝不动。
                  // 裁剪草稿仍直接渲染 left/width(裁的是边缘,transform 表达不了)。
                  // 映射条目不带 kind:裁剪只可能作用在锚点上,所以整轮的种类看 dragDraft 即可。
                  const isMoveDraft = Boolean(draft && dragDraft?.kind === "move");
                  const baseLeft = isMoveDraft ? clip.timeline_start : display.timeline_start;
                  const shiftTime = isMoveDraft ? display.timeline_start - clip.timeline_start : partingShift;
                  // 插入预览要切开的跨落点片段:头段就地收尾到落点(尾段由 lane 末尾的
                  // 幽灵段表达)。宽度走同一 200ms 过渡,松手落库后宽度恰好等于预览值。
                  const splitPreview =
                    insertRipple?.split && insertRipple.trackId === track.id && insertRipple.split.clipId === clip.id
                      ? insertRipple.split
                      : null;
                  const displaySrcOut = splitPreview ? splitPreview.cutSrc : display.src_out;
                  const waveform = clip.asset_id ? waveformByAsset.get(clip.asset_id) : undefined;
                  const clipWidth = Math.max(10, timeToPx((displaySrcOut - display.src_in) / (clip.speed || 1), pxPerSecond));
                  const peaks =
                    waveform && clip.asset_id
                      ? cachedPeaks(peaksCache.current, clip.asset_id, waveform, display.src_in, displaySrcOut, clipWidth)
                      : undefined;
                  return (
                    <TimelineClip
                      key={clip.id}
                      clipId={clip.id}
                      trackId={track.id}
                      trackKind={track.kind}
                      offline={Boolean(clip.offline_asset)}
                      aiGenerated={Boolean(clip.asset_id && aiAssetIds.has(clip.asset_id))}
                      // 脱机片段显示**它原来的**素材名 —— 那是用户唯一能拿来对回去的线索。
                      name={
                        clip.text_override ??
                        (clip.offline_asset
                          ? String(clip.offline_asset.name || t("clipOffline"))
                          : clip.asset_id
                            ? assetById.get(clip.asset_id)?.name ?? clip.asset_id.slice(0, 8)
                            : "")
                      }
                      left={timeToPx(baseLeft, pxPerSecond)}
                      shiftPx={timeToPx(shiftTime, pxPerSecond)}
                      width={clipWidth}
                      animate={animateClips}
                      selected={selectedClipIds.includes(clip.id)}
                      dragging={Boolean(draft)}
                      peaks={peaks}
                      onClipPointerDown={handleClipPointerDown}
                      onClipTrimPointerDown={handleClipTrimPointerDown}
                      onClipSelect={handleClipSelect}
                      onClipFocus={handleClipFocus}
                      tabbable={clip.id === tabbableClipId}
                      cut={cutIds.has(clip.id)}
                    />
                  );
                })}
                {/* 插入预览切出的尾段幽灵:落在切点上、随下游一起右移。松手落库后
                    真尾段出现在同一视觉位置、幽灵同帧卸载,肉眼看不出交接。 */}
                {insertRipple?.split &&
                  insertRipple.trackId === track.id &&
                  (() => {
                    const src = (track.clips ?? []).find((c) => c.id === insertRipple.split?.clipId);
                    if (!src) return null;
                    const { cutSrc, tailDuration } = insertRipple.split;
                    const width = Math.max(10, timeToPx(tailDuration, pxPerSecond));
                    const waveform = src.asset_id ? waveformByAsset.get(src.asset_id) : undefined;
                    const peaks =
                      waveform && src.asset_id
                        ? cachedPeaks(peaksCache.current, src.asset_id, waveform, cutSrc, src.src_out, width)
                        : undefined;
                    return (
                      <TimelineClip
                        key={`split-tail-${src.id}`}
                        trackKind={track.kind}
                        name={src.text_override ?? (src.asset_id ? assetById.get(src.asset_id)?.name ?? "" : "")}
                        left={timeToPx(insertRipple.from, pxPerSecond)}
                        shiftPx={timeToPx(insertRipple.shift, pxPerSecond)}
                        width={width}
                        animate={animateClips}
                        selected={false}
                        dragging={false}
                        peaks={peaks}
                      />
                    );
                  })()}
                {/* 覆盖预览里被切成两截的片段:后一截的幽灵(松手后后端切出的右段就落在这里)。 */}
                {(track.clips ?? []).flatMap((source) =>
                  (overwriteCarve.get(source.id) ?? []).slice(1).map((piece) => (
                    <TimelineClip
                      key={`carve-${source.id}-${piece.start}`}
                      trackKind={track.kind}
                      name={source.text_override ?? (source.asset_id ? assetById.get(source.asset_id)?.name ?? "" : "")}
                      left={timeToPx(piece.start, pxPerSecond)}
                      width={Math.max(10, timeToPx(piece.end - piece.start, pxPerSecond))}
                      animate={animateClips}
                      selected={false}
                      dragging={false}
                    />
                  )),
                )}
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
                    className="pointer-events-none absolute top-[-1px] z-[8] -translate-x-1/2 whitespace-nowrap rounded-md border border-floating-border bg-popover px-[7px] py-px text-ui-2xs tabular-nums text-foreground"
                    style={{
                      left: timeToPx(edgeTime, pxPerSecond),
                      top: RULER_HEIGHT + trackIndex * TRACK_HEIGHT - 10,
                    }}
                  >
                    {formatFrameTimecode(edgeTime, fps)} · {formatFrameTimecode(duration, fps)}
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
          </ContextMenuTrigger>
          {menuClip && (
            <ContextMenuContent>
              {onSplitClip && (
                <ContextMenuItem onSelect={() => onSplitClip(menuClip.id)}>
                  <Scissors /> {t("splitAtPlayhead")}
                </ContextMenuItem>
              )}
              {onDuplicateClip && (
                <ContextMenuItem onSelect={() => onDuplicateClip(menuClip.id)}>
                  <Copy /> {t("duplicateClip")}
                </ContextMenuItem>
              )}
              {/* 按**素材类型**给,不按轨道:视频轨上完全可以放图片(AI 生成的静图就是这么落上去的),
                  而图片没有声音。片段菜单里的降噪 / 分离是「做完直接换到时间线上」那一版(onClipAudio);
                  素材库里那两项只产出新素材、不动时间线。 */}
              {onDetachAudio && menuTrack?.kind === "video" && menuClip.asset_id && menuClip.asset_kind === "video" && (
                <ContextMenuItem onSelect={() => onDetachAudio(menuClip.id)}>
                  <AudioLines /> {t("detachAudio")}
                </ContextMenuItem>
              )}
              {/* 媒体片段(含脱机的 —— 换一份就重新接上)才能换素材;文字片段没有媒体。 */}
              {onReplaceMedia && (menuClip.asset_id || menuClip.offline_asset) && (
                <ContextMenuItem onSelect={() => onReplaceMedia(menuClip.id)}>
                  <Replace /> {t("replaceMedia")}
                </ContextMenuItem>
              )}
              {onClipAudio && menuClip.asset_id && (menuClip.asset_kind === "video" || menuClip.asset_kind === "audio") && (
                <>
                  <ContextMenuSeparator />
                  <ContextMenuItem onSelect={() => onClipAudio(menuClip.id, "denoise")}>
                    <AudioWaveform /> {t("clipAudioDenoise")}
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => onClipAudio(menuClip.id, "isolate_voice")}>
                    <Mic /> {t("clipAudioIsolateVoice")}
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => onClipAudio(menuClip.id, "separate")}>
                    <Split /> {t("clipAudioSeparate")}
                  </ContextMenuItem>
                </>
              )}
              <ContextMenuSeparator />
              {onDeleteClips && (
                <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => onDeleteClips(menuTargets(menuClip.id))}>
                  <Trash2 /> {t("deleteClip")}
                </ContextMenuItem>
              )}
              {onRippleDeleteClips && (
                <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => onRippleDeleteClips(menuTargets(menuClip.id))}>
                  <Waves /> {t("rippleDelete")}
                </ContextMenuItem>
              )}
            </ContextMenuContent>
          )}
          </ContextMenu>
        </div>
      </div>
      <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-4 border-t border-divider px-3 py-1">
          <PlayheadReadout total={sequenceDuration(allClips)} fps={fps} />
          <span className="whitespace-nowrap text-ui-xs text-muted-foreground">
            {t("clipCount").replace("{n}", String(allClips.length))} · {sequence.width}×{sequence.height} ·{" "}
            {Math.round(sequence.fps)}fps
          </span>
      </div>
    </div>
  );
}

/**
 * 轨道头上的一个开关(静音 / 独奏 / 闪避 / 锁定)。平时藏着,鼠标移到这一行才露出来;**按下去的
 * 一直亮着** —— 不然一条被独奏的轨和一条普通的轨看起来一模一样,「点了没反应」就是这么来的。
 * 悬停给出这个开关是什么、按下去预览和导出会怎样:S、D 两个字母自己说明不了自己。
 */
function TrackToggle({
  active,
  activeClassName,
  label,
  hint,
  onToggle,
  children,
}: {
  active: boolean;
  activeClassName: string;
  label: string;
  hint?: string;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn("grid h-4 w-4 cursor-pointer place-items-center rounded-sm border-0 bg-transparent text-muted-foreground opacity-0 transition-[opacity,color] duration-100 enabled:hover:text-foreground disabled:cursor-default disabled:opacity-25 group-hover/label:opacity-100 focus-visible:opacity-100", active && cn("opacity-100", activeClassName))}
          aria-label={label}
          aria-pressed={active}
          onClick={onToggle}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-[240px]">
        <div className="font-medium">{label}</div>
        {hint && <div className="mt-0.5 text-muted-foreground">{hint}</div>}
      </TooltipContent>
    </Tooltip>
  );
}

/** Isolated playhead subscribers: only these re-render on the ~25×/s playhead tick,
 *  not the whole Timeline (see the note at the top of Timeline). */
function TimelinePlayhead({ pxPerSecond, children }: { pxPerSecond: number; children: React.ReactNode }) {
  // 播放中竖线由 rAF 按插值时钟直接挪(见 playbackClock),不跟 store 那 25Hz 的写入一顿一顿地跳;
  // 暂停时才按 store 的值渲染。播放中这个选择器恒为 null,store 的写入不会让它重渲。
  const pausedAt = useEditorStore((state) => (state.playing ? null : state.playhead));
  const lineRef = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => {
    if (pausedAt !== null) return;
    let raf = 0;
    const tick = () => {
      if (lineRef.current) lineRef.current.style.left = `${timeToPx(livePlayhead(), pxPerSecond)}px`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [pausedAt, pxPerSecond]);
  const left = timeToPx(pausedAt ?? livePlayhead(), pxPerSecond);
  // z-[6] 高于刻度尺(z-5),否则竖线在刻度尺区被 ruler 背景盖住——之前刻度尺上看不到播放头。
  return (
    <div ref={lineRef} className="pointer-events-none absolute bottom-0 top-0 z-[6] w-px bg-[var(--playhead)]" style={{ left }}>
      {/* 刻度尺上的把手:五边形(顶宽下尖)标出播放头位置,像 PR/剪映的播放头头部 */}
      <div
        className="absolute top-0 left-1/2 h-[13px] w-[13px] -translate-x-1/2 bg-[var(--playhead)]"
        style={{ clipPath: "polygon(0 0, 100% 0, 100% 55%, 50% 100%, 0 55%)" }}
      />
      {children}
    </div>
  );
}

/** 入出点之间的选区带(画在标尺上)。只订阅入出点,不让整条时间线跟着它重渲。 */
function MarkedRangeBand({ pxPerSecond, duration }: { pxPerSecond: number; duration: number }) {
  const markIn = useEditorStore((state) => state.markIn);
  const markOut = useEditorStore((state) => state.markOut);
  const range = markedRange({ markIn, markOut }, duration);
  if (!range) return null;
  return (
    <div
      data-testid="timeline-marked-range"
      className="pointer-events-none absolute inset-y-0 border-x-2 border-primary bg-[color-mix(in_srgb,var(--primary)_22%,transparent)]"
      style={{ left: timeToPx(range.start, pxPerSecond), width: timeToPx(range.end - range.start, pxPerSecond) }}
    />
  );
}

function PlayheadReadout({ total, fps }: { total: number; fps: number }) {
  const playhead = useEditorStore((state) => state.playhead);
  return (
    <span className="timecode whitespace-nowrap text-xs font-semibold text-foreground [&_em]:not-italic [&_em]:text-muted-foreground" data-testid="timeline-playhead-readout">
      {formatFrameTimecode(playhead, fps)}
      <em> / {formatFrameTimecode(total, fps)}</em>
    </span>
  );
}

/**
 * 拖动 / 修剪进行中的 Esc:在捕获阶段接住并拦下 —— 这一下 Esc 是「取消这次拖动」,不该再传到
 * 剪辑页的全局快捷键那里(那边的 Esc 是清选区 / 清剪切标记)。回一个摘掉监听的函数。
 */
function listenEscape(onEscape: () => void): () => void {
  return listenKeys(
    window,
    (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onEscape();
    },
    true,
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
