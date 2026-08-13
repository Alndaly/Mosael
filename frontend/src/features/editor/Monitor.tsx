import React from "react";
import { Maximize2, Pause, Play, Repeat, SkipBack, SkipForward, StepBack, StepForward, Volume2, VolumeX } from "lucide-react";

import { assetFileUrl, type Asset, type Clip, type Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { clipEnd, formatTimecode, sequenceDuration } from "@/domain/timeline/geometry";
import { CURVES_FILTER_ID, colorCurvesTables, type ColorCurves } from "@/features/editor/colorCurves";
import { CanvasCompositor, type CompositorLayer } from "@/features/editor/playback/CanvasCompositor";
import { WebAudioMixer, type AudioSourceSpec } from "@/features/editor/playback/WebAudioMixer";
import { compositorSupported } from "@/features/editor/playback/compositorFlag";
import { PreviewUnavailable } from "@/features/editor/playback/PreviewUnavailable";
import { blockingPreviewState } from "@/features/editor/playback/previewReadiness";
import { readSubtitleStyle, subtitleCss } from "@/features/editor/subtitleStyle";
import { readTextStyle, textStyleCss } from "@/features/editor/textStyle";
import { applyTransformCommit, clipProgress, sampleTransform, type GainKeyframe } from "@/features/editor/keyframes";
import { TransformOverlay, readTransform, transformCss, type Transform } from "@/features/editor/TransformOverlay";
import { useEditorStore } from "@/stores/editorStore";

/**
 * 监视器。画面**只有一条路**:WebCodecs 解代理 → CanvasCompositor 合成到一张 canvas。
 *
 * 曾经还有一条 `<video>`/`<img>` 元素路作兜底,已删除——两条路的取景、层级、调色都对不齐,
 * 于是"预览长什么样"取决于当时走了哪条,同一个问题要按两套语义各查一遍。画不出来时改为
 * **明说**(PreviewUnavailable:转码中 / 失败 / 本机解不动 / 环境不支持),而不是悄悄退化成
 * 另一套画法。播放头由 WebAudioMixer 的 AudioContext 驱动(唯一主时钟)。
 */
/** How far ahead of the playhead to warm an upcoming clip's decoder. One short-GOP proxy's
    fetch+parse+first-GOP fits comfortably inside this, so a cut into it never flashes black. */
const PREWARM_SEC = 0.8;
/** CSS approximations of the backend FFmpeg filter presets (render_plan.FILTER_PRESETS). */
const FILTER_CSS: Record<string, string> = {
  bw: "grayscale(1)",
  warm: "sepia(0.22) saturate(1.15)",
  cool: "hue-rotate(-8deg) saturate(1.1) brightness(1.02)",
  vivid: "saturate(1.4) contrast(1.06)",
  fade: "saturate(0.75) contrast(0.9) brightness(1.05)",
};

export function Monitor({
  sequence,
  subtitleStyleOverride,
  assets,
  onSetTransform,
  onSetText,
  onRefreshAssets,
}: {
  sequence: Sequence;
  /** In-progress style from the subtitle panel, so dragging a slider previews live. */
  subtitleStyleOverride?: Record<string, unknown> | null;
  assets: Asset[];
  onSetTransform?: (clipId: string, transform: Transform) => void;
  /** 双击花字在画布上就地编辑文字后提交。 */
  onSetText?: (clipId: string, text: string) => void;
  /** 重新拉取素材。代理转码中时按秒轮询,重试代理后也立刻调一次——服务端实体归 React Query
      持有(见 ARCHITECTURE 的前端约定),所以 Monitor 只发信号,不自己取数。 */
  onRefreshAssets?: () => void;
}) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds);
  const playing = useEditorStore((state) => state.playing);
  const loop = useEditorStore((state) => state.loop);
  const playbackRate = useEditorStore((state) => state.playbackRate);
  const volume = useEditorStore((state) => state.volume);
  const masterMuted = useEditorStore((state) => state.muted);
  const { setPlayhead, setPlaying, togglePlaying, toggleLoop, cyclePlaybackRate, setVolume, toggleMuted } =
    useEditorStore.getState();
  const stageRef = React.useRef<HTMLDivElement | null>(null);
  const monitorStageRef = React.useRef<HTMLDivElement | null>(null);
  const scrubRef = React.useRef<HTMLDivElement | null>(null);

  const assetById = React.useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const videoTracks = React.useMemo(
    () =>
      (sequence.tracks ?? [])
        .filter((item) => item.kind === "video")
        .sort((a, b) => a.position - b.position),
    [sequence],
  );
  // PR/DaVinci z-order: the topmost timeline video track renders on top. videoTracks is sorted by
  // position ascending (top row first), so the base (bottom layer, full frame) is the LAST track;
  // tracks above composite upward, rendered so the top row (index 0) is last in the DOM = on top.
  const videoClips = React.useMemo(
    () => [...(videoTracks[videoTracks.length - 1]?.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start),
    [videoTracks],
  );
  const overlayClips = React.useMemo(
    () =>
      videoTracks
        .slice(0, -1)
        .reverse()
        .flatMap((track) => [...(track.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start)),
    [videoTracks],
  );
  const audioTracks = React.useMemo(
    () => (sequence.tracks ?? []).filter((item) => item.kind === "audio"),
    [sequence],
  );
  const subtitleClips = React.useMemo(
    () =>
      (sequence.tracks ?? [])
        .filter((item) => item.kind === "subtitle" && !item.muted)
        .flatMap((track) => track.clips ?? []),
    [sequence],
  );
  // 花字:video 轨上无 asset 的文本片段。作为最上层 DOM 叠加渲染(与 compositor/element 视频路径
  // 解耦,和字幕同理),用 transform 定位、随关键帧动画,匹配后端 ASS 烧录。
  const textOverlayClips = React.useMemo(
    () =>
      videoTracks
        .filter((track) => !track.muted)
        .flatMap((track) => (track.clips ?? []).filter((clip) => !clip.asset_id && clip.text_override)),
    [videoTracks],
  );
  const activeTextClips = React.useMemo(
    () => textOverlayClips.filter((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)),
    [textOverlayClips, playhead],
  );
  const totalDuration = React.useMemo(
    () => sequenceDuration((sequence.tracks ?? []).flatMap((track) => track.clips ?? [])),
    [sequence],
  );

  const activeClip =
    videoClips.find((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)) ?? null;
  const activeAsset = activeClip?.asset_id ? (assetById.get(activeClip.asset_id) ?? null) : null;
  // 改画幅:画框宽高比 + 填充模式(cover 裁剪 / contain 留黑边 / blur 模糊背景)。
  const fillMode = ((sequence.reframe as { fill_mode?: string } | undefined)?.fill_mode ?? "cover") as
    | "cover"
    | "contain"
    | "blur";
  const frameStyle = React.useMemo<React.CSSProperties>(
    () => ({
      aspectRatio: `${sequence.width} / ${sequence.height}`,
      ["--frame-ar" as string]: sequence.width / Math.max(1, sequence.height),
    }),
    [sequence.width, sequence.height],
  );
  const fitStyle: React.CSSProperties = { objectFit: fillMode === "cover" ? "cover" : "contain" };
  // On-canvas direct manipulation: while dragging a handle, `draft` overrides the selected clip's
  // saved transform so the media tracks the box live; committed on release via onSetTransform.
  // (selectedActive + clipTransformStyle are derived below, after the overlay elements.)
  const [draft, setDraft] = React.useState<Transform | null>(null);
  // 双击花字进入就地编辑;编辑态用独立 key 重挂 + ref 初始化内容,避免每帧重渲染覆盖用户输入。
  const [editingTextId, setEditingTextId] = React.useState<string | null>(null);
  const cancelEditRef = React.useRef(false); // Esc 取消编辑时跳过 onBlur 的提交
  // Time of the last transform-drag movement — the click that *ends* a drag would otherwise
  // bubble to the frame's click-to-play; ignore clicks within a short window after a drag.
  const tfInteractRef = React.useRef(0);
  // Keep the draft until the fresh sequence lands (same anti-flicker pattern as timeline drags),
  // otherwise clearing the draft on release snaps the box back to the stale saved transform.
  const tfSettleRef = React.useRef(false);
  const activeSubtitle =
    subtitleClips.find((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)) ?? null;
  const activeEffects = (activeClip?.effects ?? {}) as {
    filter?: string;
    color?: Record<string, number> & { curves?: ColorCurves };
  };
  const { cssFilter, vignette, curveTables } = React.useMemo(() => {
    const parts: string[] = [];
    const preset = FILTER_CSS[String(activeEffects.filter ?? "")];
    if (preset) parts.push(preset);
    const grade = activeEffects.color ?? {};
    const v = (key: string) => Math.max(-1, Math.min(1, Number(grade[key]) || 0));
    // CSS 近似导出端的 FFmpeg 公式(色阶曲线/锐化无法用 CSS 表达,仅导出生效)。
    const brightFactor = (1 + v("brightness")) * (1 + v("exposure") / 2);
    if (Math.abs(brightFactor - 1) > 0.005) parts.push(`brightness(${brightFactor.toFixed(3)})`);
    if (v("contrast")) parts.push(`contrast(${(1 + v("contrast") * 0.6).toFixed(3)})`);
    if (v("gamma")) parts.push(`brightness(${(1 + v("gamma") * 0.25).toFixed(3)})`);
    const sat = 1 + v("saturation") + v("vibrance") * 0.5;
    if (Math.abs(sat - 1) > 0.005) parts.push(`saturate(${Math.max(0, sat).toFixed(3)})`);
    if (v("hue")) parts.push(`hue-rotate(${(v("hue") * 180).toFixed(1)}deg)`);
    const w = v("temperature");
    if (w > 0) parts.push(`sepia(${(w * 0.25).toFixed(3)})`);
    else if (w < 0) parts.push(`hue-rotate(${(w * 12).toFixed(1)}deg) saturate(${(1 - w * 0.08).toFixed(3)})`);
    if (v("tint")) parts.push(`hue-rotate(${(v("tint") * -8).toFixed(1)}deg)`);
    const fadeAmount = Math.max(0, v("fade"));
    if (fadeAmount) parts.push(`contrast(${(1 - fadeAmount * 0.25).toFixed(3)}) brightness(${(1 + fadeAmount * 0.08).toFixed(3)})`);
    // 色调曲线无法用 CSS filter 函数表达 → 引用一次性渲染的 SVG feComponentTransfer 滤镜精确查表。
    const tables = colorCurvesTables(grade.curves);
    if (tables) parts.push(`url(#${CURVES_FILTER_ID})`);
    return { cssFilter: parts.join(" "), vignette: Math.max(0, v("vignette")), curveTables: tables };
  }, [activeEffects.filter, activeEffects.color]);
  const isImage = activeAsset?.kind === "image";
  // 画面引擎:WebCodecs 解代理 → 一张 canvas 合成全部活跃视频/图片片段。没有第二条路。
  const webCodecsOk = compositorSupported();
  // 上层视频轨(V2+)当前活跃的片段,按轨道 z 序。合成器把它们和 base 一起画在同一张 canvas 上;
  // 这里保留这份列表是给变换手柄用的(选中哪个元素就把手柄挂到哪个上)。
  const activeOverlayClips = React.useMemo(
    () => overlayClips.filter((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)),
    [overlayClips, playhead],
  );
  // The selected on-screen element (base V1 or any active overlay) gets the transform handles.
  const selectedActive = React.useMemo(
    () => [activeClip, ...activeOverlayClips].find((clip) => clip && selectedClipIds.includes(clip.id)) ?? null,
    [activeClip, activeOverlayClips, selectedClipIds],
  );
  React.useEffect(() => setDraft(null), [selectedActive?.id]);
  // Drop the committed draft only once the fresh sequence has propagated (armed on commit), so the
  // box never flashes back to the pre-drag transform between release and the server round-trip.
  React.useEffect(() => {
    if (tfSettleRef.current) {
      tfSettleRef.current = false;
      setDraft(null);
    }
  }, [sequence]);
  const draftFor = (clipId: string | undefined) => (draft && selectedActive?.id === clipId ? draft : null);
  const clipTransformStyle = React.useMemo<React.CSSProperties>(
    () =>
      transformCss(
        draftFor(activeClip?.id) ??
          (activeClip
            ? sampleTransform(readTransform(activeClip.transform), clipProgress(activeClip, playhead))
            : readTransform(undefined)),
      ),
    // 关键帧:base 轨 clip 的预览 transform 也要随播放头插值,故 playhead 入依赖。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draft, selectedActive?.id, activeClip?.id, activeClip?.transform, playhead],
  );

  // Active video/image clips in z-order (base first = bottom, overlays bottom→top) as
  // compositor layers, each carrying its live drag transform. Memoised so the compositor's
  // decoder pool doesn't churn on every playhead tick.
  const compositorLayers = React.useMemo<CompositorLayer[]>(() => {
    const layers: CompositorLayer[] = [];
    for (const clip of [activeClip, ...activeOverlayClips]) {
      if (!clip?.asset_id) continue;
      const asset = assetById.get(clip.asset_id);
      if (!asset || (asset.kind !== "video" && asset.kind !== "image")) continue;
      layers.push({ clip, asset, transformOverride: draft && selectedActive?.id === clip.id ? draft : null });
    }
    return layers;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeClip, activeOverlayClips, assetById, draft, selectedActive?.id]);
  // Video clips (any video track) the playhead is about to reach — handed to the compositor to warm
  // their decoders before the cut, so playing into a never-seen proxy paints immediately instead of
  // flashing black through its fetch/parse/first-GOP window. The id-set (not the clip objects) is the
  // stable key: it only changes when a clip enters/leaves the look-ahead window, so the array identity
  // holds across playhead ticks and the compositor's source pool doesn't churn every frame.
  const prewarmIds = React.useMemo(() => {
    const ids: string[] = [];
    const horizon = playhead + PREWARM_SEC;
    for (const track of videoTracks) {
      for (const clip of track.clips ?? []) {
        if (!clip.asset_id || assetById.get(clip.asset_id)?.kind !== "video") continue;
        if (clip.timeline_start > playhead && clip.timeline_start <= horizon) ids.push(clip.id);
      }
    }
    return ids;
  }, [videoTracks, assetById, playhead]);
  const prewarmKey = prewarmIds.join(",");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const prewarmSet = React.useMemo(() => new Set(prewarmIds), [prewarmKey]);
  const prewarmLayers = React.useMemo<CompositorLayer[]>(() => {
    const out: CompositorLayer[] = [];
    for (const track of videoTracks) {
      for (const clip of track.clips ?? []) {
        if (!prewarmSet.has(clip.id)) continue;
        const asset = clip.asset_id ? assetById.get(clip.asset_id) : null;
        if (asset && asset.kind === "video") out.push({ clip, asset });
      }
    }
    return out;
  }, [prewarmSet, videoTracks, assetById]);
  // Only take the canvas path when every active clip can be drawn there (image, or a
  // video whose proxy is ready); otherwise fall back wholesale to the element preview.
  // Assets whose proxy turned out to be undecodable HERE — a codec this browser lacks, a
  // truncated file. proxy_status says the file exists, not that this machine can play it, so
  // that check alone let a decode failure show as a black frame. Falling back is per-asset and
  // sticky for the session — retrying every frame would flicker between black and the element.
  const [undecodable, setUndecodable] = React.useState<ReadonlySet<string>>(() => new Set());
  const markUndecodable = React.useCallback((assetId: string) => {
    setUndecodable((current) => (current.has(assetId) ? current : new Set(current).add(assetId)));
  }, []);
  // 播放头**当前真正要画**的素材。按整条序列判定过一次(为了让引擎选择稳定,避免每帧在
  // 合成器/元素路之间来回切),但元素路删掉之后引擎只有一个,不会再切,所以这里回到逐帧判定
  // ——时间线末尾一个还在转码的片段,不该把开头已经能放的部分一起挡住。
  const activeVisualAssets = React.useMemo(() => {
    const seen = new Map<string, Asset>();
    for (const clip of [activeClip, ...activeOverlayClips]) {
      const asset = clip?.asset_id ? assetById.get(clip.asset_id) : null;
      if (asset && (asset.kind === "video" || asset.kind === "image")) seen.set(asset.id, asset);
    }
    return [...seen.values()];
  }, [activeClip, activeOverlayClips, assetById]);
  // 画不出来的原因(全部就绪则为 null)。环境不支持 WebCodecs 时压过一切:那是整个预览引擎缺失,
  // 报某个素材"转码中"会把用户引到错误的方向。
  const previewBlock = React.useMemo(
    () => (webCodecsOk ? blockingPreviewState(activeVisualAssets, undecodable) : { state: "unsupported" as const, assets: [] }),
    [webCodecsOk, activeVisualAssets, undecodable],
  );
  // 代理还在转时轮询素材:否则转好了界面也不会自己活过来,用户只能手动刷新。
  const pendingProxy = previewBlock?.state === "transcoding";
  React.useEffect(() => {
    if (!pendingProxy || !onRefreshAssets) return;
    const timer = window.setInterval(onRefreshAssets, 2000);
    return () => window.clearInterval(timer);
  }, [pendingProxy, onRefreshAssets]);
  // EVERY audio-bearing clip (base video-track video clips + all audio-track clips) fed to the
  // WebAudio mixer, which filters by the live playhead itself. Passing the full set — not just
  // the currently-active clips — means a clip that comes up under the advancing playhead is
  // already in the mixer's list, so it starts on time instead of one render late.
  const audioSources = React.useMemo<AudioSourceSpec[]>(() => {
    const list: AudioSourceSpec[] = [];
    for (const track of videoTracks) {
      for (const clip of track.clips ?? []) {
        if (!clip.asset_id || assetById.get(clip.asset_id)?.kind !== "video") continue; // images have no audio
        list.push({
          key: clip.id, assetId: clip.asset_id, srcIn: clip.src_in, srcOut: clip.src_out,
          timelineStart: clip.timeline_start, speed: clip.speed || 1, gain: clip.gain ?? 1,
          gainKeyframes: (clip.effects as { gain_keyframes?: GainKeyframe[] } | undefined)?.gain_keyframes,
          muted: Boolean(clip.muted), trackMuted: Boolean(track.muted),
        });
      }
    }
    for (const track of audioTracks) {
      for (const clip of track.clips ?? []) {
        if (!clip.asset_id) continue;
        list.push({
          key: clip.id, assetId: clip.asset_id, srcIn: clip.src_in, srcOut: clip.src_out,
          timelineStart: clip.timeline_start, speed: clip.speed || 1, gain: clip.gain ?? 1,
          gainKeyframes: (clip.effects as { gain_keyframes?: GainKeyframe[] } | undefined)?.gain_keyframes,
          muted: Boolean(clip.muted), trackMuted: Boolean(track.muted),
        });
      }
    }
    return list;
  }, [videoTracks, audioTracks, assetById]);


  const frameStep = 1 / (sequence.fps || 30);
  const seekFromScrub = (clientX: number) => {
    const rect = scrubRef.current?.getBoundingClientRect();
    if (!rect || totalDuration <= 0) return;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    setPlayhead(ratio * totalDuration);
  };
  const handleScrub = (event: React.PointerEvent<HTMLDivElement>) => {
    seekFromScrub(event.clientX);
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // synthetic/stale pointers cannot be captured; dragging still works while pressed
    }
  };
  const toggleFullscreen = () => {
    // Fullscreen the stage (not the frame): it's a size container that centers the frame, so the
    // frame's cq-based min(100cqw, 100cqh×ar) sizing now resolves against the SCREEN and stays
    // 16:9 (letterboxed), instead of the frame filling the screen and object-fit cropping it.
    const stage = monitorStageRef.current;
    if (!stage) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void stage.requestFullscreen().catch(() => undefined);
  };
  const playToggle = () => {
    if (!playing && totalDuration > 0 && playhead >= totalDuration) setPlayhead(0);
    togglePlaying();
  };
  // Frame click toggles play — but not the click that just ended a transform drag.
  const onFrameClick = () => {
    if (performance.now() - tfInteractRef.current < 300) return;
    playToggle();
  };

  return (
    <div className="grid h-full grid-rows-[minmax(0,1fr)_auto_auto]">
      {/* 音频只有一条路:WebAudio 混音器,它的 AudioContext 同时是时间线的主时钟。
          曾经还有一条「每个活跃音频片段一个 <audio>」的元素路,随画面元素路一并删除——
          两条路并存时混音器与 <video> 会各放一遍,所以引擎选择必须是唯一且稳定的一个。 */}
      <WebAudioMixer sources={audioSources} totalDuration={totalDuration} />
      {/* 曲线预览滤镜:逐通道 feComponentTransfer 查表,cssFilter 里以 url(#id) 引用。 */}
      {curveTables && (
        <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
          <filter id={CURVES_FILTER_ID} colorInterpolationFilters="sRGB">
            <feComponentTransfer>
              <feFuncR type="table" tableValues={curveTables.r} />
              <feFuncG type="table" tableValues={curveTables.g} />
              <feFuncB type="table" tableValues={curveTables.b} />
            </feComponentTransfer>
          </filter>
        </svg>
      )}
      <div className="grid min-h-0 place-items-center p-3 [container-type:size] [&:fullscreen]:h-screen [&:fullscreen]:w-screen [&:fullscreen]:bg-black [&:fullscreen::backdrop]:bg-black" ref={monitorStageRef}>
        <div className="relative aspect-video max-h-full max-w-full overflow-hidden rounded-sm bg-black [container-type:inline-size] w-[min(100cqw,calc(100cqh*var(--frame-ar,1.7778)))] [:fullscreen_&]:rounded-none" ref={stageRef} onClick={onFrameClick} style={frameStyle}>
          {/* fillMode=blur 的模糊背景由 paintScene 直接画在同一张 canvas 上(见 scenePaint),
              这里不再另铺一层 DOM 视频——那是元素路的做法,两者会叠出双重背景。 */}
          <CanvasCompositor
            onSourceFailed={markUndecodable}
            layers={compositorLayers}
            prewarmLayers={prewarmLayers}
            width={sequence.width}
            height={sequence.height}
            fillMode={fillMode}
            className="absolute inset-0 z-[1] h-full w-full bg-black object-contain"
            style={fitStyle}
          />
          {previewBlock && (
            <PreviewUnavailable state={previewBlock.state} assets={previewBlock.assets} onRetried={onRefreshAssets} />
          )}
          {!activeClip && (
            <div className="grid h-full w-full place-items-center bg-black object-contain">
              <span className="px-5 text-center text-ui-sm text-[rgb(255_255_255/0.4)]">{t("monitorBlankHint")}</span>
            </div>
          )}
          {vignette > 0 && (
            <div
              className="pointer-events-none absolute inset-0 z-[2]"
              style={{ boxShadow: `inset 0 0 ${60 + vignette * 120}px ${vignette * 60}px rgba(0,0,0,${0.35 + vignette * 0.4})` }}
            />
          )}
          {activeSubtitle?.text_override && (
            // 定位(left/top/bottom/transform)全部来自 subtitleCss 的行内样式,类里不要再写
            // 定位类:Tailwind v4 的 -translate-x-1/2 编译成独立的 translate 属性,会和行内
            // transform 叠加成双重位移(字幕整体左偏半个画框宽,曾以此形态返场过一次)。
            <div
              // 盒子几何(最大宽/圆角/内边距/行高/对齐/投影)**全部来自 subtitleCss**,
              // 类里一个都不要写:它们是和导出侧的契约(contracts/subtitle-cases.json),
              // 在这里重写一份就等于给同一个问题准备了第二个答案。
              className="pointer-events-none absolute z-[3]"
              style={subtitleCss(
                readSubtitleStyle(
                  (subtitleStyleOverride ?? sequence.subtitle_style) as Record<string, unknown>,
                ),
                sequence.width,
              )}
            >
              {activeSubtitle.text_override}
            </div>
          )}
          {/* 花字:每条按自身 transform 定位、随关键帧动画,DOM 叠加在视频之上(与导出的 ASS 一致)。 */}
          {activeTextClips.map((clip) => {
            // 拖外框(TransformOverlay)时 draft 实时驱动,花字与手柄同步动;否则按关键帧采样。
            const tf = draftFor(clip.id) ?? sampleTransform(readTransform(clip.transform), clipProgress(clip, playhead));
            const elStyle = textStyleCss(readTextStyle((clip.effects as { text_style?: unknown } | undefined)?.text_style), tf, sequence.width);
            if (editingTextId === clip.id) {
              // 就地编辑:独立 key 重挂 + ref 一次性写入内容(无 React children),避免每帧重渲染覆盖输入。
              return (
                <div
                  key={`${clip.id}-edit`}
                  className="pointer-events-auto absolute z-[5] cursor-text outline outline-2 outline-primary"
                  style={elStyle}
                  contentEditable
                  suppressContentEditableWarning
                  ref={(el) => {
                    if (el && !el.dataset.init) {
                      el.dataset.init = "1";
                      el.textContent = clip.text_override ?? "";
                      el.focus();
                      const range = document.createRange();
                      range.selectNodeContents(el);
                      const sel = window.getSelection();
                      sel?.removeAllRanges();
                      sel?.addRange(range);
                    }
                  }}
                  onPointerDown={(event) => event.stopPropagation()}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      cancelEditRef.current = true;
                      event.currentTarget.blur();
                    } else if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      event.currentTarget.blur();
                    }
                  }}
                  onBlur={(event) => {
                    const text = (event.currentTarget.textContent ?? "").trim();
                    setEditingTextId(null);
                    if (!cancelEditRef.current && text && text !== clip.text_override) onSetText?.(clip.id, text);
                    cancelEditRef.current = false;
                  }}
                />
              );
            }
            return (
              <div
                key={clip.id}
                className="pointer-events-auto absolute z-[3] cursor-move"
                style={elStyle}
                onClick={(event) => {
                  event.stopPropagation();
                  useEditorStore.getState().selectClip(clip.id);
                }}
                onDoubleClick={(event) => {
                  event.stopPropagation();
                  useEditorStore.getState().selectClip(clip.id);
                  setEditingTextId(clip.id);
                }}
              >
                {clip.text_override}
              </div>
            );
          })}
          {selectedActive && onSetTransform && (
            <div className="pointer-events-none absolute inset-0 z-[4]" onClick={(event) => event.stopPropagation()}>
              <TransformOverlay
                frameRef={stageRef}
                transform={draft ?? sampleTransform(readTransform(selectedActive.transform), clipProgress(selectedActive, playhead))}
                onChange={(tf) => {
                  tfInteractRef.current = performance.now();
                  setDraft(tf);
                }}
                onCommit={(next) => {
                  tfInteractRef.current = performance.now();
                  tfSettleRef.current = true; // hold the draft until the fresh sequence arrives
                  // 关键帧模式:拖拽结果写到当前进度的关键帧(已打点的属性),而不是覆盖基值。
                  onSetTransform(
                    selectedActive.id,
                    applyTransformCommit(readTransform(selectedActive.transform), clipProgress(selectedActive, playhead), next),
                  );
                }}
              />
            </div>
          )}
        </div>
      </div>
      <div
        className="group/scrub relative mx-3 flex h-3.5 cursor-pointer touch-none items-center before:absolute before:inset-x-0 before:h-[3px] before:rounded-sm before:bg-[rgb(255_255_255/0.16)] before:content-['']"
        ref={scrubRef}
        onPointerDown={handleScrub}
        onPointerMove={(event) => event.buttons & 1 && seekFromScrub(event.clientX)}
      >
        <div
          className="pointer-events-none relative h-[3px] rounded-sm bg-primary after:absolute after:-right-[5px] after:top-1/2 after:h-2.5 after:w-2.5 after:-translate-y-1/2 after:rounded-full after:bg-white after:opacity-0 after:transition-opacity after:duration-100 after:content-[''] group-hover/scrub:after:opacity-100"
          style={{ width: totalDuration > 0 ? `${(Math.min(playhead, totalDuration) / totalDuration) * 100}%` : "0%" }}
        />
      </div>
      {/* 底部行:左右缩进与画面/进度条同一刻度(12px);上下留白让按钮离面板底边有呼吸感,
          不再紧贴底边界线(pt 略小于 pb,视觉重心稍稍上抬)。 */}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-1.5 px-3 pb-2.5 pt-1 [&>div:last-child]:justify-end [&_button]:text-[#c6cbd2] [&_button:hover]:bg-[rgb(255_255_255/0.08)] [&_button:hover]:text-white">
        <div className="flex items-center gap-0.5">
          <Button variant="ghost" size="icon" onClick={() => setPlayhead(0)} aria-label={t("monStart")}>
            <SkipBack size={14} />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setPlayhead(Math.max(0, playhead - frameStep))} aria-label={t("monFrameBack")}>
            <StepBack size={14} />
          </Button>
          <Button variant="secondary" size="icon" className="h-7 w-7 rounded-full! bg-white! text-[#17181a]! transition-transform duration-[120ms] hover:scale-[1.06] hover:bg-white! hover:text-[#17181a]!" onClick={playToggle} aria-label={t("playPause")}>
            {playing ? <Pause size={14} /> : <Play size={14} className="ml-px" />}
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setPlayhead(Math.min(totalDuration, playhead + frameStep))} aria-label={t("monFrameForward")}>
            <StepForward size={14} />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setPlayhead(totalDuration)} aria-label={t("monEnd")}>
            <SkipForward size={14} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={loop ? "bg-[rgb(255_255_255/0.1)]! text-primary!" : undefined}
            onClick={toggleLoop}
            aria-label={t("monLoop")}
          >
            <Repeat size={13} />
          </Button>
          <button type="button" className="timecode cursor-pointer rounded-md border border-[rgb(255_255_255/0.18)] bg-transparent px-[7px] py-0.5 text-ui-xs text-[#c6cbd2] hover:bg-[rgb(255_255_255/0.08)] hover:text-white" onClick={cyclePlaybackRate} aria-label={t("monRate")}>
            {playbackRate}x
          </button>
        </div>
        <div className="timecode text-xs text-[#e8eaed]">
          {formatTimecode(playhead)}
          <span className="text-[#82878f]"> / {formatTimecode(totalDuration)}</span>
        </div>
        <div className="flex items-center gap-0.5">
          <Button variant="ghost" size="icon" onClick={toggleMuted} aria-label={t("monMute")}>
            {masterMuted || volume === 0 ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </Button>
          <Slider
            className="w-[68px] flex-none [--slider-range:rgba(255,255,255,0.75)] [--slider-thumb:#ffffff] [--slider-track:rgba(255,255,255,0.22)]"
            min={0}
            max={1}
            step={0.05}
            value={[masterMuted ? 0 : volume]}
            onValueChange={([value]) => setVolume(value)}
            aria-label={t("monVolume")}
          />
          <Button variant="ghost" size="icon" onClick={toggleFullscreen} aria-label={t("monFullscreen")}>
            <Maximize2 size={13} />
          </Button>
        </div>
      </div>
    </div>
  );
}
