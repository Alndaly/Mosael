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
    expect(merged.items.map((one) => one.id)).toEqual(["a", "mine", "theirs"]);
    //: c 被服务端删了,连着它的那根本地新线没有一头可接。
    expect(merged.edges.map((one) => one.id)).toEqual(["a->theirs"]);
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
