import { Trash2 } from "lucide-react";

import type { Asset, Clip, Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
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
  const asset = selectedClip?.asset_id ? assets.find((item) => item.id === selectedClip.asset_id) : null;
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
  const isTextClip = Boolean(selectedClip && !selectedClip.asset_id && selectedClip.text_override != null);
  const effects = (selectedClip?.effects ?? {}) as {
    fade_in?: number;
    fade_out?: number;
    filter?: string;
    color?: { brightness?: number; contrast?: number; saturation?: number };
  };
  const grade = { brightness: 0, contrast: 0, saturation: 0, ...(effects.color ?? {}) };
  const hasGrade = Boolean(grade.brightness || grade.contrast || grade.saturation);
  const applyGrade = (key: "brightness" | "contrast" | "saturation", raw: string) => {
    if (!selectedClip) return;
    const value = Math.max(-1, Math.min(1, Number(raw) / 100));
    onSetEffects(selectedClip.id, { ...selectedClip.effects, color: { ...grade, [key]: value } });
  };
  const resetGrade = () => {
    if (!selectedClip) return;
    const next = { ...selectedClip.effects } as Record<string, unknown>;
    delete next.color;
    onSetEffects(selectedClip.id, next);
  };
  const applyFade = (key: "fade_in" | "fade_out", raw: string) => {
    if (!selectedClip) return;
    const value = Math.max(0, Number(raw) || 0);
    onSetEffects(selectedClip.id, { ...selectedClip.effects, [key]: value });
  };

  return (
    <section className="panel inspector">
      <div className="panel-head">
        <h2>{t("inspector")}</h2>
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
        <div className="inspector-body">
          <dl>
            <dt>{t("asset")}</dt>
            <dd className="inspector-ellipsis" title={asset?.name}>{asset?.name ?? selectedClip.asset_id?.slice(0, 8) ?? t("subtitleText")}</dd>
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
          {!isTextClip && (
            <div className="pip-controls">
              <div className="grade-head">
                <span className="pip-label">{t("colorGrade")}</span>
                {hasGrade && (
                  <button type="button" className="grade-reset" onClick={resetGrade}>
                    {t("gradeReset")}
                  </button>
                )}
              </div>
              <div className="pip-row">
                {FILTER_PRESETS.map((preset) => (
                  <button
                    key={preset || "none"}
                    type="button"
                    className={(effects.filter ?? "") === preset ? "pip-btn active" : "pip-btn"}
                    title={t("filterPresetHint")}
                    onClick={() =>
                      onSetEffects(selectedClip.id, { ...selectedClip.effects, filter: preset || undefined })
                    }
                  >
                    {t(preset ? (`filter_${preset}` as never) : ("filter_none" as never))}
                  </button>
                ))}
              </div>
              {(
                [
                  ["brightness", t("gradeBrightness")],
                  ["contrast", t("gradeContrast")],
                  ["saturation", t("gradeSaturation")],
                ] as const
              ).map(([key, label]) => (
                <label className="grade-slider" key={`${key}-${selectedClip.id}`}>
                  <span>{label}</span>
                  <input
                    type="range"
                    min={-100}
                    max={100}
                    step={5}
                    defaultValue={Math.round((grade[key] ?? 0) * 100)}
                    onPointerUp={(event) => applyGrade(key, (event.target as HTMLInputElement).value)}
                    onKeyUp={(event) => applyGrade(key, (event.target as HTMLInputElement).value)}
                    aria-label={label}
                  />
                  <em className="timecode">{Math.round((grade[key] ?? 0) * 100)}</em>
                </label>
              ))}
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
