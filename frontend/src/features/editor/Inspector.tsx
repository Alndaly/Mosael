import React from "react";
import { Redo2, RotateCcw, Trash2, Undo2, X } from "lucide-react";

import type { Asset, Clip, Sequence } from "@/api/client";
import { Slider } from "@/components/ui/slider";
import { useI18n } from "@/app/preferences";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";
import { CurveEditor } from "@/features/editor/CurveEditor";
import type { ColorCurves } from "@/features/editor/colorCurves";
import { COLOR_PRESETS, matchColorPreset, presetColorPayload } from "@/features/editor/colorPresets";
import { useColorHistory } from "@/features/editor/useColorHistory";
import { LutPicker } from "@/features/editor/LutPicker";

const PIP_POSITIONS: Array<{ key: string; x: number; y: number }> = [
  { key: "↖", x: 0.05, y: 0.06 },
  { key: "↗", x: 0.62, y: 0.06 },
  { key: "↙", x: 0.05, y: 0.6 },
  { key: "↘", x: 0.62, y: 0.6 },
];
const PIP_SIZES = [0.25, 0.33, 0.5];
const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2];

/** mibu-video 调色面板的完整参数集,按老版分组呈现。 */
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

export function Inspector({
  sequence,
  workspaceId,
  selectedClip,
  assets,
  isOverlayClip,
  onDeleteClip,
  onSetEffects,
  onSetTransform,
  onReframe,
  onSetSpeed,
  onSetText,
  onClose,
}: {
  sequence: Sequence;
  workspaceId: string;
  selectedClip: Clip | null;
  assets: Asset[];
  isOverlayClip: boolean;
  onDeleteClip: (clipId: string) => void;
  onSetEffects: (clipId: string, effects: Record<string, unknown>) => void;
  onSetTransform?: (clipId: string, transform: Record<string, number>) => void;
  onReframe?: (width: number, height: number, fillMode: string) => void;
  onSetSpeed?: (clipId: string, speed: number) => void;
  onSetText?: (clipId: string, text: string) => void;
  /** 紧凑模式抽屉需要显式关闭入口(桌面三栏布局不传)。 */
  onClose?: () => void;
}) {
  const t = useI18n();
  const [tab, setTab] = React.useState<"props" | "color">("props");
  const asset = selectedClip?.asset_id ? assets.find((item) => item.id === selectedClip.asset_id) : null;
  const isTextClip = Boolean(selectedClip && !selectedClip.asset_id && selectedClip.text_override != null);
  const effects = (selectedClip?.effects ?? {}) as {
    fade_in?: number;
    fade_out?: number;
    filter?: string;
    color?: Partial<Record<GradeKey, number>>;
  };

  const applyFade = (key: "fade_in" | "fade_out", raw: string) => {
    if (!selectedClip) return;
    const value = Math.max(0, Number(raw) || 0);
    onSetEffects(selectedClip.id, { ...selectedClip.effects, [key]: value });
  };
  const pip = {
    x: 0.62,
    y: 0.06,
    scale: 0.33,
    ...(((selectedClip?.effects as { pip?: { x?: number; y?: number; scale?: number } })?.pip) ?? {}),
  };
  const applyPip = (patch: Partial<typeof pip>) => {
    if (!selectedClip) return;
    onSetEffects(selectedClip.id, { ...selectedClip.effects, pip: { ...pip, ...patch } });
  };

  const transform = {
    scale: 1,
    x: 0,
    y: 0,
    rotation: 0,
    opacity: 1,
    ...((selectedClip?.transform as Record<string, number>) ?? {}),
  };
  const applyTransform = (patch: Partial<typeof transform>) => {
    if (!selectedClip || !onSetTransform) return;
    onSetTransform(selectedClip.id, { ...transform, ...patch });
  };
  const isIdentityTransform =
    transform.scale === 1 && transform.x === 0 && transform.y === 0 && transform.rotation === 0 && transform.opacity === 1;

  // 字幕片段没有调色;切换选中对象时回到属性页。
  React.useEffect(() => {
    if (isTextClip) setTab("props");
  }, [selectedClip?.id, isTextClip]);

  return (
    <section className="panel inspector">
      <div className="panel-head">
        {selectedClip && !isTextClip ? (
          <div className="seg" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "props"}
              className={tab === "props" ? "seg-btn active" : "seg-btn"}
              onClick={() => setTab("props")}
            >
              {t("inspectorProps")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "color"}
              className={tab === "color" ? "seg-btn active" : "seg-btn"}
              onClick={() => setTab("color")}
            >
              {t("colorGrade")}
            </button>
          </div>
        ) : (
          <h2>{t("inspector")}</h2>
        )}
        <div className="inspector-head-tools">
          {selectedClip && (
            <button
              type="button"
              className="inspector-delete"
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
              className="inspector-delete inspector-close"
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
          <div className="inspector-body">
            <dl>
              <dt>{t("asset")}</dt>
              <dd className="inspector-ellipsis" title={asset?.name}>
                {asset?.name ?? selectedClip.asset_id?.slice(0, 8) ?? t("subtitleText")}
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
              <dt>{t("gain")}</dt>
              <dd className="timecode">{selectedClip.gain.toFixed(2)}</dd>
            </dl>
            {isTextClip && onSetText && (
              <div className="pip-controls">
                <span className="pip-label">{t("subtitleText")}</span>
                <textarea
                  key={`text-${selectedClip.id}`}
                  className="subtitle-input"
                  rows={3}
                  defaultValue={selectedClip.text_override ?? ""}
                  onBlur={(event) => {
                    const value = event.target.value.trim();
                    if (value && value !== selectedClip.text_override) onSetText(selectedClip.id, value);
                  }}
                />
              </div>
            )}
            {!isTextClip && onSetSpeed && (
              <div className="pip-controls">
                <span className="pip-label">{t("speed")}</span>
                <div className="pip-row">
                  {SPEED_OPTIONS.map((option) => (
                    <button
                      key={option}
                      type="button"
                      className={Math.abs(selectedClip.speed - option) < 0.001 ? "pip-btn active" : "pip-btn"}
                      onClick={() => onSetSpeed(selectedClip.id, option)}
                    >
                      {option}x
                    </button>
                  ))}
                </div>
              </div>
            )}
            {!isTextClip && (
              <div className="pip-controls">
                <span className="pip-label">{t("fadeIn")}</span>
                <input
                  key={`fi-${selectedClip.id}`}
                  className="fade-input"
                  type="number"
                  min={0}
                  step={0.1}
                  defaultValue={effects.fade_in ?? 0}
                  onBlur={(event) => applyFade("fade_in", event.target.value)}
                />
                <span className="pip-label">{t("fadeOut")}</span>
                <input
                  key={`fo-${selectedClip.id}`}
                  className="fade-input"
                  type="number"
                  min={0}
                  step={0.1}
                  defaultValue={effects.fade_out ?? 0}
                  onBlur={(event) => applyFade("fade_out", event.target.value)}
                />
              </div>
            )}
            {!isTextClip && onSetTransform && (
              <div className="pip-controls transform-controls">
                <div className="transform-head">
                  <span className="pip-label">{t("transformTitle")}</span>
                  {!isIdentityTransform && (
                    <button
                      type="button"
                      className="transform-reset"
                      onClick={() => applyTransform({ scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 })}
                    >
                      {t("transformReset")}
                    </button>
                  )}
                </div>
                {(
                  [
                    { key: "scale", label: t("transformScale"), min: 0.1, max: 4, step: 0.05, fmt: (v: number) => `${Math.round(v * 100)}%` },
                    { key: "rotation", label: t("transformRotation"), min: -180, max: 180, step: 1, fmt: (v: number) => `${Math.round(v)}°` },
                    { key: "opacity", label: t("transformOpacity"), min: 0, max: 1, step: 0.05, fmt: (v: number) => `${Math.round(v * 100)}%` },
                    { key: "x", label: t("transformPosX"), min: -1, max: 1, step: 0.02, fmt: (v: number) => v.toFixed(2) },
                    { key: "y", label: t("transformPosY"), min: -1, max: 1, step: 0.02, fmt: (v: number) => v.toFixed(2) },
                  ] as const
                ).map((row) => (
                  <label key={row.key} className="transform-row">
                    <span className="transform-row-label">{row.label}</span>
                    <input
                      key={`${row.key}-${selectedClip.id}-${transform[row.key]}`}
                      type="range"
                      min={row.min}
                      max={row.max}
                      step={row.step}
                      defaultValue={transform[row.key]}
                      onPointerUp={(event) => applyTransform({ [row.key]: Number((event.target as HTMLInputElement).value) })}
                      onKeyUp={(event) => applyTransform({ [row.key]: Number((event.target as HTMLInputElement).value) })}
                    />
                    <span className="transform-row-value timecode">{row.fmt(transform[row.key])}</span>
                  </label>
                ))}
              </div>
            )}
            {isOverlayClip && (
              <div className="pip-controls">
                <span className="pip-label">{t("pipPosition")}</span>
                <div className="pip-row">
                  {PIP_POSITIONS.map((position) => (
                    <button
                      key={position.key}
                      type="button"
                      className={
                        Math.abs(pip.x - position.x) < 0.01 && Math.abs(pip.y - position.y) < 0.01
                          ? "pip-btn active"
                          : "pip-btn"
                      }
                      onClick={() => applyPip({ x: position.x, y: position.y })}
                    >
                      {position.key}
                    </button>
                  ))}
                </div>
                <span className="pip-label">{t("pipSize")}</span>
                <div className="pip-row">
                  {PIP_SIZES.map((size) => (
                    <button
                      key={size}
                      type="button"
                      className={Math.abs(pip.scale - size) < 0.01 ? "pip-btn active" : "pip-btn"}
                      onClick={() => applyPip({ scale: size })}
                    >
                      {Math.round(size * 100)}%
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )
      ) : (
        <div className="inspector-body">
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
            <div className="pip-controls">
              <span className="pip-label">{t("reframeTitle")}</span>
              <div className="pip-row">
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
                      className={sequence.width === preset.w && sequence.height === preset.h ? "pip-btn active" : "pip-btn"}
                      onClick={() => onReframe(preset.w, preset.h, fill)}
                    >
                      {preset.label}
                    </button>
                  );
                })}
              </div>
              <span className="pip-label">{t("reframeFill")}</span>
              <div className="pip-row">
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
                      className={fill === mode.key ? "pip-btn active" : "pip-btn"}
                      onClick={() => onReframe(sequence.width, sequence.height, mode.key)}
                    >
                      {mode.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <p className="inspector-hint">{t("noSelection")}</p>
        </div>
      )}
    </section>
  );
}

