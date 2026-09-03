import { describe, expect, it } from "vitest";

import {
  CANVAS_PANEL_EDGE_INSET_PX,
  canvasDockedPanelEdges,
  canvasPanelTop,
  canvasRightDockHandleEdges,
  canvasRightDockOcclusion,
} from "./canvasPanelLayout";

describe("canvas panel geometry", () => {
  it("uses one inset for the dock and its resize handle", () => {
    expect(canvasPanelTop(8)).toBe(58);
    expect(canvasDockedPanelEdges(8)).toEqual({
      top: 58,
      right: CANVAS_PANEL_EDGE_INSET_PX,
      bottom: CANVAS_PANEL_EDGE_INSET_PX,
    });
    expect(canvasRightDockHandleEdges(420, 8)).toEqual({
      top: 58,
      right: 420 + CANVAS_PANEL_EDGE_INSET_PX,
      bottom: CANVAS_PANEL_EDGE_INSET_PX,
    });
    expect(canvasRightDockOcclusion(420)).toBe(436);
  });
});
