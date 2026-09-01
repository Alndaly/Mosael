import { describe, expect, it } from "vitest";

import { normalizeBilibiliTranscript } from "../src/platforms/bilibili";


describe("normalizeBilibiliTranscript", () => {
  it("keeps the server timestamps and removes empty subtitle rows", () => {
    const cues = normalizeBilibiliTranscript({
      body: [
        { from: 0.45, to: 2.1, content: "  第一行  " },
        { from: 2.1, to: 2.3, content: "  " },
        { from: 2.3, to: 4.8, content: "第二行\n继续" },
      ],
    });

    expect(cues).toEqual([
      { start: 0.45, end: 2.1, text: "第一行" },
      { start: 2.3, end: 4.8, text: "第二行 继续" },
    ]);
  });
});
