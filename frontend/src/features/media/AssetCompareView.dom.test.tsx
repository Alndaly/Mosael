/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 滑动分割:两张图叠在同一画面里,拖分割线擦除。
 *
 * 两条判据都是曾经踩过或极易踩到的:
 *
 * 1. **两层的定位必须完全一致**。用 clip-path 而不是给 B 层设 width —— 后者会让 B 的
 *    可用宽度随分割位置变化,`object-contain` 于是重新计算缩放,擦除时画面横向跳动,
 *    比的就不是同一处了。所以断言拖动后两张图的 transform 依然逐字相同。
 *
 * 2. **拖分割线不能连带平移画面**。分割线压在容器上,容器自己也监听 pointerdown 做平移;
 *    漏掉 stopPropagation 的话每拖一次分割线,底下的图也跟着跑,而且是"越擦越偏"。
 *
 * jsdom 没有布局,getBoundingClientRect 全是 0,所以这里把容器的矩形喂成固定值,只验
 * 事件到状态这一段逻辑。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (k: string) => k, usePreferences: () => ({ locale: "zh-CN" }) }));
vi.mock("@/api/client", async () => ({
  assetFileUrl: (id: string) => `/files/${id}`,
  type: undefined,
}));

import { AssetCompareView } from "@/features/media/AssetCompareView";

const asset = (id: string) => ({ id, name: `${id}.png`, kind: "image" }) as never;

/** 把容器的矩形固定成 1000×800、左边界 0,这样 clientX 就等于百分比×10。 */
function stubRects() {
  Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ left: 0, top: 0, width: 1000, height: 800, right: 1000, bottom: 800, x: 0, y: 0, toJSON: () => ({}) }),
  });
}

describe("素材对比 · 滑动分割", () => {
  it("拖分割线只改分割位置,不动画面本身", () => {
    stubRects();
    const { container } = render(<AssetCompareView assets={[asset("a"), asset("b")]} onClose={() => {}} />);

    fireEvent.click(screen.getByText("mediaCompareSplit"));

    const transformsBefore = [...container.querySelectorAll("img")].map((img) => img.style.transform);
    expect(transformsBefore).toHaveLength(2);
    expect(transformsBefore[0]).toBe(transformsBefore[1]); // 两层同一个变换

    const divider = container.querySelector(".cursor-ew-resize") as HTMLElement;
    fireEvent.pointerDown(divider, { clientX: 500, clientY: 400, button: 0 });
    fireEvent(window, new MouseEvent("pointermove", { clientX: 800, clientY: 400 }) as never);
    fireEvent(window, new MouseEvent("pointerup", { clientX: 800, clientY: 400 }) as never);

    const clipped = container.querySelector("[style*='clip-path']") as HTMLElement;
    expect(clipped.style.clipPath).toContain("80%");

    const transformsAfter = [...container.querySelectorAll("img")].map((img) => img.style.transform);
    expect(transformsAfter).toEqual(transformsBefore); // 没有被平移带跑
  });
});
