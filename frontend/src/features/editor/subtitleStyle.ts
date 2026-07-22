import type React from "react";

const SYSTEM_FONT_STACK =
  'system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif';

export type SubtitleStyle = {
  font_size: number;
  color: string;
  bg_color: string;
  bg_opacity: number;
  bold: boolean;
  position: "bottom" | "center" | "top";
  offset: number;
  font_family: string;
  /** Set when the family comes from an uploaded workspace font; "" for the built-in stacks.
      Export uses this to locate the file — the family name alone is not enough, since an
      uploaded font is not installed on the machine doing the render. */
  font_id: string;
};

/** Curated families rather than a free-text box. Two rules carried over from mibu-video:
    always end in a generic fallback, and put the FAMILY name before any PostScript alias —
    the export side's fontconfig only resolves family names, so an alias-first stack silently
    falls through the whole list to a Latin-only default with no CJK glyphs. */
export const SUBTITLE_FONTS: { labelKey: string; value: string }[] = [
  { labelKey: "subFontSystem", value: SYSTEM_FONT_STACK },
  { labelKey: "subFontHei", value: '"PingFang SC", "Microsoft YaHei", sans-serif' },
  { labelKey: "subFontSong", value: '"Songti SC", "SimSun", serif' },
  { labelKey: "subFontKai", value: '"Kaiti SC", "KaiTi", serif' },
  { labelKey: "subFontXingkai", value: '"Xingkai SC", "STXingkai", "KaiTi", cursive' },
  { labelKey: "subFontLishu", value: '"Baoli SC", "LiSu", "STLiti", serif' },
  { labelKey: "subFontYuan", value: '"Yuanti SC", "YouYuan", "Hiragino Maru Gothic ProN", sans-serif' },
  { labelKey: "subFontSerifLatin", value: 'Georgia, "Times New Roman", serif' },
  { labelKey: "subFontMono", value: 'ui-monospace, "SFMono-Regular", Menlo, monospace' },
];

export const SUBTITLE_DEFAULTS: SubtitleStyle = {
  font_size: 32,
  color: "#ffffff",
  bg_color: "#000000",
  bg_opacity: 0.5,
  bold: true,
  position: "bottom",
  offset: 8,
  font_family: SYSTEM_FONT_STACK,
  font_id: "",
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
    font_family: s.font_family || SUBTITLE_DEFAULTS.font_family,
    font_id: s.font_id || "",
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
    fontFamily: style.font_family,
    fontWeight: style.bold ? 700 : 400,
    background: style.bg_opacity > 0 ? hexToRgba(style.bg_color, style.bg_opacity) : "transparent",
    left: "50%",
    // 绝对定位 + left:50% 的收缩适配宽度只有画框的一半,长句会提前折行;
    // 按内容定宽(max-w 类仍封顶 86%),translateX(-50%) 再居中。
    width: "max-content",
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


/** Target languages offered wherever translation appears (Google codes; the AI path takes the
    same codes as hints). Shared so the transcript and subtitle panels cannot drift apart. */
export const TRANSLATE_LANGS = ["en", "zh-CN", "zh-TW", "ja", "ko", "fr", "de", "es", "ru"] as const;
