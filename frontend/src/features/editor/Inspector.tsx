import React from "react";
import { AlignCenter, AlignLeft, AlignRight, Bold, Diamond, Italic, Loader2, RotateCcw, Trash2, Upload, X } from "lucide-react";

import type { Asset, Clip, Font, Sequence } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/app/preferences";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";
import { clipProgress, hasActiveKeyframes, propTimes, sampleProp, togglePropKeyframe, upsertKeyframe, sampleGain, gainKeyTimes, toggleGainKeyframe, upsertGainKeyframe, type GainKeyframe, type Keyframe, type KfProp } from "@/features/editor/keyframes";
import { readTextStyle, TEXT_PRESETS, type TextStyle } from "@/features/editor/textStyle";
import { SUBTITLE_FONTS } from "@/features/editor/subtitleStyle";
import { uploadedFontStack } from "@/features/editor/FontFaces";
import { useEditorStore } from "@/stores/editorStore";
import { CurveEditor } from "@/features/editor/CurveEditor";
import type { ColorCurves } from "@/features/editor/colorCurves";
import { COLOR_PRESETS, matchColorPreset, presetColorPayload } from "@/features/editor/colorPresets";
import { ClipAppearancePanel } from "@/features/editor/ClipAppearancePanel";
import { LutPicker } from "@/features/editor/LutPicker";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2];

/** 调色面板的完整参数集,沿用前身项目的分组。 */
const GRADE_GROUPS = [
  {
    label: "gradeGroupLight",
    keys: ["exposure", "brightness", "contrast", "gamma", "highlights", "shadows", "whites", "blacks"],
  },
  { label: "gradeGroupColor", keys: ["temperature", "tint", "saturation", "vibrance", "hue"] },
  { label: "gradeGroupFx", keys: ["fade", "sharpen", "vignette"] },
] as const;
const POSITIVE_ONLY = new Set(["fade", "sharpen", "vignette"]);
const GRADE_KEYS = GRADE_GROUPS.flatMap((group) => group.keys);
type GradeKey = (typeof GRADE_KEYS)[number];


const INSPECTOR_TABS = ["props", "color"] as const;

