import { describe, expect, it } from "vitest";

import { carriedByFrame, type CarryBox } from "@/features/boards/frameCarry";

const box = (id: string, kind: string, x: number, y: number, w = 40, h = 40): CarryBox => ({ id, kind, x, y, width: w, height: h });

describe("分组框带走谁", () => {
  const frame = box("F", "frame", 0, 0, 400, 400);

  it("中心在框里的跟着走", () => {
    const inside = box("n1", "note", 100, 100);
    const outside = box("n2", "note", 500, 500);
    expect(carriedByFrame(frame, [frame, inside, outside]).map((o) => o.id)).toEqual(["n1"]);
  });

  it("压着边线但中心在外的不走", () => {
    // 用碰撞判的话它会跟着走,而它看起来明明在框外。
    const straddling = box("n1", "note", 380, 380, 40, 40); // 中心 (400,400) 恰在边上 → 算里面
    const mostlyOut = box("n2", "note", 390, 390, 40, 40); // 中心 (410,410) → 外面
    const ids = carriedByFrame(frame, [frame, straddling, mostlyOut]).map((o) => o.id);
    expect(ids).toEqual(["n1"]);
  });

  it("框也会被框带走", () => {
    /**
     * 这一条是修复本身。此前排除了所有 frame,于是外框把内框**里的东西**带走了(它们按中心
     * 判确实在外框里),却把内框本身留在原地 —— 一拖,内容就从它的框里跑了出来。
     */
    const innerFrame = box("I", "frame", 50, 50, 200, 200);
    const noteInInner = box("n1", "note", 100, 100);
    const ids = carriedByFrame(frame, [frame, innerFrame, noteInInner]).map((o) => o.id);
    expect(ids).toEqual(["I", "n1"]);
  });

  it("不带自己", () => {
    expect(carriedByFrame(frame, [frame]).map((o) => o.id)).toEqual([]);
  });
});
