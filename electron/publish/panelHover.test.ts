import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HOVER_RECHECK_MS, PanelHover } from "./panelHover";

describe("PanelHover", () => {
  let inside: boolean;
  const pointerInside = vi.fn(() => inside);
  const onChange = vi.fn();
  let hover: PanelHover;

  beforeEach(() => {
    vi.useFakeTimers();
    inside = true;
    pointerInside.mockClear();
    onChange.mockClear();
    hover = new PanelHover({ pointerInside, onChange });
  });

  afterEach(() => {
    hover.dispose();
    vi.useRealTimers();
  });

  it("turns on with any mouse event over the page and off with mouseLeave, notifying only on change", () => {
    hover.observe("a", "mouseMove");
    hover.observe("a", "mouseMove");
    hover.observe("a", "mouseWheel");
    expect(hover.has("a")).toBe(true);
    expect(onChange).toHaveBeenCalledTimes(1);

    hover.observe("a", "mouseLeave");
    expect(hover.has("a")).toBe(false);
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("clears a hover whose mouseLeave never came once the pointer is no longer over the view", () => {
    hover.observe("a", "mouseMove");
    vi.advanceTimersByTime(HOVER_RECHECK_MS);
    expect(hover.has("a")).toBe(true);

    inside = false; // 视图被挪走 / 应用失去激活:Chromium 没补发 mouseLeave
    vi.advanceTimersByTime(HOVER_RECHECK_MS);
    expect(hover.has("a")).toBe(false);
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("does not poll while nothing is hovered", () => {
    vi.advanceTimersByTime(HOVER_RECHECK_MS * 10);
    expect(pointerInside).not.toHaveBeenCalled();

    hover.observe("a", "mouseMove");
    hover.observe("a", "mouseLeave");
    pointerInside.mockClear();
    vi.advanceTimersByTime(HOVER_RECHECK_MS * 10);
    expect(pointerInside).not.toHaveBeenCalled();
  });

  it("forgets a detached panel without announcing it (the caller re-lays out anyway)", () => {
    hover.observe("a", "mouseMove");
    onChange.mockClear();
    hover.drop("a");
    expect(hover.has("a")).toBe(false);
    expect(onChange).not.toHaveBeenCalled();
    vi.advanceTimersByTime(HOVER_RECHECK_MS * 4);
    expect(pointerInside).not.toHaveBeenCalled();
  });
});
