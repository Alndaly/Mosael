import type React from "react";

export type SubtitleStyle = {
  font_size: number;
  color: string;
  bg_color: string;
  bg_opacity: number;
  bold: boolean;
  position: "bottom" | "center" | "top";
  offset: number;
};

export const SUBTITLE_DEFAULTS: SubtitleStyle = {
  font_size: 32,
  color: "#ffffff",
  bg_color: "#000000",
  bg_opacity: 0.5,
  bold: true,
  position: "bottom",
  offset: 8,
};

export function readSubtitleStyle(raw: Record<string, unknown> | undefined | null): SubtitleStyle {
  const s = (raw ?? {}) as Partial<SubtitleStyle>;
  return {
    font_size: typeof s.font_size === "number" ? s.font_size : SUBTITLE_DEFAULTS.font_size,
    color: s.color ?? SUBTITLE_DEFAULTS.color,
    bg_color: s.bg_color ?? SUBTITLE_DEFAULTS.bg_color,
    bg_opacity: typeof s.bg_opacity === "number" ? s.bg_opacity : SUBTITLE_DEFAULTS.bg_opacity,
    bold: typeof s.bold === "boolean" ? s.bold : SUBTITLE_DEFAULTS.bold,
    position: s.position ?? SUBTITLE_DEFAULTS.position,
    offset: typeof s.offset === "number" ? s.offset : SUBTITLE_DEFAULTS.offset,
  };
}

function hexToRgba(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return `rgba(0,0,0,${alpha})`;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/** Inline CSS for the preview subtitle. Font size is expressed in cqw so it scales with the
 *  preview frame width — the frame is an `inline-size` container (a `size` container collapses
 *  its aspect-ratio-derived height to 0). frameWidth is the sequence's native width; since the
 *  frame keeps a fixed aspect ratio, scaling by width matches the intended height ratio. */
export function subtitleCss(style: SubtitleStyle, frameWidth: number): React.CSSProperties {
  const css: React.CSSProperties = {
    fontSize: `${(style.font_size / Math.max(frameWidth, 1)) * 100}cqw`,
    color: style.color,
    fontWeight: style.bold ? 700 : 400,
    background: style.bg_opacity > 0 ? hexToRgba(style.bg_color, style.bg_opacity) : "transparent",
    left: "50%",
  };
  if (style.position === "top") {
    css.top = `${style.offset}%`;
    css.bottom = "auto";
    css.transform = "translateX(-50%)";
  } else if (style.position === "center") {
    css.top = "50%";
    css.bottom = "auto";
    css.transform = `translate(-50%, calc(-50% + ${style.offset}%))`;
  } else {
    css.bottom = `${style.offset}%`;
    css.top = "auto";
    css.transform = "translateX(-50%)";
  }
  return css;
}
