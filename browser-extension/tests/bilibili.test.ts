import { describe, expect, it } from "vitest";

import { listBilibiliTranscriptTracks, normalizeBilibiliTranscript } from "../src/platforms/bilibili";


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

  it("places a human subtitle before an AI subtitle", () => {
    expect(listBilibiliTranscriptTracks([
      { id: 1, lan: "zh-CN", lan_doc: "中文（自动）", ai_type: 1, subtitle_url: "//ai.test" },
      { id: 2, lan: "en", lan_doc: "English", ai_type: 0, subtitle_url: "//human.test" },
    ])).toEqual([
      {
        id: "bilibili:source:2",
        language: "en",
        languageLabel: "English",
        kind: "source",
        url: "//human.test",
      },
      {
        id: "bilibili:source:1",
        language: "zh-CN",
        languageLabel: "中文（自动）",
        kind: "source",
        url: "//ai.test",
      },
    ]);
  });
});
