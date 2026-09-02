import { describe, expect, it } from "vitest";

import {
  listBilibiliTranscriptTracks,
  normalizeBilibiliTranscript,
  readBilibiliTranscript,
} from "../src/platforms/bilibili";


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

  it("refreshes the signed subtitle URL instead of reusing a stale page listing", async () => {
    const requested: string[] = [];
    const transcript = await readBilibiliTranscript({
      bvid: "BV-current",
      cid: "42",
      fetchText: async (url) => {
        requested.push(url);
        if (url.includes("/x/player/v2")) {
          return JSON.stringify({
            data: {
              subtitle: {
                subtitles: [{ id: 9, lan: "zh-CN", lan_doc: "中文", subtitle_url: "//aisubtitle.hdslb.com/bfs/ai_subtitle/current.json" }],
              },
            },
          });
        }
        return JSON.stringify({ body: [{ from: 1, to: 2, content: "当前视频字幕" }] });
      },
    });

    expect(requested[0]).toContain("bvid=BV-current&cid=42");
    expect(requested[1]).toBe("https://aisubtitle.hdslb.com/bfs/ai_subtitle/current.json");
    expect(transcript.cues).toEqual([{ start: 1, end: 2, text: "当前视频字幕" }]);
  });
});
