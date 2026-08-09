import { describe, expect, it } from "vitest";

import { pendingTranscribeIds } from "@/features/editor/transcribeQueue";

describe("要转哪些素材", () => {
  it("跳过已经有逐字稿的 —— 重转一遍只是浪费一次真实调用", () => {
    const done = new Set(["a", "c"]);
    expect(pendingTranscribeIds(["a", "b", "c", "d"], (id) => done.has(id))).toEqual(["b", "d"]);
  });

  it("全都转过了就没得转", () => {
    expect(pendingTranscribeIds(["a"], () => true)).toEqual([]);
  });

  it("按时间线顺序 —— 先转到的先能读", () => {
    expect(pendingTranscribeIds(["c", "a", "b"], () => false)).toEqual(["c", "a", "b"]);
  });
});