/**
 * 调色独立面板(老版 mibu-video color-panel 的形态):作用对象标注 +
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

  // 调色独立撤销栈:按 clip 存快照(color+filter),每次编辑前记一步。与时间线全局
  // 撤销无关 —— 撤销只是再发一次 setEffects,方便反复试色。
  const history = useColorHistory(clip.id, clip.effects, onSetEffects);
  const applyPreset = (payload: Record<string, unknown> | null) => {
    history.snapshot();
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
    history.snapshot();
    const value = Math.max(-1, Math.min(1, Number(raw) / 100));
    // 从完整 color 展开,保住 curves 等非滑杆字段。
    onSetEffects(clip.id, { ...clip.effects, color: { ...curColor, [key]: value } });
  };
  const resetAll = () => {
    history.snapshot();
    const next = { ...clip.effects } as Record<string, unknown>;
    delete next.color;
    delete next.filter;
    onSetEffects(clip.id, next);
  };
  const setLut = (lutId: string | undefined) => {
    history.snapshot();
    const nextColor = { ...curColor };
    if (lutId) nextColor.lut = lutId;
    else delete nextColor.lut;
    onSetEffects(clip.id, { ...clip.effects, color: nextColor });
  };

  return (
    <div className="inspector-body color-panel">
      <div className="color-target">
        <span>{t("colorTarget")}</span>
        <strong title={targetName}>{targetName}</strong>
        <div className="color-actions">
          <button
            type="button"
            className="grade-icon-btn"
            onClick={history.undo}
            disabled={!history.canUndo}
            title={t("colorUndo")}
            aria-label={t("colorUndo")}
          >
            <Undo2 size={12} />
          </button>
          <button
            type="button"
            className="grade-icon-btn"
            onClick={history.redo}
            disabled={!history.canRedo}
            title={t("colorRedo")}
            aria-label={t("colorRedo")}
          >
            <Redo2 size={12} />
          </button>
          {hasGrade && (
            <button type="button" className="grade-reset" onClick={resetAll} title={t("gradeResetAllHint")}>
              <RotateCcw size={11} /> {t("gradeReset")}
            </button>
          )}
        </div>
      </div>
      <div className="pip-controls">
        <span className="pip-label">{t("stylePresets")}</span>
        <div className="pip-row color-presets">
          <button
            type="button"
            className={isCleanColor ? "pip-btn active" : "pip-btn"}
            title={t("colorPresetHint")}
            onClick={() => applyPreset(null)}
          >
            {t("colorPreset_none")}
          </button>
          {COLOR_PRESETS.map((preset) => (
            <button
              key={preset.key}
              type="button"
              className={activePreset === preset.key ? "pip-btn active" : "pip-btn"}
              title={t("colorPresetHint")}
              onClick={() => applyPreset(presetColorPayload(preset))}
            >
              {t(`colorPreset_${preset.key}` as never)}
            </button>
          ))}
        </div>
      </div>
      {GRADE_GROUPS.map((group) => (
        <div className="pip-controls" key={group.label}>
          <span className="pip-label">{t(group.label as never)}</span>
          {group.keys.map((key) => (
            <div className="grade-slider" key={`${key}-${clip.id}`}>
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
      <div className="pip-controls">
        <span className="pip-label">{t("gradeGroupCurves")}</span>
        <CurveEditor
          key={clip.id}
          curves={curColor.curves as ColorCurves | undefined}
          onCommitStart={history.snapshot}
          onChange={(next) =>
            onSetEffects(clip.id, { ...clip.effects, color: { ...curColor, curves: next } })
          }
        />
      </div>
      <div className="pip-controls">
        <span className="pip-label">{t("gradeGroupLut")}</span>
        <LutPicker workspaceId={workspaceId} value={curColor.lut as string | undefined} onChange={setLut} />
      </div>
      <p className="color-hint">{t("colorScopeHint")}</p>
    </div>
  );
}
