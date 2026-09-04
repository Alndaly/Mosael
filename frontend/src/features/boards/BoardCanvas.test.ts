import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";

import { focusBoardNode } from "./BoardCanvas";

describe("画板节点聚焦", () => {
  it("一次点击就只选中目标节点", () => {
    const nodes = [
      { id: "old", selected: true },
      { id: "target", selected: false },
    ] as Node[];

    expect(focusBoardNode(nodes, "target").map((node) => [node.id, node.selected])).toEqual([
      ["old", false],
      ["target", true],
    ]);
  });

  it("目标已选中时保持对象稳定", () => {
    const target = { id: "target", selected: true } as Node;
    expect(focusBoardNode([target], "target")[0]).toBe(target);
  });
});
