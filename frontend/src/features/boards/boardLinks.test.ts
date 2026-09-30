import { describe, expect, it } from "vitest";

import { batchLinks, linkRefusal, linkSources, spawnableFor } from "@/features/boards/boardLinks";
import { joinSequenceToCanvas, record, emptyHistory, undo } from "@/features/boards/canvasHistory";

const cell = (id: string, kind: "note" | "image" | "video" | "audio" | "frame" | "sequence" | "document", selected = false) => ({ id, kind, selected });

describe("一根线能不能连(单格和批量同一条规矩)", () => {
  it("自己连自己、分组框、已经连着的、时间线格收非媒体:都不连", () => {
    expect(linkRefusal(cell("a", "image"), cell("a", "image"), [])).toBe("self");
    expect(linkRefusal(cell("f", "frame"), cell("b", "image"), [])).toBe("notLinkable");
    expect(linkRefusal(cell("a", "note"), cell("f", "frame"), [])).toBe("notLinkable");
    expect(linkRefusal(cell("a", "note"), cell("b", "image"), [{ source: "a", target: "b" }])).toBe("duplicate");
    expect(linkRefusal(cell("a", "note"), cell("t", "sequence"), [])).toBe("timelineTakesMedia");
    expect(linkRefusal(cell("a", "video"), cell("t", "sequence"), [])).toBeNull();
    expect(linkRefusal(cell("a", "note"), cell("b", "image"), [{ source: "b", target: "a" }]), "反方向的线是另一根").toBeNull();
  });
});

describe("多选之后一次连到一格", () => {
  it("拉线的那一格在一组选中里:这一组都连过去(分组框不算);没选中就只有它自己", () => {
    const cells = [cell("a", "image", true), cell("b", "image", true), cell("f", "frame", true), cell("c", "image")];
    expect(linkSources(cells[0], cells).map((one) => one.id)).toEqual(["a", "b"]);
    expect(linkSources(cells[3], cells).map((one) => one.id), "从没选中的那一格拉:就它自己").toEqual(["c"]);
    expect(linkSources(cell("a", "image", true), [cell("a", "image", true)]).map((one) => one.id), "只选了一格").toEqual(["a"]);
  });

  it("逐根按规矩判:连得上的交回,连不上的数一数;终点自己在选中里不算没连上", () => {
    const sources = [cell("v", "video"), cell("n", "note"), cell("i", "image"), cell("t", "sequence")];
    const got = batchLinks(sources, cell("t", "sequence"), [{ source: "i", target: "t" }]);
    expect(got.links).toEqual([{ source: "v", target: "t" }]);
    expect(got.refused, "便签进不了时间线格,那张图已经连着").toBe(2);
  });

  it("批量接进同一条时间线的几段,和画布上那几根线并成撤销里的一步", () => {
    const before = JSON.stringify({ items: [], edges: [] });
    const after = JSON.stringify({ items: [], edges: [{ source: "a", target: "t" }, { source: "b", target: "t" }] });
    let h = record(emptyHistory(before), after);
    h = joinSequenceToCanvas(h, "seq", 5, { source: "a", target: "t", batch: "x" })!;
    h = joinSequenceToCanvas(h, "seq", 6, { source: "b", target: "t", batch: "x" })!;
    expect(h.past).toEqual([{ sequence: "seq", revision: 6, canvas: before, batch: "x", count: 2 }]);
    expect(undo(h)!.present, "撤一下,两根线都没了").toBe(before);
  });
});

describe("多选之后拉出来新建一格", () => {
  it("只列每一格都连得上的那几种:有分组框就一种都不列,有便签就不列时间线", () => {
    const kinds = ["image", "video", "sequence"] as const;
    expect(spawnableFor([cell("a", "image"), cell("b", "video")], kinds)).toEqual(["image", "video", "sequence"]);
    expect(spawnableFor([cell("a", "image"), cell("n", "note")], kinds)).toEqual(["image", "video"]);
    expect(spawnableFor([cell("f", "frame")], kinds)).toEqual([]);
  });
});
