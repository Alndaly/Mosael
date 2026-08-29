/**
 * 撤销这件事有三处会静默出错,而它们都不是「撤销本身写错了」:
 * 撤销自己造成的变化又被记一步、连续拖动被记成几十步、改了新东西之后重做还留着。
 */
import { describe, expect, it } from "vitest";

import { canRedo, canUndo, emptyHistory, record, redo, undo } from "./canvasHistory";

describe("画布历史", () => {
  it("记一步、退一步、再回来", () => {
    let h = emptyHistory("A");
    h = record(h, "B");
    expect(canUndo(h)).toBe(true);
    expect(canRedo(h)).toBe(false);

    h = undo(h)!;
    expect(h.present).toBe("A");
    expect(canRedo(h)).toBe(true);

    h = redo(h)!;
    expect(h.present).toBe("B");
  });

  it("和当前一样就不记 —— 自动保存回来的那一轮重渲染不是一次编辑", () => {
    let h = record(emptyHistory("A"), "B");
    const before = h;
    h = record(h, "B");
    expect(h).toBe(before);
  });

  it("撤回去之后又改了别的,重做就没了", () => {
    // 留着的话「重做」会把用户带到一个他从没到过的画布。
    let h = record(record(emptyHistory("A"), "B"), "C");
    h = undo(h)!;
    expect(canRedo(h)).toBe(true);
    h = record(h, "D");
    expect(canRedo(h)).toBe(false);
    expect(h.present).toBe("D");
  });

  it("退到底就退不动了,不会退出一个空画布", () => {
    const h = emptyHistory("A");
    expect(undo(h)).toBeNull();
    expect(redo(h)).toBeNull();
  });

  it("摞太深时丢最老的那几步,而不是最近的", () => {
    let h = emptyHistory("0");
    for (let i = 1; i <= 10; i += 1) h = record(h, String(i), 5);
    expect(h.past).toHaveLength(5);
    expect(h.past[h.past.length - 1]).toBe("9");
    expect(h.present).toBe("10");
  });
})
