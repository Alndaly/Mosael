import { describe, expect, it } from "vitest";

import { DEFAULT_TEXT_STYLE, readTextStyle, textStyleCss } from "@/features/editor/textStyle";
import type { Transform } from "@/features/editor/TransformOverlay";

const tf = (over: Partial<Transform> = {}): Transform => ({ scale: 1, x: 0, y: 0, rotation: 0, opacity: 1, ...over });

describe("readTextStyle", () => {
  it("falls back to defaults when empty", () => {
    expect(readTextStyle(undefined)).toEqual(DEFAULT_TEXT_STYLE);
    expect(readTextStyle({})).toEqual(DEFAULT_TEXT_STYLE);
  });

  it("clamps numbers and rejects bad colors / aligns", () => {
    const st = readTextStyle({ font_size: 9999, stroke_width: 999, color: "nope", align: "sideways" });
    expect(st.font_size).toBe(800);
    expect(st.stroke_width).toBe(40);
    expect(st.color).toBe("#ffffff");
    expect(st.align).toBe("center");
  });

  it("keeps valid values", () => {
    const st = readTextStyle({ color: "#ff0066", stroke_color: "#101010", stroke_width: 3, bold: false, italic: true, align: "left" });
    expect(st.color).toBe("#ff0066");
    expect(st.stroke_color).toBe("#101010");
    expect(st.stroke_width).toBe(3);
    expect(st.bold).toBe(false);
    expect(st.italic).toBe(true);
    expect(st.align).toBe("left");
  });
});

describe("textStyleCss", () => {
  it("centers on transform position (matches backend \\pos)", () => {
    expect(textStyleCss(DEFAULT_TEXT_STYLE, tf(), 1920)).toMatchObject({ left: "50%", top: "50%" });
    expect(textStyleCss(DEFAULT_TEXT_STYLE, tf({ x: 1 }), 1920).left).toBe("100%");
    expect(textStyleCss(DEFAULT_TEXT_STYLE, tf({ x: -1 }), 1920).left).toBe("0%");
    expect(textStyleCss(DEFAULT_TEXT_STYLE, tf({ y: -1 }), 1920).top).toBe("0%");
  });

  it("maps scale/rotation/opacity and scales font by frame width", () => {
    const css = textStyleCss({ ...DEFAULT_TEXT_STYLE, font_size: 96 }, tf({ scale: 2, rotation: 30, opacity: 0.5 }), 1920);
    expect(css.transform).toBe("translate(-50%,-50%) scale(2) rotate(30deg)");
    expect(css.opacity).toBe(0.5);
    expect(css.fontSize).toBe("5cqw"); // 96/1920*100
  });

  it("emits webkit text stroke only when stroke width > 0", () => {
    expect(textStyleCss(DEFAULT_TEXT_STYLE, tf(), 1920).WebkitTextStrokeWidth).toBeUndefined();
    const css = textStyleCss({ ...DEFAULT_TEXT_STYLE, stroke_width: 4, stroke_color: "#000000" }, tf(), 1920);
    expect(css.WebkitTextStrokeColor).toBe("#000000");
  });
});
