/**
 * Select 的菜单要有**固定限高**,不能只靠 Radix 的 available-height。
 *
 * available-height 管的是「不顶出屏幕」,但它允许菜单长到近千像素:触发器在屏幕底部、
 * 菜单向上展开时,可用高度几乎就是整个窗口。时长区间 4–30s 在画板节点上列成 27 项,
 * 就是这个下场 —— 顶部的选项直接跑出窗口外(截图为证,2026-09-01)。
 *
 * 菜单高了不会报错,只是超出屏幕 —— 正是「违反了不会报错」的那类规约,所以钉在这里。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SELECT_TSX = join(import.meta.dirname, "select.tsx");

describe("Select 菜单限高", () => {
  it("SelectContent 的 max-h 是 min(固定上限, available-height),不是只有后者", () => {
    const source = readFileSync(SELECT_TSX, "utf8");
    // min( 里必须同时出现固定上限(rem)和 Radix 的可用高度 —— 缺了固定上限,
    // 长列表又能长到接近窗口高;缺了 available-height,小窗口里会顶出屏幕。
    expect(source).toMatch(/max-h-\[min\(\d+rem,var\(--radix-select-content-available-height/);
  });
});
