import React from "react";
import { RotateCcw, Trash2 } from "lucide-react";

import type { Asset, Clip, Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";

const PIP_POSITIONS: Array<{ key: string; x: number; y: number }> = [
  { key: "↖", x: 0.05, y: 0.06 },
  { key: "↗", x: 0.62, y: 0.06 },
  { key: "↙", x: 0.05, y: 0.6 },
  { key: "↘", x: 0.62, y: 0.6 },
];
const PIP_SIZES = [0.25, 0.33, 0.5];
const SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const FILTER_PRESETS = ["", "bw", "warm", "cool", "vivid", "fade"] as const;

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
  selectedClip,
  assets,
  isOverlayClip,
  onDeleteClip,
  onSetEffects,
  onSetSpeed,
  onSetText,
}: {
  sequence: Sequence;
  selectedClip: Clip | null;
  assets: Asset[];
  isOverlayClip: boolean;
  onDeleteClip: (clipId: string) => void;
  onSetEffects: (clipId: string, effects: Record<string, unknown>) => void;
  onSetSpeed?: (clipId: string, speed: number) => void;
  onSetText?: (clipId: string, text: string) => void;
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
      </div>
      {selectedClip ? (
        tab === "color" && !isTextClip ? (
          <ColorGradePanel
            clip={selectedClip}
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
  targetName,
  effects,
  onSetEffects,
}: {
  clip: Clip;
  targetName: string;
  effects: { filter?: string; color?: Partial<Record<GradeKey, number>> };
  onSetEffects: (clipId: string, effects: Record<string, unknown>) => void;
}) {
  const t = useI18n();
  const grade = Object.fromEntries(
    GRADE_KEYS.map((key) => [key, Number((effects.color as Record<string, number> | undefined)?.[key]) || 0]),
  ) as Record<GradeKey, number>;
  const hasGrade = GRADE_KEYS.some((key) => grade[key]) || Boolean(effects.filter);
  const applyGrade = (key: GradeKey, raw: string) => {
    const value = Math.max(-1, Math.min(1, Number(raw) / 100));
    onSetEffects(clip.id, { ...clip.effects, color: { ...grade, [key]: value } });
  };
  const resetAll = () => {
    const next = { ...clip.effects } as Record<string, unknown>;
    delete next.color;
    delete next.filter;
    onSetEffects(clip.id, next);
  };

  return (
    <div className="inspector-body color-panel">
      <div className="color-target">
        <span>{t("colorTarget")}</span>
        <strong title={targetName}>{targetName}</strong>
        {hasGrade && (
          <button type="button" className="grade-reset" onClick={resetAll} title={t("gradeResetAllHint")}>
            <RotateCcw size={11} /> {t("gradeReset")}
          </button>
        )}
      </div>
      <div className="pip-controls">
        <span className="pip-label">{t("stylePresets")}</span>
        <div className="pip-row color-presets">
          {FILTER_PRESETS.map((preset) => (
            <button
              key={preset || "none"}
              type="button"
              className={(effects.filter ?? "") === preset ? "pip-btn active" : "pip-btn"}
              title={t("filterPresetHint")}
              onClick={() => onSetEffects(clip.id, { ...clip.effects, filter: preset || undefined })}
            >
              {t(preset ? (`filter_${preset}` as never) : ("filter_none" as never))}
            </button>
          ))}
        </div>
      </div>
      {GRADE_GROUPS.map((group) => (
        <div className="pip-controls" key={group.label}>
          <span className="pip-label">{t(group.label as never)}</span>
          {group.keys.map((key) => (
            <label className="grade-slider" key={`${key}-${clip.id}`}>
              <span>{t(`grade_${key}` as never)}</span>
              <input
                type="range"
                min={POSITIVE_ONLY.has(key) ? 0 : -100}
                max={100}
                step={5}
                defaultValue={Math.round((grade[key] ?? 0) * 100)}
                onPointerUp={(event) => applyGrade(key, (event.target as HTMLInputElement).value)}
                onKeyUp={(event) => applyGrade(key, (event.target as HTMLInputElement).value)}
                aria-label={t(`grade_${key}` as never)}
              />
              <em className="timecode">{Math.round((grade[key] ?? 0) * 100)}</em>
            </label>
          ))}
        </div>
      ))}
      <p className="color-hint">{t("colorScopeHint")}</p>
    </div>
  );
}
