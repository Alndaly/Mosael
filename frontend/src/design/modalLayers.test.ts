import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * 蒙层和它的内容**必须同一层**。
 *
 * 真机(2026-10-11):为了躲开浮卡(等人拍板的确认卡 z-60),把遮罩和 Dialog 内容一起抬到 z-70,
 * 却漏了 Sheet 和 AlertDialog 的内容 —— 那两个的蒙层抬了、内容没抬,打开的弹窗被自己的蒙层
 * 盖住(设置页那个弹窗整块变灰、点不动)。jsdom 里没有 Tailwind,取不到算出来的 z-index,
 * 所以这里按**源码**钉:三个用同一份 MODAL_OVERLAY 的原语,内容层要和它同一个 z。
 */
const ui = (name: string) => readFileSync(join(import.meta.dirname, "../components/ui", name), "utf8");

/** 一份源码里第一处 `z-数字` 工具类。 */
function layerOf(source: string, where: string): number {
  const found = source.match(/\bz-(\d+)\b/);
  expect(found, `${where} 里没有 z-* 层级`).not.toBeNull();
  return Number(found![1]);
}

describe("模态的两层在同一层高上", () => {
  const overlay = layerOf(ui("floating.ts").match(/MODAL_OVERLAY = "([^"]+)"/)![1], "MODAL_OVERLAY");

  it("蒙层在浮卡(z-60)之上", () => {
    expect(overlay).toBeGreaterThanOrEqual(70);
  });

  for (const file of ["dialog.tsx", "sheet.tsx", "alert-dialog.tsx"]) {
    it(`${file} 的内容层不落在自己的蒙层下面`, () => {
      expect(layerOf(ui(file), file)).toBe(overlay);
    });
  }
});
