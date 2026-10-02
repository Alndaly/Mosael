/**
 * 花字描边契约的前端一侧:跑 contracts/text-stroke-cases.json。
 *
 * 后端 `backend/tests/test_text_stroke_parity.py` 跑**同一份文件**,并且真渲导出 PNG 与 libass
 * 两条路径量像素(字芯在不在、外轮廓动没动、两条路径外圈一样不一样宽)。
 *
 * 预览这一侧画的是 DOM:`-webkit-text-stroke` 配 `paint-order: stroke fill` —— 先画描边、再画
 * 填充,描边向内的那一半被字本身盖回去,只剩字外一圈。修复前没有 paint-order,描边居中盖在
 * 字上面,细笔画字体(霞鹜文楷)的白芯几乎被吃光;导出 PNG 跑的是同一套 CSS,于是两边一起坏。
 *
 * 线宽写成 cqw(随预览缩放),这里在画幅原生宽度上解析回像素再和语料比。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/text-stroke-cases.json";
import { DEFAULT_TEXT_STYLE, outerStrokePx, TEXT_STROKE_MAX_OUTER_RATIO, textStyleCss } from "@/features/editor/textStyle";
import type { Transform } from "@/features/editor/TransformOverlay";

const FRAME_W = 1920;
const IDENTITY: Transform = { scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 };

/** `12.5cqw` → 在画幅原生宽度上的像素(浏览器会做的那件事)。 */
function cqwToPx(value: unknown): number {
  const m = /^(-?[\d.e-]+)cqw$/.exec(String(value ?? ""));
  if (!m) throw new Error(`描边线宽不是 cqw:${String(value)}`);
  return (Number(m[1]) / 100) * FRAME_W;
}

describe("花字描边契约", () => {
  it("语料在,且带版本号 —— 找不到就静默跳过是最坏的结果", () => {
    expect(contract.contract).toBe("text-stroke");
    expect(typeof contract.version).toBe("number");
    expect(contract.cases.length).toBeGreaterThan(0);
  });

  it("封顶比例与语料一致", () => {
    expect(TEXT_STROKE_MAX_OUTER_RATIO).toBe(contract.max_outer_ratio);
  });

  for (const c of contract.cases) {
    it(`${c.name}:外圈宽度`, () => {
      expect(outerStrokePx({ ...DEFAULT_TEXT_STYLE, ...c.style })).toBeCloseTo(c.expected.outer_px, 6);
    });

    it(`${c.name}:预览先画描边、再画填充,线宽 = 外圈 × 2`, () => {
      const css = textStyleCss({ ...DEFAULT_TEXT_STYLE, ...c.style }, IDENTITY, FRAME_W);
      if (c.expected.css_stroke_width_px === 0) {
        expect(css.WebkitTextStrokeWidth).toBeUndefined();
        expect(css.paintOrder).toBeUndefined();
        return;
      }
      expect(css.paintOrder).toBe("stroke fill");
      expect(cqwToPx(css.WebkitTextStrokeWidth)).toBeCloseTo(c.expected.css_stroke_width_px, 6);
    });
  }
});
