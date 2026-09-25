import type { Edge, Node } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import type { BoardItem } from "@/api/client";
import { copySelected } from "./BoardCanvas";

const node = (item: BoardItem, selected = true): Node => ({
  id: item.id,
  type: item.kind,
  position: { x: item.x, y: item.y },
  selected,
  data: { item },
});
const itemOf = (one: Node) => (one.data as { item: BoardItem }).item;

describe("复制选中的几项", () => {
  it("一起复制的两项之间的那根线跟着复制,两端接到新的那两格上", () => {
    const note = node({ id: "n1", kind: "note", x: 0, y: 0, text: "一只猫" });
    const image = node({ id: "img", kind: "image", x: 300, y: 0 });
    const outside = node({ id: "other", kind: "note", x: 0, y: 300 }, false);
    const edges: Edge[] = [
      { id: "e1", source: "n1", target: "img" },
      { id: "e2", source: "other", target: "img" },
    ];

    const copied = copySelected([note, image, outside], edges);

    const fresh = copied.nodes.filter((one) => one.selected);
    const ids = new Map(fresh.map((one) => [itemOf(one).kind === "note" ? "n1" : "img", one.id]));
    // 原来那两根原样留着;复制出来的只多一根 —— 连着没被选中那项的线不跟着来。
    expect(copied.edges).toHaveLength(3);
    const added = copied.edges.find((one) => !["e1", "e2"].includes(one.id));
    expect(added).toMatchObject({ source: ids.get("n1"), target: ids.get("img") });
  });

  it("正在跑的那一格复制出来是空槽:任务的回执只认原件,副本会一直转圈", () => {
    const running = node({
      id: "img",
      kind: "image",
      x: 0,
      y: 0,
      form: { prompt: "一只猫" },
      run: { status: "running", job_id: "job-1" },
    });

    const copy = itemOf(copySelected([running], []).nodes.find((one) => one.id !== "img")!);

    expect(copy.run).toBeUndefined();
    expect(copy.form).toEqual({ prompt: "一只猫" });
  });

  it("便签正在写的那一格同样不把「写作中」带过去", () => {
    const writing = node({ id: "n1", kind: "note", x: 0, y: 0, text: "", run: { status: "running" } });

    const copy = itemOf(copySelected([writing], []).nodes.find((one) => one.id !== "n1")!);

    expect(copy.run).toBeUndefined();
  });

  it("槽位里顺着线挂上的那一份,上游一起复制了就改记成新的那一格;没一起复制的原样交给服务端去摘", () => {
    const upstream = node({ id: "A", kind: "image", x: 0, y: 0, asset_id: "a1" });
    const video = node({
      id: "V",
      kind: "video",
      x: 300,
      y: 0,
      form: { source_assets: [{ asset_id: "a1", role: "first_frame", from: "A" }, { asset_id: "m1", role: "last_frame" }] },
    });

    const both = copySelected([upstream, video], [{ id: "e1", source: "A", target: "V" }]);
    const fresh = both.nodes.filter((one) => one.selected);
    const newA = fresh.find((one) => itemOf(one).kind === "image")!.id;
    const newV = itemOf(fresh.find((one) => itemOf(one).kind === "video")!);
    expect(newV.form?.source_assets).toEqual([
      { asset_id: "a1", role: "first_frame", from: newA },
      { asset_id: "m1", role: "last_frame" },
    ]);
    expect(both.edges.some((one) => one.source === newA && one.target === newV.id)).toBe(true);

    const alone = copySelected([node(itemOf(upstream), false), video], [{ id: "e1", source: "A", target: "V" }]);
    const copy = itemOf(alone.nodes.find((one) => one.selected)!);
    expect(copy.form?.source_assets?.[0]).toEqual({ asset_id: "a1", role: "first_frame", from: "A" });
  });
});
