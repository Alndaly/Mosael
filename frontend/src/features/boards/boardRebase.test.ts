import { describe, expect, it } from "vitest";

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { rebaseCanvas } from "@/features/boards/boardRebase";

const note = (id: string, extra: Partial<BoardItem> = {}): BoardItem => ({ id, kind: "note", x: 0, y: 0, text: "", ...extra });
const canvas = (items: BoardItem[], edges: Canvas["edges"] = []): Canvas => ({ items, edges, markers: [] });

describe("本地没存的改动重放到服务端最新那一版上", () => {
  it("同一格:本地改的字段用本地的,服务端改的字段用服务端的 —— 拖了一格、它的产出同时落下,两样都在", () => {
    const slot: BoardItem = { id: "img", kind: "image", x: 0, y: 0, run: { status: "running", job_id: "j" } };
    const { canvas: merged, conflicted } = rebaseCanvas(
      canvas([slot]),
      canvas([{ ...slot, x: 120 }]),
      canvas([{ ...slot, asset_id: "a1", run: { status: "succeeded" } }]),
    );
    expect(merged.items).toEqual([{ id: "img", kind: "image", x: 120, y: 0, asset_id: "a1", run: { status: "succeeded" } }]);
    expect(conflicted).toBe(false);
  });

  it("本地加的、删的照本地;服务端加的、删的照服务端;线跟着两头走", () => {
    const base = canvas([note("a"), note("b"), note("c")], [{ id: "a->b", source: "a", target: "b" }]);
    const mine = canvas([note("a"), note("c"), note("mine")], [{ id: "c->mine", source: "c", target: "mine" }]);
    const theirs = canvas(
      [note("a"), note("b"), note("theirs")],
      [{ id: "a->b", source: "a", target: "b" }, { id: "a->theirs", source: "a", target: "theirs" }],
    );
    const { canvas: merged } = rebaseCanvas(base, mine, theirs);
    //: 服务端新加的按它在服务端那份里的位置插(接在它前面、本地也在的那一格后面),本地新加的照本地的位置。
    expect(merged.items.map((one) => one.id)).toEqual(["a", "theirs", "mine"]);
    //: c 被服务端删了,连着它的那根本地新线没有一头可接。
    expect(merged.edges.map((one) => one.id)).toEqual(["a->theirs"]);
  });

  it("服务端插在宿主后面的几格(一次多张的其余几张):合好的顺序和服务端一样 —— 只是顺序不同不算本地改动,不多存一次", () => {
    const base = canvas([note("a"), note("img"), note("z")]);
    const theirs = canvas([note("a"), note("img"), note("img-2"), note("img-3"), note("z")]);
    expect(rebaseCanvas(base, base, theirs).canvas).toEqual(theirs);
    //: 本地拖了一格:顺序照样跟着服务端,只多那一处改动。
    const moved = rebaseCanvas(base, canvas([note("a"), note("img"), note("z", { x: 40 })]), theirs).canvas;
    expect(moved.items.map((one) => one.id)).toEqual(["a", "img", "img-2", "img-3", "z"]);
  });

  it("两边改了同一格的同一处、改得不一样:用本地的,并说一声", () => {
    const { canvas: merged, conflicted } = rebaseCanvas(
      canvas([note("n", { text: "原来" })]),
      canvas([note("n", { text: "我改的" })]),
      canvas([note("n", { text: "别人改的" })]),
    );
    expect(merged.items[0].text).toBe("我改的");
    expect(conflicted).toBe(true);
  });

  it("本地删掉了一个字段(换成笔记后不再引用原件):服务端那份上也删掉", () => {
    const doc: BoardItem = { id: "d", kind: "document", x: 0, y: 0, asset_id: "pdf" };
    const { canvas: merged } = rebaseCanvas(
      canvas([doc]),
      canvas([{ id: "d", kind: "document", x: 0, y: 0, note_id: "n1", note_revision: 1 }]),
      canvas([{ ...doc, y: 40 }]),
    );
    expect(merged.items[0]).toEqual({ id: "d", kind: "document", x: 0, y: 40, note_id: "n1", note_revision: 1 });
  });
});
