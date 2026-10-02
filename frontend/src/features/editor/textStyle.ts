import type React from "react";

import type { MessageKey } from "@/app/messages";
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
  font_family: string; // CSS 字体栈;上传字体时为 uploadedFontStack(family)
  font_id: string; // 上传字体 id;"" = 内置字体栈(与字幕 font_id 同源)
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
  font_id: "",
};

/** 一键花字预设:只覆盖外观字段(颜色/描边/阴影/粗细),不动字体与字号,方便在任意字体上套风格。 */
export const TEXT_PRESETS: Array<{ key: string; labelKey: MessageKey; style: Partial<TextStyle> }> = [
  { key: "plain", labelKey: "textPresetPlain", style: { color: "#ffffff", stroke_width: 0, shadow: 0, bold: true } },
  { key: "outline", labelKey: "textPresetOutline", style: { color: "#ffffff", stroke_color: "#000000", stroke_width: 4, shadow: 0, bold: true } },
  { key: "variety", labelKey: "textPresetVariety", style: { color: "#ffe14d", stroke_color: "#3a2a00", stroke_width: 6, shadow: 3, bold: true } },
  { key: "shadow", labelKey: "textPresetShadow", style: { color: "#ffffff", stroke_color: "#000000", stroke_width: 0, shadow: 6, bold: true } },
  { key: "candy", labelKey: "textPresetCandy", style: { color: "#ff6fa5", stroke_color: "#ffffff", stroke_width: 4, shadow: 2, bold: true } },
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
    font_id: String(r.font_id ?? "") || "",
  };
}

/**
 * 外描边的上限:字形轮廓外那一圈最宽是字号的多少。描边画在字外,再粗字芯也还在;过了这条线,
 * 笔画之间的空隙被糊成一整块,尖角处的斜接尖刺也开始比字还显眼(霞鹜文楷实测)。
 * 后端 render_plan.TEXT_STROKE_MAX_OUTER_RATIO 是同一个数,两份都对着
 * contracts/text-stroke-cases.json 的 max_outer_ratio 测。
 */
export const TEXT_STROKE_MAX_OUTER_RATIO = 0.15;

/**
 * 描边在字形轮廓**外**那一圈的宽度(帧像素)。预览、导出 PNG、libass 回落三条路径都只画这一圈
 * (契约 contracts/text-stroke-cases.json)。
 *
 * stroke_width 是历史上「居中描边」的线宽 —— 一半在字外、一半压进字里,细笔画字体的白芯因此被
 * 吃掉。外圈取它的一半,正好是那时向外伸出的部分:已有花字的外轮廓不动,还回来的只有字芯。
 * 再按字号封顶;超出时按上限画,存储值不动。
 */
export function outerStrokePx(style: Pick<TextStyle, "font_size" | "stroke_width">): number {
  return Math.min(style.stroke_width / 2, style.font_size * TEXT_STROKE_MAX_OUTER_RATIO);
}

/** 描边滑杆的上限:这个字号下还画得出差别的最大存储值(外圈封顶 × 2),最多到原来的 20。 */
export function strokeSliderMax(fontSize: number): number {
  return Math.max(1, Math.min(20, Math.floor(fontSize * TEXT_STROKE_MAX_OUTER_RATIO * 2)));
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
  // 描边居中骑在轮廓上,线宽给外圈的两倍;paint-order 让填充后画、盖回向内的那一半,只剩字外一圈。
  const outer = outerStrokePx(style);
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
    paintOrder: outer > 0 ? "stroke fill" : undefined,
    WebkitTextStrokeWidth: outer > 0 ? cqw(outer * 2, frameWidth) : undefined,
    WebkitTextStrokeColor: outer > 0 ? style.stroke_color : undefined,
    textShadow: style.shadow > 0 ? `0 ${cqw(style.shadow, frameWidth)} ${cqw(style.shadow * 1.5, frameWidth)} rgba(0,0,0,0.65)` : undefined,
  };
}
