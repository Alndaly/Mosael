import { describe, expect, it } from "vitest";

import { batchLinks, linkRefusal, selectionSources, spawnableBefore, spawnableFor } from "@/features/boards/boardLinks";
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

describe("选区框的统一出口一次连到一格", () => {
  const at = (id: string, kind: Parameters<typeof cell>[1], x: number, y: number, selected = true) => ({ ...cell(id, kind, selected), x, y });

  it("选中两格以上才有:连出去的是其中连得出线的几格(分组框不算);只选一格没有(它用自己的出口)", () => {
    const cells = [at("a", "image", 0, 0), at("b", "image", 300, 0), at("f", "frame", -40, -40), at("c", "image", 600, 0, false)];
    expect(selectionSources(cells).map((one) => one.id)).toEqual(["a", "b"]);
    expect(selectionSources([at("a", "image", 0, 0), at("b", "image", 300, 0, false)]), "只选了一格").toEqual([]);
    expect(selectionSources([at("f", "frame", 0, 0), at("g", "frame", 300, 0)]), "选的全是分组框:一格都连不出").toEqual([]);
  });

  it("从左到右排(x 相同再按 y)—— 连进时间线格时照这个顺序一段一段接,不照节点数组的先后", () => {
    const cells = [at("right", "image", 600, 0), at("lower", "image", 0, 300), at("upper", "image", 0, 0), at("middle", "video", 300, 50)];
    expect(selectionSources(cells).map((one) => one.id)).toEqual(["upper", "lower", "middle", "right"]);
  });

  it("逐根按规矩判:连得上的照顺序交回;没连上的只数真连不上的 —— 已经连着的、终点自己都不算", () => {
    const sources = [cell("v", "video"), cell("n", "note"), cell("i", "image"), cell("t", "sequence")];
    const got = batchLinks(sources, cell("t", "sequence"), [{ source: "i", target: "t" }]);
    expect(got.links).toEqual([{ source: "v", target: "t" }]);
    expect(got.refused, "只有便签进不了时间线格;那张图已经连着,不算").toBe(1);
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

  it("从一格的入口拉出来(新的一格是它的上游):时间线格只长得出视频 / 图片 / 音频", () => {
    expect(spawnableBefore(cell("t", "sequence"), ["image", "video", "audio", "note", "document"] as const)).toEqual(["image", "video", "audio"]);
    expect(spawnableBefore(cell("i", "image"), ["note", "document"] as const)).toEqual(["note", "document"]);
  });
});
