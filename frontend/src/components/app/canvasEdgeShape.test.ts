import { describe, expect, it } from "vitest";

import { CANVAS_EDGE_CLASS } from "@/components/app/canvasEdgeShape";

describe("画布连线的样式类", () => {
  it("任意值选择器里的下划线都转义了 —— 否则 Tailwind 把 `__` 换成空格,规则选不中任何东西", () => {
    const selectors = CANVAS_EDGE_CLASS.split(/\s+/).flatMap((one) => one.match(/^\[&[^\]]*\]/) ?? []);
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) expect(selector, selector).not.toMatch(/(?<!\\)__/);
  });

  it("线色和线宽走 xyflow 的变量,不直接写 stroke(层外的 xyflow 样式会压过工具类)", () => {
    expect(CANVAS_EDGE_CLASS).toContain("[--xy-edge-stroke:var(--border-strong)]");
    expect(CANVAS_EDGE_CLASS).not.toMatch(/:stroke-|\[stroke:|\[stroke-width:/);
  });
});
