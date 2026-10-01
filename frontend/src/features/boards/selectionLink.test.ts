import { describe, expect, it } from "vitest";

import { boundsOf, cellAt, outletOf, selectionDraft, type PlacedCell } from "@/features/boards/selectionLink";

const placed = (id: string, kind: PlacedCell["kind"], x: number, y: number, width = 200, height = 100): PlacedCell => ({ id, kind, x, y, width, height });

describe("选区框和出口的位置", () => {
  it("框是选中几格的外接矩形;一格都没有就没有框", () => {
    expect(boundsOf([placed("a", "image", 0, 0), placed("b", "image", 300, -50, 100, 400)])).toEqual({ x: 0, y: -50, width: 400, height: 400 });
    expect(boundsOf([])).toBeNull();
  });

  it("一格的出口在它右边中点 —— 预览线和真线从同一处出来", () => {
    expect(outletOf(placed("a", "image", 10, 20, 200, 100))).toEqual({ x: 210, y: 70 });
  });
});

describe("指针底下是哪一格", () => {
  it("叠着的取画在上面那一格;分组框不算(落在框里的空白处 = 空白处)", () => {
    const frame = placed("f", "frame", -100, -100, 800, 600);
    const below = placed("below", "image", 0, 0);
    const above = placed("above", "note", 50, 50);
    expect(cellAt({ x: 60, y: 60 }, [frame, below, above])?.id).toBe("above");
    expect(cellAt({ x: 10, y: 10 }, [frame, below, above])?.id).toBe("below");
    expect(cellAt({ x: 600, y: 400 }, [frame, below, above]), "框里的空白处").toBeNull();
  });
});

describe("拖着统一出口时的预览线", () => {
  const a = placed("a", "image", 0, 0);
  const n = placed("n", "note", 0, 200);
  const timeline = placed("t", "sequence", 600, 0, 400, 300);
  const cells = [a, n, timeline];

  it("在空白处:每个源从自己的出口画一根到指针,都是「拖线途中」那种", () => {
    const draft = selectionDraft([a, n], cells, [], { x: 400, y: 600 });
    expect(draft.target).toBeNull();
    expect(draft.verdict).toBeNull();
    expect(draft.lines).toEqual([
      { id: "a", from: { x: 200, y: 50 }, to: { x: 400, y: 600 }, tone: "draft" },
      { id: "n", from: { x: 200, y: 250 }, to: { x: 400, y: 600 }, tone: "draft" },
    ]);
  });

  it("悬在一格上:线头吸到它的入口(左边中点);每一根按规矩判 —— 便签进不了时间线格,那一根标成连不上;有一根连得上,这一格就算连得上", () => {
    const draft = selectionDraft([a, n], cells, [], { x: 700, y: 100 });
    expect(draft.target).toBe("t");
    expect(draft.verdict).toBe("link");
    expect(draft.lines.map((line) => [line.id, line.tone])).toEqual([["a", "link"], ["n", "refused"]]);
    expect(draft.lines.map((line) => line.to)).toEqual([{ x: 600, y: 150 }, { x: 600, y: 150 }]);
  });

  it("已经连着的那一根照样算连得上(松手之后它确实连着);一根都连不上,这一格就是连不上", () => {
    expect(selectionDraft([a], cells, [{ source: "a", target: "t" }], { x: 700, y: 100 }).lines[0].tone).toBe("link");
    expect(selectionDraft([n], cells, [], { x: 700, y: 100 }).verdict).toBe("refused");
  });

  it("终点就是选中的一格:它自己那一根不画", () => {
    const draft = selectionDraft([a, n], cells, [], { x: 50, y: 50 });
    expect(draft.target).toBe("a");
    expect(draft.lines.map((line) => line.id)).toEqual(["n"]);
  });
});
