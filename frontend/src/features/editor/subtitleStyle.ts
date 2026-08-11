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

/** Curated families rather than a free-text box. Two rules carried over from the predecessor project:
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

/** 无空格的 `rgba(r,g,b,a)` —— 导出侧(text_render)按这个格式产出,两边写法一致,契约里
    就能直接比字符串,不必各写一个颜色解析器。 */
function hexToRgba(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return `rgba(0,0,0,${alpha})`;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

/**
 * 字幕框的固定几何。**这几个数字是契约**(contracts/subtitle-cases.json)。
 *
 * 导出侧 `backend/app/media/text_render._subtitle_style_css` 有一份对应的 —— 它们决定
 * 预览里看到的和导出的成片是不是同一个画面,改一个必须两侧一起改,`subtitleStyle.parity.test.ts`
 * 与 `test_subtitle_parity.py` 会同时红。
 *
 * 用 em 而不是固定 px:预览按显示尺寸缩、导出按帧原生渲染,固定 px 会让框和文字的间距在两边对不上。
 */
export const SUBTITLE_BOX = {
  maxWidthPct: 86,
  borderRadius: "0.33em",
  padding: "0.16em 0.55em",
  lineHeight: "1.45",
  textAlign: "center",
  textShadow: "0 0.055em 0.11em rgba(0,0,0,0.7)",
  whiteSpace: "pre-wrap",
} as const;

/** 解析后的字幕框 —— 契约比的就是这个形状(见 contracts/subtitle-cases.json)。
 *
 *  预览的 CSS 由它派生:字号写成 cqw 是为了跟着预览缩放,而在画幅**原生宽度**上
 *  `(font_size / frameWidth) * 100` cqw 正好解析成 `font_size` px,与导出侧相同。 */
export function subtitleBox(style: SubtitleStyle, frameWidth: number) {
  return {
    font_size_px: style.font_size,
    color: style.color,
    font_weight: style.bold ? 700 : 400,
    background: style.bg_opacity > 0 ? hexToRgba(style.bg_color, style.bg_opacity) : "transparent",
    // 导出侧写的是 px(`int(frame_w * 0.86)`),预览写的是百分比 —— 同一个比例两种写法,
    // 契约钉的是解析后的像素,所以这里按同样的截断取整。
    max_width_px: Math.trunc((frameWidth * SUBTITLE_BOX.maxWidthPct) / 100),
    border_radius: SUBTITLE_BOX.borderRadius,
    padding: SUBTITLE_BOX.padding,
    line_height: SUBTITLE_BOX.lineHeight,
    text_align: SUBTITLE_BOX.textAlign,
    text_shadow: SUBTITLE_BOX.textShadow,
    white_space: SUBTITLE_BOX.whiteSpace,
  };
}

/** Inline CSS for the preview subtitle. Font size is expressed in cqw so it scales with the
 *  preview frame width — the frame is an `inline-size` container (a `size` container collapses
 *  its aspect-ratio-derived height to 0). frameWidth is the sequence's native width; since the
 *  frame keeps a fixed aspect ratio, scaling by width matches the intended height ratio. */
export function subtitleCss(style: SubtitleStyle, frameWidth: number): React.CSSProperties {
  const box = subtitleBox(style, frameWidth);
  const css: React.CSSProperties = {
    // 字号是唯一按预览尺寸缩放的一项(cqw);其余几何全部从 subtitleBox 派生,**不要再在
    // className 里写一份** —— 那正是它和导出侧漂移的方式。
    fontSize: `${(style.font_size / Math.max(frameWidth, 1)) * 100}cqw`,
    color: box.color,
    fontFamily: style.font_family,
    fontWeight: box.font_weight,
    background: box.background,
    maxWidth: `${SUBTITLE_BOX.maxWidthPct}%`,
    borderRadius: box.border_radius,
    padding: box.padding,
    lineHeight: box.line_height,
    textAlign: box.text_align,
    textShadow: box.text_shadow,
    whiteSpace: box.white_space,
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
