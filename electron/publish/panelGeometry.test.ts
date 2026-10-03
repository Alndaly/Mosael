import { describe, expect, it } from "vitest";

import {
  DEFAULT_PANEL_LAYOUT,
  PANEL,
  fitPanelLayout,
  movePanel,
  panelHeightFor,
  panelRect,
  resizePanel,
  type PanelHandle,
  type PanelLayout,
  type PanelRect,
} from "./panelGeometry";
import { EMBED_HEADER_HEIGHT } from "./types";

const AREA = { width: 1440, height: 900 };
const START: PanelLayout = { x: 400, y: 300, width: 384 };

/** 渲染层做的事:起手时的卡片 + 指针位移 → 指针要的矩形(不带约束)。 */
function dragged(handle: PanelHandle, from: PanelRect, dx: number, dy: number): PanelRect {
  const rect = { ...from };
  if (handle.includes("w")) {
    rect.x += dx;
    rect.width -= dx;
  }
  if (handle.includes("e")) rect.width += dx;
  if (handle.includes("n")) {
    rect.y += dy;
    rect.height -= dy;
  }
  if (handle.includes("s")) rect.height += dy;
  return rect;
}

function resize(handle: PanelHandle, dx: number, dy: number, from: PanelLayout = START): PanelRect {
  return panelRect(resizePanel(handle, dragged(handle, panelRect(from, AREA), dx, dy), AREA), AREA);
}

describe("panel size is one scalar", () => {
  it("derives the card height from its width so the page viewport stays 1280×800", () => {
    for (const width of [PANEL.minWidth, PANEL.width, 600, 824]) {
      const height = panelHeightFor(width);
      const view = { width: width - PANEL.inset * 2, height: height - PANEL.header - PANEL.inset };
      // 布局视口 = 视图尺寸 / 缩放,缩放 = 视图宽 / 1280。取整误差在一个视图像素以内。
      expect(Math.abs(view.height - (view.width * PANEL.layoutHeight) / PANEL.layoutWidth)).toBeLessThanOrEqual(0.5);
    }
  });

  it("starts at the default width with the matching height, tucked into the bottom-right corner", () => {
    const rect = panelRect(DEFAULT_PANEL_LAYOUT, AREA);
    expect(rect).toEqual({
      x: AREA.width - PANEL.width - PANEL.margin,
      y: AREA.height - panelHeightFor(PANEL.width) - PANEL.margin,
      width: PANEL.width,
      height: panelHeightFor(PANEL.width),
    });
  });
});

describe("resizing from a corner", () => {
  it.each([
    ["se", 120, 80],
    ["nw", -120, -80],
    ["ne", 120, -80],
    ["sw", -120, 80],
  ] as const)("%s grows proportionally and keeps the opposite corner fixed", (handle, dx, dy) => {
    const before = panelRect(START, AREA);
    const after = resize(handle, dx, dy);

    expect(after.width).toBeGreaterThan(before.width);
    expect(after.height).toBe(panelHeightFor(after.width));
    const right = (r: PanelRect) => r.x + r.width;
    const bottom = (r: PanelRect) => r.y + r.height;
    if (handle.includes("e")) expect(after.x).toBe(before.x);
    else expect(right(after)).toBe(right(before));
    if (handle.includes("s")) expect(after.y).toBe(before.y);
    else expect(bottom(after)).toBe(bottom(before));
  });

  it("follows a purely horizontal or purely vertical drag in both directions", () => {
    // 只取横纵较大者时横着往里拖缩不小;只取较小者时横着往外拖放不大。两个方向都得动。
    expect(resize("se", 100, 0).width).toBeGreaterThan(START.width);
    expect(resize("se", -100, 0).width).toBeLessThan(START.width);
    expect(resize("se", 0, 100).width).toBeGreaterThan(START.width);
    expect(resize("se", 0, -100).width).toBeLessThan(START.width);
  });

  it("puts the corner on its diagonal exactly under the pointer when the pointer is on that diagonal", () => {
    const before = panelRect(START, AREA);
    const width = 500;
    const after = resize("se", width - before.width, panelHeightFor(width) - before.height);
    expect(after.width).toBe(width);
  });
});

