import React from "react";

import type { Clip } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Slider } from "@/components/ui/slider";
import {
  clipAppearancePayload,
  readClipAppearance,
  type ClipAppearance,
  type MaskShape,
} from "@/features/editor/clipAppearance";
import { cn } from "@/lib/utils";

export function ClipAppearancePanel({
  clip,
  onSetEffects,
}: {
  clip: Clip;
  onSetEffects: (clipId: string, effects: Record<string, unknown>) => void;
}) {
  const t = useI18n();
  const [appearance, setDraft] = React.useState<ClipAppearance>(() => readClipAppearance(clip.effects));
  React.useEffect(() => setDraft(readClipAppearance(clip.effects)), [clip.id, clip.effects]);

  const commit = (next: ClipAppearance) => {
    // Compose quick successive edits locally instead of waiting for a sequence refetch between
    // each control (choose Circle, then immediately enable Shadow must preserve both).
    setDraft(next);
    onSetEffects(clip.id, { ...clip.effects, appearance: clipAppearancePayload(next) });
  };

  return (
    <div className="grid gap-2 border-t border-border pt-2.5">
      <span className="text-ui-xs font-semibold uppercase tracking-[0.05em] text-muted-foreground">{t("clipAppearance")}</span>
      <div className="grid grid-cols-[52px_1fr] items-center gap-2">
        <span className="text-ui-xs text-muted-foreground">{t("clipMask")}</span>
        <div className="grid grid-cols-3 gap-1">
          {(
            [
              { shape: "none", label: t("maskShapeNone") },
              { shape: "rounded", label: t("maskShapeRounded") },
              { shape: "circle", label: t("maskShapeCircle") },
            ] as Array<{ shape: MaskShape; label: string }>
          ).map(({ shape, label }) => (
            <button
              key={shape}
              type="button"
              aria-label={label}
              className={cn(
                "cursor-pointer rounded-md border border-border bg-panel px-1.5 py-1 text-xs text-muted-foreground transition-[border-color,color,background-color] duration-100 hover:border-border-strong hover:text-foreground",
                appearance.mask.shape === shape && "border-primary bg-accent text-accent-foreground hover:border-primary hover:text-accent-foreground",
              )}
              onClick={() => commit({ ...appearance, mask: { ...appearance.mask, shape } })}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {appearance.mask.shape === "rounded" && (
        <AppearanceSlider label={t("maskRadius")} value={appearance.mask.radius} min={0} max={0.5} step={0.01} format={(value) => `${Math.round(value * 200)}%`} onCommit={(radius) => commit({ ...appearance, mask: { ...appearance.mask, radius } })} />
      )}
      <div className="flex items-center justify-between">
        <span className="text-ui-xs text-muted-foreground">{t("clipShadow")}</span>
        <button
          type="button"
          aria-label={t("clipShadowEnable")}
          className={cn(
            "min-w-[44px] cursor-pointer rounded-md border border-border bg-panel px-1.5 py-1 text-xs text-muted-foreground hover:border-border-strong hover:text-foreground",
            appearance.shadow.enabled && "border-primary bg-accent text-accent-foreground hover:border-primary hover:text-accent-foreground",
          )}
          onClick={() => commit({ ...appearance, shadow: { ...appearance.shadow, enabled: !appearance.shadow.enabled } })}
        >
          {appearance.shadow.enabled ? t("enabled") : t("disabled")}
        </button>
      </div>
      {appearance.shadow.enabled && (
        <div className="grid gap-1.5">
          <label className="grid grid-cols-[52px_1fr] items-center gap-2">
            <span className="text-ui-xs text-muted-foreground">{t("shadowColor")}</span>
            <input
              className="h-6 w-full cursor-pointer rounded-md border border-input bg-transparent p-0.5 [&::-webkit-color-swatch]:rounded [&::-webkit-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-0"
              type="color"
              value={appearance.shadow.color}
              aria-label={t("shadowColor")}
              onChange={(event) => commit({ ...appearance, shadow: { ...appearance.shadow, color: event.target.value } })}
            />
          </label>
          <AppearanceSlider label={t("shadowOpacity")} value={appearance.shadow.opacity} min={0} max={1} step={0.05} format={(value) => `${Math.round(value * 100)}%`} onCommit={(opacity) => commit({ ...appearance, shadow: { ...appearance.shadow, opacity } })} />
          <AppearanceSlider label={t("shadowBlur")} value={appearance.shadow.blur} min={0} max={120} step={1} format={(value) => `${Math.round(value)}px`} onCommit={(blur) => commit({ ...appearance, shadow: { ...appearance.shadow, blur } })} />
          <AppearanceSlider label={t("shadowOffsetX")} value={appearance.shadow.offsetX} min={-120} max={120} step={1} format={(value) => `${Math.round(value)}px`} onCommit={(offsetX) => commit({ ...appearance, shadow: { ...appearance.shadow, offsetX } })} />
          <AppearanceSlider label={t("shadowOffsetY")} value={appearance.shadow.offsetY} min={-120} max={120} step={1} format={(value) => `${Math.round(value)}px`} onCommit={(offsetY) => commit({ ...appearance, shadow: { ...appearance.shadow, offsetY } })} />
        </div>
      )}
    </div>
  );
}

function AppearanceSlider({
  label,
  value,
  min,
  max,
  step,
  format,
  onCommit,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onCommit: (value: number) => void;
}) {
  return (
    <div className="grid grid-cols-[52px_1fr_40px] items-center gap-2">
      <span className="text-ui-xs text-muted-foreground">{label}</span>
      <Slider key={`${label}-${value}`} min={min} max={max} step={step} defaultValue={[value]} onValueCommit={([next]) => onCommit(next)} aria-label={label} />
      <span className="timecode text-right text-ui-xs text-muted-foreground">{format(value)}</span>
    </div>
  );
}
