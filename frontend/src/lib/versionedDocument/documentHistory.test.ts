import { describe, expect, it } from "vitest";

import { GESTURE_GAP_MS, record, redo, reset, startHistory, undo } from "./documentHistory";

describe("documentHistory:一次手势 = 一步", () => {
  it("同一个手势里挨得近的改动并成一步,撤一下回到手势开始之前", () => {
    let h = startHistory(0);
    for (let step = 1; step <= 30; step += 1) h = record(h, step, { gesture: "slider", at: step * 10 });
    expect(h.past).toEqual([0]);
    expect(undo(h).present).toBe(0);
  });

  it("隔得久、或换了手势、或没给手势,各自是一步", () => {
    let h = startHistory("a");
    h = record(h, "b", { gesture: "x", at: 0 });
    h = record(h, "c", { gesture: "x", at: GESTURE_GAP_MS + 1 });
    h = record(h, "d", { gesture: "y", at: GESTURE_GAP_MS + 2 });
    h = record(h, "e", { at: GESTURE_GAP_MS + 3 });
    h = record(h, "f", { at: GESTURE_GAP_MS + 4 });
    expect(h.past).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("撤销之后的新改动清掉重做,也不并进撤销前的那个手势", () => {
    let h = record(startHistory(0), 1, { gesture: "g", at: 0 });
    h = undo(h);
    expect(h.future).toEqual([1]);
    h = record(h, 2, { gesture: "g", at: 1 });
    expect(h.future).toEqual([]);
    expect(h.past).toEqual([0]);
    expect(redo(h)).toBe(h);
  });

  it("撤销 / 重做来回走得通;到头了什么都不做", () => {
    let h = record(record(startHistory(0), 1), 2);
    h = undo(undo(h));
    expect(h.present).toBe(0);
    expect(undo(h)).toBe(h);
    h = redo(redo(h));
    expect(h.present).toBe(2);
  });

  it("最多记 limit 步;reset 清空两边", () => {
    let h = startHistory(0);
    for (let step = 1; step <= 5; step += 1) h = record(h, step, { limit: 3 });
    expect(h.past).toEqual([2, 3, 4]);
    expect(reset(9)).toEqual({ past: [], present: 9, future: [], last: null });
  });
});