describe("resizing from an edge", () => {
  it("right edge sets the width and keeps the left edge and the vertical centre", () => {
    const before = panelRect(START, AREA);
    const after = resize("e", 90, 37); // 纵向位移对左右边没有意义
    expect(after.width).toBe(before.width + 90);
    expect(after.x).toBe(before.x);
    expect(Math.abs(after.y + after.height / 2 - (before.y + before.height / 2))).toBeLessThanOrEqual(0.5);
  });

  it("left edge keeps the right edge fixed", () => {
    const before = panelRect(START, AREA);
    const after = resize("w", -60, 0);
    expect(after.width).toBe(before.width + 60);
    expect(after.x + after.width).toBe(before.x + before.width);
  });

  it("bottom edge is proportional too and keeps the top edge and the horizontal centre", () => {
    const before = panelRect(START, AREA);
    const after = resize("s", 0, 60);
    expect(after.height).toBe(panelHeightFor(after.width));
    expect(Math.abs(after.height - (before.height + 60))).toBeLessThanOrEqual(1);
    expect(after.y).toBe(before.y);
    expect(Math.abs(after.x + after.width / 2 - (before.x + before.width / 2))).toBeLessThanOrEqual(0.5);
  });

  it("top edge keeps the bottom edge fixed", () => {
    const before = panelRect(START, AREA);
    const after = resize("n", 0, 40);
    expect(after.width).toBeLessThan(before.width);
    expect(after.y + after.height).toBe(before.y + before.height);
  });

  it("does not drift during a long drag: the anchor comes from the drag, not from the rounded result", () => {
    const start = panelRect(START, AREA);
    let layout: PanelLayout = START;
    for (let dx = 1; dx <= 200; dx += 1) layout = resizePanel("e", dragged("e", start, dx, 0), AREA);
    for (let dx = 199; dx >= 0; dx -= 1) layout = resizePanel("e", dragged("e", start, dx, 0), AREA);
    expect(panelRect(layout, AREA)).toEqual(start);
  });
});

describe("limits", () => {
  it("never goes below the minimum width, and still keeps the anchor", () => {
    const before = panelRect(START, AREA);
    const after = resize("nw", 300, 300);
    expect(after.width).toBe(PANEL.minWidth);
    expect(after.x + after.width).toBe(before.x + before.width);
    expect(after.y + after.height).toBe(before.y + before.height);
  });

  it("caps the size at the window share", () => {
    const after = resize("se", 2000, 2000, { x: 0, y: EMBED_HEADER_HEIGHT, width: 384 });
    // 1440×900:宽上限 864,高上限 540 → 折算成宽 824,取小。
    expect(after.width).toBe(824);
    expect(after.height).toBeLessThanOrEqual(540);
  });

  it("stops growing at the window edge instead of pushing the anchored corner away", () => {
    const nearTopLeft: PanelLayout = { x: 30, y: EMBED_HEADER_HEIGHT + 30, width: 384 };
    const before = panelRect(nearTopLeft, AREA);
    const after = resize("nw", -200, -200, nearTopLeft);
    expect(after.x).toBe(0);
    expect(after.x + after.width).toBe(before.x + before.width);
    expect(after.y + after.height).toBe(before.y + before.height);
  });

  it("keeps a moved panel inside the window and below the top bar", () => {
    expect(movePanel(START, { x: -50, y: 0 }, AREA)).toEqual({ x: 0, y: EMBED_HEADER_HEIGHT, width: 384 });
    expect(movePanel(START, { x: 5000, y: 5000 }, AREA)).toEqual({
      x: AREA.width - 384,
      y: AREA.height - panelHeightFor(384),
      width: 384,
    });
  });

  it("refits a stored layout into a smaller window and keeps the default corner when never moved", () => {
    expect(fitPanelLayout({ x: null, y: null, width: 100 }, AREA)).toEqual({ x: null, y: null, width: PANEL.minWidth });
    const small = { width: 800, height: 600 };
    const fitted = fitPanelLayout({ x: 700, y: 500, width: 700 }, small);
    const rect = panelRect(fitted, small);
    expect(rect.width).toBeLessThanOrEqual(480);
    expect(rect.x + rect.width).toBeLessThanOrEqual(small.width);
    expect(rect.y + rect.height).toBeLessThanOrEqual(small.height);
  });
});
