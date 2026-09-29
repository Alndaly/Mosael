/**
 * 撤销这件事有三处会静默出错,而它们都不是「撤销本身写错了」:
 * 撤销自己造成的变化又被记一步、连续拖动被记成几十步、改了新东西之后重做还留着。
 */
import { describe, expect, it } from "vitest";

import { canRedo, canUndo, dropSequenceStep, emptyHistory, record, recordSequence, redo, retagSequenceStep, sequenceOf, undo } from "./canvasHistory";

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

  it("时间线格的一步和画布的步交错着退:退到时间线那一步时画布不动,重做再按原顺序回来", () => {
    let h = record(emptyHistory("A"), "B");
    h = recordSequence(h, "seq", 3);
    h = record(h, "C");
    h = undo(h)!;
    expect(h.present).toBe("B");
    expect(sequenceOf(h.past.at(-1)), "下一步退的是时间线").toBe("seq");
    h = undo(h)!;
    expect(h.present, "撤时间线那一步时画布停在原处").toBe("B");
    expect(sequenceOf(h.future[0])).toBe("seq");
    h = undo(h)!;
    expect(h.present).toBe("A");
    h = redo(redo(redo(h)!)!)!;
    expect(h.present).toBe("C");
    expect(sequenceOf(h.past.at(-1))).toBeNull();
    expect(sequenceOf(h.past.at(-2))).toBe("seq");
  });

  it("时间线的一步记着版本号:撤成了换成回来的那一版,撤不成就从摞里拿掉", () => {
    let h = recordSequence(record(emptyHistory("A"), "B"), "seq", 3);
    h = undo(h)!;
    expect(h.future[0]).toEqual({ sequence: "seq", revision: 3 });
    h = retagSequenceStep(h, "future", 4);
    expect(h.future[0], "重做时照撤销之后那一版比").toEqual({ sequence: "seq", revision: 4 });
    h = redo(h)!;
    h = retagSequenceStep(h, "past", 5);
    expect(h.past.at(-1)).toEqual({ sequence: "seq", revision: 5 });
    h = undo(h)!;
    h = dropSequenceStep(h, "future");
    expect(canRedo(h), "在别处改过、撤不成的那一步不再留着").toBe(false);
    expect(h.past, "画布的步不受影响").toEqual(["A"]);
    expect(dropSequenceStep(h, "past"), "画布的一步不是它能拿掉的").toBe(h);
  });

  it("时间线上做了新的一步,重做就没了", () => {
    let h = record(record(emptyHistory("A"), "B"), "C");
    h = undo(h)!;
    h = recordSequence(h, "seq", 3);
    expect(canRedo(h)).toBe(false);
    expect(h.present).toBe("B");
  });
});
