import type React from "react";

import type { Transform } from "@/features/editor/TransformOverlay";

/**
 * 花字(独立文本元素)的逐条样式。区别于序列级统一、底部的字幕(SubtitleStyle):每条花字自带
 * 一套样式,并用 transform 任意定位/缩放/旋转/打关键帧。预览用 DOM 叠加渲染,与后端 ASS 烧录
 * (\pos/\frz/\fscx + \1c/\bord/\shad)锁步同一套定位与外观语义,保证所见即所得。
 */
export type TextStyle = {
  font_size: number; // 原生帧像素;预览按 frame 宽度换算成 cqw
  color: string;
  stroke_color: string;
  stroke_width: number;
  shadow: number;
  bold: boolean;
  italic: boolean;
  align: "left" | "center" | "right";
  font_family: string;
};

export const DEFAULT_TEXT_STYLE: TextStyle = {
  font_size: 48,
  color: "#ffffff",
  stroke_color: "#000000",
  stroke_width: 0,
  shadow: 0,
  bold: true,
  italic: false,
  align: "center",
  font_family: "",
};

/** 花字可选字体:value 是 CSS 字体栈(预览直接用),导出侧 _resolve_font_stack 取首个具体字族给 ASS \\fn。 */
export const FONT_OPTIONS: Array<{ label: string; value: string }> = [
  { label: "默认", value: "" },
  { label: "黑体", value: '"PingFang SC", "Microsoft YaHei", sans-serif' },
  { label: "宋体", value: '"Songti SC", SimSun, serif' },
  { label: "楷体", value: '"Kaiti SC", KaiTi, serif' },
  { label: "圆体", value: '"Yuanti SC", YouYuan, sans-serif' },
  { label: "无衬线", value: "sans-serif" },
  { label: "衬线", value: "serif" },
];

/** 一键花字预设:只覆盖外观字段(颜色/描边/阴影/粗细),不动字体与字号,方便在任意字体上套风格。 */
export const TEXT_PRESETS: Array<{ key: string; label: string; style: Partial<TextStyle> }> = [
  { key: "plain", label: "简白", style: { color: "#ffffff", stroke_width: 0, shadow: 0, bold: true } },
  { key: "outline", label: "描边", style: { color: "#ffffff", stroke_color: "#000000", stroke_width: 4, shadow: 0, bold: true } },
  { key: "variety", label: "综艺", style: { color: "#ffe14d", stroke_color: "#3a2a00", stroke_width: 6, shadow: 3, bold: true } },
  { key: "shadow", label: "投影", style: { color: "#ffffff", stroke_color: "#000000", stroke_width: 0, shadow: 6, bold: true } },
  { key: "candy", label: "糖果", style: { color: "#ff6fa5", stroke_color: "#ffffff", stroke_width: 4, shadow: 2, bold: true } },
];

const HEX = /^#[0-9a-fA-F]{6}$/;

/** clip.effects.text_style → 归一化后的样式,逐字段回落默认(与后端 _read_text_style 对齐)。 */
export function readTextStyle(raw: unknown): TextStyle {
  const r = (raw ?? {}) as Record<string, unknown>;
  const d = DEFAULT_TEXT_STYLE;
  const num = (key: keyof TextStyle, lo: number, hi: number): number => {
    const v = Number(r[key]);
    return Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : (d[key] as number);
  };
  const color = (key: keyof TextStyle): string => {
    const v = String(r[key] ?? "");
    return HEX.test(v) ? v : (d[key] as string);
  };
  const align = String(r.align ?? d.align);
  return {
    font_size: num("font_size", 4, 800),
    color: color("color"),
    stroke_color: color("stroke_color"),
    stroke_width: num("stroke_width", 0, 40),
    shadow: num("shadow", 0, 40),
    bold: r.bold == null ? d.bold : Boolean(r.bold),
    italic: Boolean(r.italic ?? d.italic),
    align: align === "left" || align === "right" ? align : "center",
    font_family: String(r.font_family ?? "") || "",
  };
}

/** 原生帧像素 → 相对帧宽的 cqw(frame 是 container-query 容器),让文字/描边随预览缩放。 */
function cqw(px: number, frameWidth: number): string {
  return `${(px / Math.max(frameWidth, 1)) * 100}cqw`;
}

/**
 * 花字元素的行内样式:文字中心放到 transform 位置(与后端 \an5+\pos 一致),再叠加缩放/旋转/
 * 透明度与字号/颜色/描边/阴影。定位用 left/top 百分比 + translate(-50%,-50%) 做中心锚点。
 */
export function textStyleCss(style: TextStyle, tf: Transform, frameWidth: number): React.CSSProperties {
  const cx = (0.5 + tf.x * 0.5) * 100;
  const cy = (0.5 + tf.y * 0.5) * 100;
  return {
    position: "absolute",
    left: `${cx}%`,
    top: `${cy}%`,
    transform: `translate(-50%,-50%) scale(${tf.scale}) rotate(${tf.rotation}deg)`,
    transformOrigin: "center",
    opacity: tf.opacity,
    fontSize: cqw(style.font_size, frameWidth),
    lineHeight: 1.2,
    color: style.color,
    fontWeight: style.bold ? 700 : 400,
    fontStyle: style.italic ? "italic" : "normal",
    fontFamily: style.font_family || undefined,
    textAlign: style.align,
    whiteSpace: "pre",
    WebkitTextStrokeWidth: style.stroke_width > 0 ? cqw(style.stroke_width, frameWidth) : undefined,
    WebkitTextStrokeColor: style.stroke_width > 0 ? style.stroke_color : undefined,
    textShadow: style.shadow > 0 ? `0 ${cqw(style.shadow, frameWidth)} ${cqw(style.shadow * 1.5, frameWidth)} rgba(0,0,0,0.65)` : undefined,
  };
}
