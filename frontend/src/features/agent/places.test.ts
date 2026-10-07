import { describe, expect, it } from "vitest";

import { comfyParts, comfyPlace, placeFromKey, placeKey, samePlace, type AgentPlace } from "./places";

describe("地方和它的键", () => {
  const places: AgentPlace[] = [
    { kind: "studio", id: "" },
    { kind: "project", id: "p1" },
    { kind: "note", id: "n1" },
    { kind: "board", id: "b1" },
    { kind: "workflow", id: "w1" },
    { kind: "scene", id: "s1" },
    { kind: "comfyui", id: "c1/人像/qwen 编辑.json" },
    { kind: "comfyui", id: "c1#workflows/Unsaved Workflow (2).json" },
    { kind: "comfyui", id: "c1" },
  ];

  it("每种地方 ↔ 键来回一致", () => {
    for (const place of places) expect(placeFromKey(placeKey(place))).toEqual(place);
    expect(new Set(places.map(placeKey)).size).toBe(places.length);
  });

  it("ComfyUI 的三种 id 切得开 —— 从左边第一个 / 或 # 切,路径里再带 #、/ 也行", () => {
    expect(comfyParts("c1/a/b#c.json")).toEqual({ connection: "c1", path: "a/b#c.json", key: "" });
    expect(comfyParts("c1#workflows/x/y.json")).toEqual({ connection: "c1", path: "", key: "workflows/x/y.json" });
    expect(comfyParts("c1")).toEqual({ connection: "c1", path: "", key: "" });
  });

  it("工作台那一处:存过的认路径,没存过的认标签页 key,一张都没开就是连接", () => {
    expect(comfyPlace("c1", { path: "a.json", key: "workflows/a.json" })).toEqual({ kind: "comfyui", id: "c1/a.json" });
    expect(comfyPlace("c1", { path: "", key: "workflows/Unsaved Workflow.json" })).toEqual({
      kind: "comfyui", id: "c1#workflows/Unsaved Workflow.json",
    });
    expect(comfyPlace("c1", null)).toEqual({ kind: "comfyui", id: "c1" });
    expect(samePlace(comfyPlace("c1", null), { kind: "comfyui", id: "c1" })).toBe(true);
  });
});