export function Inspector({
  sequence,
  workspaceId,
  selectedClip,
  assets,
  isTitleText,
  onDeleteClip,
  onSetEffects,
  onSetTransform,
  onReframe,
  onSetSpeed,
  onSetGain,
  onSetText,
  fonts,
  onUploadFont,
  onDeleteFont,
  uploadingFont,
  onClose,
}: {
  sequence: Sequence;
  workspaceId: string;
  selectedClip: Clip | null;
  assets: Asset[];
  /** 花字(video 轨上的文本元素):复用画面元素的 transform 面板(定位/缩放/旋转 + 关键帧)。 */
  isTitleText?: boolean;
  onDeleteClip: (clipId: string) => void;
  onSetEffects: (clipId: string, effects: Record<string, unknown>) => void;
  onSetTransform?: (clipId: string, transform: Record<string, unknown>) => void;
  onReframe?: (width: number, height: number, fillMode: string) => void;
  onSetSpeed?: (clipId: string, speed: number) => void;
  onSetGain?: (clipId: string, gain: number, muted: boolean) => void;
  onSetText?: (clipId: string, text: string) => void;
  /** 花字字体:工作区上传字体列表 + 上传/删除(与字幕共用一套基础设施)。 */
  fonts?: Font[];
  onUploadFont?: (file: File) => void;
  onDeleteFont?: (fontId: string) => void;
  uploadingFont?: boolean;
  /** 紧凑模式抽屉需要显式关闭入口(桌面三栏布局不传)。 */
  onClose?: () => void;
}) {
  const t = useI18n();
  // 同上:切走再回来还在这一栏。
  const [tab, setTab] = usePersistentTab<"props" | "color">("editor-inspector", "props", INSPECTOR_TABS);
  const asset = selectedClip?.asset_id ? assets.find((item) => item.id === selectedClip.asset_id) : null;
  const isTextClip = Boolean(selectedClip && !selectedClip.asset_id && selectedClip.text_override != null);
  const isVisualClip = asset?.kind === "video" || asset?.kind === "image";
  const effects = (selectedClip?.effects ?? {}) as {
    fade_in?: number;
    fade_out?: number;
    video_fade_in?: number;
    video_fade_out?: number;
    filter?: string;
    color?: Partial<Record<GradeKey, number>>;
  };

  const applyFade = (
    key: "fade_in" | "fade_out" | "video_fade_in" | "video_fade_out",
    raw: string,
  ) => {
    if (!selectedClip) return;
    const value = Math.max(0, Number(raw) || 0);
    onSetEffects(selectedClip.id, { ...selectedClip.effects, [key]: value });
  };

  const rawTransform = (selectedClip?.transform as Record<string, unknown>) ?? {};
  const keyframes: Keyframe[] = Array.isArray(rawTransform.keyframes) ? (rawTransform.keyframes as Keyframe[]) : [];
  const transform = {
    scale: typeof rawTransform.scale === "number" ? rawTransform.scale : 1,
    x: typeof rawTransform.x === "number" ? rawTransform.x : 0,
    y: typeof rawTransform.y === "number" ? rawTransform.y : 0,
    rotation: typeof rawTransform.rotation === "number" ? rawTransform.rotation : 0,
    opacity: typeof rawTransform.opacity === "number" ? rawTransform.opacity : 1,
    keyframes,
  };
  // 关键帧按属性独立成轨(AE/PR 风):每个属性有自己的关键帧点,互不绑定。滑块作用于 playhead
  // 所在的片段进度——该属性已有关键帧时写该进度点,否则改静态基值;钻石按钮在该属性上打/删点。
  const playhead = useEditorStore((s) => s.playhead);
  const setPlayhead = useEditorStore((s) => s.setPlayhead);
  const progress = selectedClip ? clipProgress(selectedClip, playhead) : 0;
  const clipDuration = selectedClip ? (selectedClip.src_out - selectedClip.src_in) / (selectedClip.speed || 1) : 0;
  const commitTransform = (next: Record<string, unknown>) => {
    if (!selectedClip || !onSetTransform) return;
    onSetTransform(selectedClip.id, next);
  };
  const propKeyed = (prop: KfProp) => propTimes(keyframes, prop).length > 0;
  // 某属性当前显示值:有关键帧→按进度采样(随播放头动),否则基值。
  const shownProp = (prop: KfProp): number => (propKeyed(prop) ? sampleProp(keyframes, prop, transform[prop], progress) : transform[prop]);
  const shown = { scale: shownProp("scale"), rotation: shownProp("rotation"), opacity: shownProp("opacity"), x: shownProp("x"), y: shownProp("y") } as const;
  // 调某属性:该属性有关键帧则写当前进度点,否则改基值。
  const setProp = (prop: KfProp, value: number) => {
    if (propKeyed(prop)) commitTransform({ ...transform, keyframes: upsertKeyframe(keyframes, progress, { [prop]: value }) });
    else commitTransform({ ...transform, [prop]: value });
  };
  const toggleProp = (prop: KfProp) => commitTransform({ ...transform, keyframes: togglePropKeyframe(keyframes, prop, progress, shownProp(prop)) });
  const clearKeyframes = () => commitTransform({ scale: transform.scale, x: transform.x, y: transform.y, rotation: transform.rotation, opacity: transform.opacity });
  const seekToKeyframe = (t: number) => selectedClip && setPlayhead(selectedClip.timeline_start + t * clipDuration);
  const anyKeyframes = keyframes.length > 0;
  const animated = hasActiveKeyframes(transform);
  const isIdentityTransform =
    !anyKeyframes && transform.scale === 1 && transform.x === 0 && transform.y === 0 && transform.rotation === 0 && transform.opacity === 1;

  // 字幕片段没有调色;切换选中对象时回到属性页。
  React.useEffect(() => {
    if (isTextClip) setTab("props");
  }, [selectedClip?.id, isTextClip]);

  return (
    <section className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid min-h-0 grid-rows-[auto_minmax(0,1fr)]">
      <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-ui-xs [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
        {selectedClip && !isTextClip ? (
          <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "props"}
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", tab === "props" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              onClick={() => setTab("props")}
            >
              {t("inspectorProps")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "color"}
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", tab === "color" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              onClick={() => setTab("color")}
            >
              {t("colorGrade")}
            </button>
          </div>
        ) : (
          <h2>{t("inspector")}</h2>
        )}
        <div className="flex items-center gap-0.5">
          {selectedClip && (
            <button
              type="button"
              className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive"
              title={t("deleteClip")}
              aria-label={t("deleteClip")}
              onClick={() => onDeleteClip(selectedClip.id)}
            >
              <Trash2 size={13} />
            </button>
          )}
          {onClose && (
            <button
              type="button"
              className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-secondary hover:text-foreground"
              title={t("close")}
              aria-label={t("close")}
              onClick={onClose}
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>
      {selectedClip ? (
        tab === "color" && !isTextClip ? (
          <ColorGradePanel
            clip={selectedClip}
            workspaceId={workspaceId}
            targetName={asset?.name ?? selectedClip.asset_id?.slice(0, 8) ?? ""}
            effects={effects}
            onSetEffects={onSetEffects}
          />
        ) : (
          <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] content-start gap-1.5 overflow-y-auto overflow-x-hidden p-2.5 [&_dl]:m-0 [&_dl]:grid [&_dl]:grid-cols-[92px_minmax(0,1fr)] [&_dl]:gap-[9px] [&_dl]:text-xs [&_dt]:text-muted-foreground [&_dd]:m-0 [&_dd]:min-w-0">
            <dl>
              <dt>{t("asset")}</dt>
              <dd className="truncate" title={asset?.name}>
                {asset?.name ?? selectedClip.asset_id?.slice(0, 8) ?? (isTitleText ? t("titleText") : t("subtitleText"))}
              </dd>
              <dt>{t("timelineRange")}</dt>
              <dd className="timecode">
                {formatTimecode(selectedClip.timeline_start)} – {formatTimecode(clipEnd(selectedClip))}
              </dd>
              <dt>{t("sourceRange")}</dt>
              <dd className="timecode">
                {formatTimecode(selectedClip.src_in)} – {formatTimecode(selectedClip.src_out)}
              </dd>
              <dt>{t("duration")}</dt>
              <dd className="timecode">{formatTimecode(selectedClip.src_out - selectedClip.src_in)}</dd>
              <dt>{t("speed")}</dt>
              <dd className="timecode">{selectedClip.speed.toFixed(2)}x</dd>
            </dl>
            {isTextClip && onSetText && (
              <div className="grid gap-1.5 border-t border-border pt-2.5">
                <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{isTitleText ? t("titleText") : t("subtitleText")}</span>
                <Textarea
                  key={`text-${selectedClip.id}`}
                  className="w-full resize-y rounded-md border border-border bg-field px-[9px] py-[7px] text-ui-sm leading-normal text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-ring"
                  rows={3}
                  defaultValue={selectedClip.text_override ?? ""}
                  onBlur={(event) => {
                    const value = event.target.value.trim();
                    if (value && value !== selectedClip.text_override) onSetText(selectedClip.id, value);
                  }}
                />
              </div>
            )}
            {isTitleText && (
              <TextStylePanel
                clip={selectedClip}
                onSetEffects={onSetEffects}
                fonts={fonts ?? []}
                onUploadFont={onUploadFont}
                onDeleteFont={onDeleteFont}
                uploadingFont={uploadingFont}
              />
            )}
            {!isTextClip && onSetSpeed && (
              <div className="grid gap-1.5 border-t border-border pt-2.5">
                <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t("speed")}</span>
                <div className="flex flex-wrap gap-1">
                  {SPEED_OPTIONS.map((option) => (
                    <button
                      key={option}
                      type="button"
                      className={cn("min-w-[34px] cursor-pointer rounded-md border border-border bg-panel px-1.5 py-1 text-xs text-muted-foreground transition-[border-color,color,background-color] duration-100 hover:border-border-strong hover:text-foreground", Math.abs(selectedClip.speed - option) < 0.001 && "border-primary bg-accent text-accent-foreground hover:border-primary hover:text-accent-foreground")}
                      onClick={() => onSetSpeed(selectedClip.id, option)}
                    >
                      {option}x
                    </button>
                  ))}
                </div>
              </div>
            )}
            {/* A clip carries its own audio (video clips too, like PR/DaVinci): mix its level/mute. 音量可打关键帧。 */}
            {!isTextClip && onSetGain &&
              (() => {
                const gainKfs: GainKeyframe[] = Array.isArray((effects as { gain_keyframes?: unknown }).gain_keyframes)
                  ? ((effects as { gain_keyframes?: GainKeyframe[] }).gain_keyframes ?? [])
                  : [];
                const gainKeyed = gainKfs.length > 0;
                const shownGain = gainKeyed ? sampleGain(gainKfs, selectedClip.gain, progress) : selectedClip.gain;
                const onGainKf = gainKeyed && gainKeyTimes(gainKfs).some((tt) => Math.abs(tt - progress) < 0.02);
                return (
                  <div className="grid gap-1.5 border-t border-border pt-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t("clipAudio")}</span>
                      <button
                        type="button"
                        className={cn("min-w-[34px] cursor-pointer rounded-md border border-border bg-panel px-1.5 py-1 text-xs text-muted-foreground transition-[border-color,color,background-color] duration-100 hover:border-border-strong hover:text-foreground", selectedClip.muted && "border-primary bg-accent text-accent-foreground hover:border-primary hover:text-accent-foreground")}
                        onClick={() => onSetGain(selectedClip.id, selectedClip.gain, !selectedClip.muted)}
                      >
                        {selectedClip.muted ? t("clipMuted") : t("clipMute")}
                      </button>
                    </div>
                    <div className="grid grid-cols-[52px_1fr_40px_20px] items-center gap-2">
                      <span className="text-ui-xs text-muted-foreground">{t("gain")}</span>
                      <Slider
                        key={`gain-${selectedClip.id}-${shownGain.toFixed(3)}-${gainKfs.length}`}
                        min={0}
                        max={2}
                        step={0.05}
                        defaultValue={[shownGain]}
                        disabled={selectedClip.muted}
                        onValueCommit={([value]) => {
                          if (gainKeyed) onSetEffects(selectedClip.id, { ...selectedClip.effects, gain_keyframes: upsertGainKeyframe(gainKfs, progress, value) });
                          else onSetGain(selectedClip.id, value, selectedClip.muted);
                        }}
                      />
                      <span className="timecode text-right text-ui-xs text-muted-foreground">{Math.round(shownGain * 100)}%</span>
                      <button
                        type="button"
                        title={onGainKf ? t("kfRemoveHere") : t("kfAddHere")}
                        aria-label={onGainKf ? t("kfRemoveHere") : t("kfAddHere")}
                        disabled={selectedClip.muted}
                        className={cn("grid h-5 w-5 cursor-pointer place-items-center rounded border-0 bg-transparent disabled:cursor-default disabled:opacity-40", onGainKf ? "text-primary" : gainKeyed ? "text-muted-foreground hover:text-primary" : "text-muted-foreground/50 hover:text-primary")}
                        onClick={() => onSetEffects(selectedClip.id, { ...selectedClip.effects, gain_keyframes: toggleGainKeyframe(gainKfs, progress, shownGain) })}
                      >
                        <Diamond size={11} fill={onGainKf ? "currentColor" : "none"} />
                      </button>
                    </div>
                  </div>
                );
              })()}
            {!isTextClip && (
              <div className="grid gap-1.5 border-t border-border pt-2.5">
                {(
                  [
                    { title: t("videoFade"), inKey: "video_fade_in", outKey: "video_fade_out", inV: effects.video_fade_in, outV: effects.video_fade_out },
                    { title: t("audioFade"), inKey: "fade_in", outKey: "fade_out", inV: effects.fade_in, outV: effects.fade_out },
                  ] as const
                ).map((grp) => (
                  <div key={grp.title} className="grid gap-1">
                    <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{grp.title}</span>
                    <div className="grid grid-cols-2 gap-1.5">
                      {(
                        [
                          { key: grp.inKey, label: t("fadeIn"), value: grp.inV },
                          { key: grp.outKey, label: t("fadeOut"), value: grp.outV },
                        ] as const
                      ).map((f) => (
                        <label key={f.key} className="grid grid-cols-[auto_1fr] items-center gap-1.5">
                          <span className="text-ui-xs text-muted-foreground">{f.label}</span>
                          <div className="relative">
                            <Input
                              key={`${f.key}-${selectedClip.id}`}
                              className="h-[26px] w-full rounded-md border border-border bg-field pl-1.5 pr-5 text-xs tabular-nums text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-ring"
                              type="number"
                              min={0}
                              step={0.1}
                              defaultValue={f.value ?? 0}
                              onBlur={(event) => applyFade(f.key, event.target.value)}
                              aria-label={`${grp.title} · ${f.label}`}
                            />
                            <span className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-ui-2xs text-muted-foreground">s</span>
                          </div>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {isVisualClip && <ClipAppearancePanel clip={selectedClip} onSetEffects={onSetEffects} />}
            {(!isTextClip || isTitleText) && onSetTransform && (
              <div className="flex flex-col gap-1.5 border-t border-border pt-2.5">
                <div className="flex items-center justify-between">
                  <span className="inline-flex items-center gap-1.5 text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">
                    {t("transformTitle")}
                    {animated && <Diamond size={10} className="text-primary" fill="currentColor" />}
                  </span>
                  <div className="flex items-center gap-2">
                    {anyKeyframes && (
                      <button type="button" className="cursor-pointer border-0 bg-transparent text-ui-xs text-muted-foreground hover:text-destructive" onClick={clearKeyframes}>
                        {t("kfClear")}
                      </button>
                    )}
                    {!isIdentityTransform && (
                      <button
                        type="button"
                        className="cursor-pointer border-0 bg-transparent text-ui-xs text-muted-foreground hover:text-foreground"
                        onClick={() => commitTransform({ scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 })}
                      >
                        {t("transformReset")}
                      </button>
                    )}
                  </div>
                </div>
                {(
                  [
                    { key: "scale", label: t("transformScale"), min: 0.1, max: 4, step: 0.05, fmt: (v: number) => `${Math.round(v * 100)}%`, kf: true },
                    { key: "rotation", label: t("transformRotation"), min: -180, max: 180, step: 1, fmt: (v: number) => `${Math.round(v)}°`, kf: true },
                    { key: "opacity", label: t("transformOpacity"), min: 0, max: 1, step: 0.05, fmt: (v: number) => `${Math.round(v * 100)}%`, kf: true },
                    { key: "x", label: t("transformPosX"), min: -1, max: 1, step: 0.02, fmt: (v: number) => v.toFixed(2), kf: true },
                    { key: "y", label: t("transformPosY"), min: -1, max: 1, step: 0.02, fmt: (v: number) => v.toFixed(2), kf: true },
                  ] as const
                ).map((row) => {
                  const keyed = row.kf && propKeyed(row.key as KfProp);
                  // 该属性在当前播放头进度处是否已有关键帧点——打下第一个点就点亮,不必等到两个点。
                  const onKf = keyed && propTimes(keyframes, row.key as KfProp).some((tt) => Math.abs(tt - progress) < 0.02);
                  return (
                    <div key={row.key} className="grid grid-cols-[52px_1fr_40px_20px] items-center gap-2">
                      <span className="text-ui-xs text-muted-foreground">{row.label}</span>
                      <Slider
                        // 值/进度入 key:改画幅、重置、或移动播放头(采样值变)后重挂非受控滑块。
                        key={`${row.key}-${selectedClip.id}-${shown[row.key].toFixed(3)}-${keyframes.length}`}
                        min={row.min}
                        max={row.max}
                        step={row.step}
                        defaultValue={[shown[row.key]]}
                        onValueCommit={([value]) => setProp(row.key as KfProp, value)}
                      />
                      <span className="timecode text-right text-ui-xs text-muted-foreground">{row.fmt(shown[row.key])}</span>
                      {row.kf ? (
                        <button
                          type="button"
                          title={onKf ? t("kfRemoveHere") : t("kfAddHere")}
                          aria-label={onKf ? t("kfRemoveHere") : t("kfAddHere")}
                          className={cn("grid h-5 w-5 cursor-pointer place-items-center rounded border-0 bg-transparent", onKf ? "text-primary" : keyed ? "text-muted-foreground hover:text-primary" : "text-muted-foreground/50 hover:text-primary")}
                          onClick={() => toggleProp(row.key as KfProp)}
                        >
                          <Diamond size={11} fill={onKf ? "currentColor" : "none"} />
                        </button>
                      ) : (
                        <span />
                      )}
                    </div>
                  );
                })}
                {/* 关键帧点总览:合并所有属性的时间点,点击跳转;每属性自己的钻石在上面各行。 */}
                {anyKeyframes && (
                  <div className="mt-0.5 flex flex-wrap items-center gap-1">
                    {[...new Set(keyframes.map((k) => k.t))].sort((a, b) => a - b).map((tt) => {
                      const near = Math.abs(tt - progress) < 0.02;
                      return (
                        <button
                          key={tt}
                          type="button"
                          title={`${Math.round(tt * 100)}%`}
                          className={cn("timecode cursor-pointer rounded-full border px-1.5 py-0.5 text-ui-2xs", near ? "border-primary bg-accent text-accent-foreground" : "border-border text-muted-foreground hover:border-primary")}
                          onClick={() => seekToKeyframe(tt)}
                        >
                          {Math.round(tt * 100)}%
                        </button>
                      );
                    })}
                  </div>
                )}
                <span className="text-ui-2xs leading-[1.4] text-muted-foreground">{anyKeyframes ? t("kfHintActive") : t("kfHintEmpty")}</span>
              </div>
            )}
          </div>
        )
      ) : (
        <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] content-start gap-1.5 overflow-y-auto overflow-x-hidden p-2.5 [&_dl]:m-0 [&_dl]:grid [&_dl]:grid-cols-[92px_minmax(0,1fr)] [&_dl]:gap-[9px] [&_dl]:text-xs [&_dt]:text-muted-foreground [&_dd]:m-0 [&_dd]:min-w-0">
          <dl>
            <dt>{t("sequence")}</dt>
            <dd>{sequence.name}</dd>
            <dt>{t("revision")}</dt>
            <dd className="timecode">{sequence.revision}</dd>
            <dt>{t("format")}</dt>
            <dd className="timecode">
              {sequence.width}×{sequence.height} · {sequence.fps}fps
            </dd>
          </dl>
          {onReframe && (
            <div className="grid gap-1.5 border-t border-border pt-2.5">
              <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t("reframeTitle")}</span>
              <div className="flex flex-wrap gap-1">
                {(
                  [
                    { label: "16:9", w: 1920, h: 1080 },
                    { label: "9:16", w: 1080, h: 1920 },
                    { label: "1:1", w: 1080, h: 1080 },
                    { label: "4:5", w: 1080, h: 1350 },
                  ] as const
                ).map((preset) => {
                  const fill = (sequence.reframe as { fill_mode?: string })?.fill_mode ?? "cover";
                  return (
                    <button
                      key={preset.label}
                      type="button"
                      className={cn("min-w-[34px] cursor-pointer rounded-md border border-border bg-panel px-1.5 py-1 text-xs text-muted-foreground transition-[border-color,color,background-color] duration-100 hover:border-border-strong hover:text-foreground", sequence.width === preset.w && sequence.height === preset.h && "border-primary bg-accent text-accent-foreground hover:border-primary hover:text-accent-foreground")}
                      onClick={() => onReframe(preset.w, preset.h, fill)}
                    >
                      {preset.label}
                    </button>
                  );
                })}
              </div>
              <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t("reframeFill")}</span>
              <div className="flex flex-wrap gap-1">
                {(
                  [
                    { key: "cover", label: t("fillCover") },
                    { key: "contain", label: t("fillContain") },
                    { key: "blur", label: t("fillBlur") },
                  ] as const
                ).map((mode) => {
                  const fill = (sequence.reframe as { fill_mode?: string })?.fill_mode ?? "cover";
                  return (
                    <button
                      key={mode.key}
                      type="button"
                      className={cn("min-w-[34px] cursor-pointer rounded-md border border-border bg-panel px-1.5 py-1 text-xs text-muted-foreground transition-[border-color,color,background-color] duration-100 hover:border-border-strong hover:text-foreground", fill === mode.key && "border-primary bg-accent text-accent-foreground hover:border-primary hover:text-accent-foreground")}
                      onClick={() => onReframe(sequence.width, sequence.height, mode.key)}
                    >
                      {mode.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <p className="m-0 border-t border-border pt-2.5 text-xs text-muted-foreground">{t("noSelection")}</p>
        </div>
      )}
    </section>
  );
}

/**
 * 调色独立面板(沿用前身项目 color-panel 的形态):作用对象标注 +
 * 风格预设 + 分组滑杆 + 重置。只作用于选中的片段。
 */
function ColorGradePanel({
  clip,
  workspaceId,
  targetName,
  effects,
  onSetEffects,
}: {
  clip: Clip;
  workspaceId: string;
  targetName: string;
  effects: { filter?: string; color?: Partial<Record<GradeKey, number>> };
  onSetEffects: (clipId: string, effects: Record<string, unknown>) => void;
}) {
  const t = useI18n();
  const grade = Object.fromEntries(
    GRADE_KEYS.map((key) => [key, Number((effects.color as Record<string, number> | undefined)?.[key]) || 0]),
  ) as Record<GradeKey, number>;
  const curColor = (effects.color ?? {}) as Record<string, unknown>;
  const hasGrade =
    GRADE_KEYS.some((key) => grade[key]) ||
    Boolean(effects.filter) ||
    Boolean(curColor.curves) ||
    Boolean(curColor.lut);
  // 预设高亮:滤镜与调色预设互斥,滤镜在时不高亮任一调色预设。
  const activePreset = effects.filter ? null : matchColorPreset(curColor);
  const isCleanColor =
    !effects.filter && !curColor.curves && !curColor.lut && !GRADE_KEYS.some((key) => grade[key]);

  // 调色不再有自己的撤销栈,统一走时间线的 ⌘Z。
  //
  // 那套栈的 undo 只是"再发一次 setEffects",而每次 setEffects 都会在服务端记一条
  // set_clip_effect —— 于是它撤销的动作本身又往全局栈里压了一条。实测三次试色 + 三次
  // 面板撤销 = 全局栈 6 条,用户想回到调色之前要按 6 次 ⌘Z,其中 3 次是在撤销自己的撤销。
  // 同一份状态上架两套栈就会这样;滑杆本来就是松手提交一次,全局栈的颗粒度已经够用。
  const applyPreset = (payload: Record<string, unknown> | null) => {
    const next = { ...clip.effects } as Record<string, unknown>;
    delete next.filter; // 调色预设是唯一真源,清掉遗留的 CSS 滤镜
    if (payload) {
      // 预设换的是主校正(滑杆 + 曲线),保留用户已选的创意 LUT。
      next.color = curColor.lut ? { ...payload, lut: curColor.lut } : payload;
    } else {
      delete next.color;
    }
    onSetEffects(clip.id, next);
  };
  const applyGrade = (key: GradeKey, raw: string) => {
    const value = Math.max(-1, Math.min(1, Number(raw) / 100));
    // 从完整 color 展开,保住 curves 等非滑杆字段。
    onSetEffects(clip.id, { ...clip.effects, color: { ...curColor, [key]: value } });
  };
  const resetAll = () => {
    const next = { ...clip.effects } as Record<string, unknown>;
    delete next.color;
    delete next.filter;
    onSetEffects(clip.id, next);
  };
  const setLut = (lutId: string | undefined) => {
    const nextColor = { ...curColor };
    if (lutId) nextColor.lut = lutId;
    else delete nextColor.lut;
    onSetEffects(clip.id, { ...clip.effects, color: nextColor });
  };

  return (
    <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] content-start gap-1.5 overflow-y-auto overflow-x-hidden p-2.5">
      <div className="flex items-center gap-1.5 border-b border-border pb-0.5 text-xs text-muted-foreground [&_strong]:min-w-0 [&_strong]:flex-1 [&_strong]:truncate [&_strong]:font-semibold [&_strong]:text-foreground">
        <span>{t("colorTarget")}</span>
        <strong title={targetName}>{targetName}</strong>
        <div className="inline-flex items-center gap-1">
          {hasGrade && (
            <button type="button" className="inline-flex cursor-pointer items-center gap-[3px] whitespace-nowrap border-0 bg-transparent p-0 text-ui-xs text-muted-foreground hover:text-destructive" onClick={resetAll} title={t("gradeResetAllHint")}>
              <RotateCcw size={11} /> {t("gradeReset")}
            </button>
          )}
        </div>
      </div>
      <div className="grid gap-1.5 border-t border-border pt-2.5">
        <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t("stylePresets")}</span>
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            className={cn("min-w-[34px] cursor-pointer rounded-md border border-border bg-panel px-1.5 py-1 text-xs text-muted-foreground transition-[border-color,color,background-color] duration-100 hover:border-border-strong hover:text-foreground", isCleanColor && "border-primary bg-accent text-accent-foreground hover:border-primary hover:text-accent-foreground")}
            title={t("colorPresetHint")}
            onClick={() => applyPreset(null)}
          >
            {t("colorPreset_none")}
          </button>
          {COLOR_PRESETS.map((preset) => (
            <button
              key={preset.key}
              type="button"
              className={cn("min-w-[34px] cursor-pointer rounded-md border border-border bg-panel px-1.5 py-1 text-xs text-muted-foreground transition-[border-color,color,background-color] duration-100 hover:border-border-strong hover:text-foreground", activePreset === preset.key && "border-primary bg-accent text-accent-foreground hover:border-primary hover:text-accent-foreground")}
              title={t("colorPresetHint")}
              onClick={() => applyPreset(presetColorPayload(preset))}
            >
              {t(`colorPreset_${preset.key}` as never)}
            </button>
          ))}
        </div>
      </div>
      {GRADE_GROUPS.map((group) => (
        <div className="grid gap-1.5 border-t border-border pt-2.5" key={group.label}>
          <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t(group.label as never)}</span>
          {group.keys.map((key) => (
            <div className="grid grid-cols-[44px_minmax(0,1fr)_30px] items-center gap-1.5 text-ui-xs text-muted-foreground [&_em]:text-right [&_em]:text-ui-2xs [&_em]:not-italic" key={`${key}-${clip.id}`}>
              <span>{t(`grade_${key}` as never)}</span>
              <Slider
                // 值入 key:套预设后重挂,让非受控滑杆的滑块跳到预设值。
                key={`${key}-${clip.id}-${Math.round((grade[key] ?? 0) * 100)}`}
                min={POSITIVE_ONLY.has(key) ? 0 : -100}
                max={100}
                step={5}
                defaultValue={[Math.round((grade[key] ?? 0) * 100)]}
                onValueCommit={([value]) => applyGrade(key, String(value))}
                aria-label={t(`grade_${key}` as never)}
              />
              <em className="timecode">{Math.round((grade[key] ?? 0) * 100)}</em>
            </div>
          ))}
        </div>
      ))}
      <div className="grid gap-1.5 border-t border-border pt-2.5">
        <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t("gradeGroupCurves")}</span>
        <CurveEditor
          key={clip.id}
          curves={curColor.curves as ColorCurves | undefined}
          onChange={(next) =>
            onSetEffects(clip.id, { ...clip.effects, color: { ...curColor, curves: next } })
          }
        />
      </div>
      <div className="grid gap-1.5 border-t border-border pt-2.5">
        <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t("gradeGroupLut")}</span>
        <LutPicker workspaceId={workspaceId} value={curColor.lut as string | undefined} onChange={setLut} />
      </div>
      <p className="mb-0 mt-1 text-ui-xs leading-normal text-muted-foreground">{t("colorScopeHint")}</p>
    </div>
  );
}

/** 上传字体与内置字体栈在同一个 Select 里的区分前缀(与字幕同源)。 */
const FONT_UPLOAD_PREFIX = "upload:";

/**
 * 花字文字样式面板:字体(内置栈 + 上传字体,shadcn Select)、字号、颜色/描边、阴影、粗斜、对齐,
 * 以及一键花字预设。写入 clip.effects.text_style,与预览 textStyleCss、导出 ASS 锁步同一套字段。
 * 字体机制复用字幕:内置 SUBTITLE_FONTS + 工作区上传字体(font_id),预览由 FontFaces 注入 @font-face。
 */
function TextStylePanel({
  clip,
  onSetEffects,
  fonts,
  onUploadFont,
  onDeleteFont,
  uploadingFont,
}: {
  clip: Clip;
  onSetEffects: (clipId: string, effects: Record<string, unknown>) => void;
  fonts: Font[];
  onUploadFont?: (file: File) => void;
  onDeleteFont?: (fontId: string) => void;
  uploadingFont?: boolean;
}) {
  const t = useI18n();
  const fileRef = React.useRef<HTMLInputElement | null>(null);
  const style = readTextStyle((clip.effects as { text_style?: unknown } | undefined)?.text_style);
  const set = (patch: Partial<TextStyle>) =>
    onSetEffects(clip.id, { ...clip.effects, text_style: { ...style, ...patch } });
  const iconBtn = (active: boolean) =>
    cn(
      "grid h-6 min-w-[30px] cursor-pointer place-items-center rounded-md border border-border bg-panel px-1.5 text-xs text-muted-foreground transition-[border-color,color,background-color] duration-100 hover:border-border-strong hover:text-foreground",
      active && "border-primary bg-accent text-accent-foreground hover:border-primary hover:text-accent-foreground",
    );
  const swatch =
    "h-6 w-9 shrink-0 cursor-pointer rounded-md border border-input bg-transparent p-0.5 [&::-webkit-color-swatch]:rounded [&::-webkit-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-0";
  const bars: Array<{ key: "stroke_width" | "shadow"; label: string }> = [
    { key: "stroke_width", label: t("textStroke") },
    { key: "shadow", label: t("textShadow") },
  ];
  return (
    <div className="grid gap-2 border-t border-border pt-2.5">
      <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t("textStyleTitle")}</span>
      <div className="flex flex-wrap gap-1">
        {TEXT_PRESETS.map((preset) => (
          <button key={preset.key} type="button" className={iconBtn(false)} onClick={() => set(preset.style)}>
            {preset.label}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-[40px_1fr] items-center gap-2">
        <span className="text-ui-xs text-muted-foreground">{t("textFont")}</span>
        <Select
          value={style.font_id ? `${FONT_UPLOAD_PREFIX}${style.font_id}` : style.font_family}
          onValueChange={(value) => {
            if (!value.startsWith(FONT_UPLOAD_PREFIX)) {
              set({ font_family: value, font_id: "" });
              return;
            }
            const id = value.slice(FONT_UPLOAD_PREFIX.length);
            const picked = fonts.find((font) => font.id === id);
            if (picked) set({ font_id: id, font_family: uploadedFontStack(picked.family) });
          }}
        >
          <SelectTrigger className="h-[26px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SUBTITLE_FONTS.map((font) => (
              <SelectItem key={font.value} value={font.value} style={{ fontFamily: font.value }}>
                {t(font.labelKey as Parameters<typeof t>[0])}
              </SelectItem>
            ))}
            {fonts.map((font) => (
              <SelectItem key={font.id} value={`${FONT_UPLOAD_PREFIX}${font.id}`} style={{ fontFamily: uploadedFontStack(font.family) }}>
                {font.family}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {onUploadFont && (
        <div className="flex items-center gap-1 pl-[48px]">
          <Button variant="ghost" size="sm" className="h-6 px-1.5 text-ui-xs" disabled={uploadingFont} onClick={() => fileRef.current?.click()}>
            {uploadingFont ? <Loader2 size={12} className="animate-mosael-spin" /> : <Upload size={12} />} {t("subFontUpload")}
          </Button>
          {style.font_id && onDeleteFont && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-ui-xs"
              onClick={() => {
                const removing = style.font_id;
                set({ font_id: "", font_family: SUBTITLE_FONTS[0].value });
                onDeleteFont(removing);
              }}
            >
              <Trash2 size={12} /> {t("subFontRemove")}
            </Button>
          )}
          <input
            ref={fileRef}
            type="file"
            accept=".ttf,.otf,.ttc,.otc"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onUploadFont(file);
              event.target.value = "";
            }}
          />
        </div>
      )}
      <div className="grid grid-cols-[40px_1fr_34px] items-center gap-2">
        <span className="text-ui-xs text-muted-foreground">{t("textSize")}</span>
        <Slider
          key={`fs-${clip.id}-${Math.round(style.font_size)}`}
          min={12}
          max={200}
          step={2}
          defaultValue={[style.font_size]}
          onValueCommit={([value]) => set({ font_size: value })}
        />
        <span className="timecode text-right text-ui-xs text-muted-foreground">{Math.round(style.font_size)}</span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex items-center justify-between gap-1.5 text-ui-xs text-muted-foreground">
          {t("textColor")}
          <input type="color" className={swatch} value={style.color} onChange={(event) => set({ color: event.target.value })} />
        </label>
        <label className="flex items-center justify-between gap-1.5 text-ui-xs text-muted-foreground">
          {t("textStrokeColor")}
          <input type="color" className={swatch} value={style.stroke_color} onChange={(event) => set({ stroke_color: event.target.value })} />
        </label>
      </div>
      {bars.map((bar) => (
        <div key={bar.key} className="grid grid-cols-[40px_1fr_34px] items-center gap-2">
          <span className="text-ui-xs text-muted-foreground">{bar.label}</span>
          <Slider
            key={`${bar.key}-${clip.id}-${style[bar.key]}`}
            min={0}
            max={20}
            step={1}
            defaultValue={[style[bar.key]]}
            onValueCommit={([value]) => set({ [bar.key]: value } as Partial<TextStyle>)}
          />
          <span className="timecode text-right text-ui-xs text-muted-foreground">{Math.round(style[bar.key])}</span>
        </div>
      ))}
      <div className="flex items-center gap-1">
        <button type="button" className={iconBtn(style.bold)} onClick={() => set({ bold: !style.bold })} aria-label={t("textBold")}>
          <Bold size={13} />
        </button>
        <button type="button" className={iconBtn(style.italic)} onClick={() => set({ italic: !style.italic })} aria-label={t("textItalic")}>
          <Italic size={13} />
        </button>
        <span className="mx-0.5 h-4 w-px bg-border" />
        {([["left", AlignLeft], ["center", AlignCenter], ["right", AlignRight]] as const).map(([align, Icon]) => (
          <button key={align} type="button" className={iconBtn(style.align === align)} onClick={() => set({ align })} aria-label={`align-${align}`}>
            <Icon size={13} />
          </button>
        ))}
      </div>
    </div>
  );
}
