/**
 * 撤销这件事有三处会静默出错,而它们都不是「撤销本身写错了」:
 * 撤销自己造成的变化又被记一步、连续拖动被记成几十步、改了新东西之后重做还留着。
 */
import { describe, expect, it } from "vitest";

import { canRedo, canUndo, dropSequenceStep, emptyHistory, joinSequenceToCanvas, record, recordSequence, redo, retagSequenceStep, sequenceOf, undo } from "./canvasHistory";
import { sequencesFilledFrom } from "./useBoardSequenceLinks";

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

describe("连一格进时间线格:画布上的线和时间线上的那一段是一步", () => {
  const plain = JSON.stringify({ items: [], edges: [] });
  const linked = JSON.stringify({ items: [], edges: [{ id: "e", source: "v", target: "t" }] });
  const link = { source: "v", target: "t" };

  it("并成一步:撤一下画布回到没连的样子、时间线也撤;重做一下两样都回来", () => {
    let h = record(emptyHistory(plain), linked);
    h = joinSequenceToCanvas(h, "seq", 3, link)!;
    expect(h.past).toEqual([{ sequence: "seq", revision: 3, canvas: plain }]);

    h = undo(h)!;
    expect(h.present, "画布回到没连的样子").toBe(plain);
    expect(h.future[0]).toEqual({ sequence: "seq", revision: 3, canvas: linked });
    h = redo(h)!;
    expect(h.present).toBe(linked);
    expect(h.past).toEqual([{ sequence: "seq", revision: 3, canvas: plain }]);
  });

  it("对不上就不并:上一步里已经有这根线(中间人又做了别的)", () => {
    const other = JSON.stringify({ items: [{ id: "n" }], edges: [{ id: "e", source: "v", target: "t" }] });
    const h = record(record(emptyHistory(plain), linked), other);
    expect(joinSequenceToCanvas(h, "seq", 3, link)).toBeNull();
  });

  it("时间线那一半撤不了:只拿掉时间线那一半,画布那一步还在", () => {
    let h = joinSequenceToCanvas(record(emptyHistory(plain), linked), "seq", 3, link)!;
    h = undo(h)!;
    h = dropSequenceStep(h, "future");
    expect(h.future).toEqual([linked]);
    expect(redo(h)!.present).toBe(linked);
  });
});

describe("服务端新的一版里产出刚落进连着时间线格的那一格", () => {
  it("说得出是哪几条时间线要刷新;本来就有产出的、没连时间线的不算", () => {
    const before = {
      items: [
        { id: "v", kind: "video" as const, x: 0, y: 0 },
        { id: "w", kind: "video" as const, x: 0, y: 0, asset_id: "old" },
        { id: "i", kind: "image" as const, x: 0, y: 0 },
        { id: "t", kind: "sequence" as const, x: 0, y: 0, sequence_id: "seq" },
      ],
      edges: [{ id: "a", source: "v", target: "t" }, { id: "b", source: "w", target: "t" }],
    };
    const after = {
      ...before,
      items: before.items.map((one) => (one.id === "v" || one.id === "i" ? { ...one, asset_id: "made" } : one.id === "w" ? { ...one, asset_id: "new" } : one)),
    };
    expect(sequencesFilledFrom(before, after)).toEqual(["seq"]);
    expect(sequencesFilledFrom(before, { ...after, edges: [] })).toEqual([]);
  });
});
