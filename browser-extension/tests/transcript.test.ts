import { describe, expect, it } from "vitest";

import { alignSecondaryCues, languageMatches, transcriptSegmentsToCues } from "../src/transcript";

describe("bilingual transcript alignment", () => {
  it("maps differently segmented secondary subtitles onto the source timeline", () => {
    const source = [
      { start: 0, end: 2, text: "Hello" },
      { start: 2, end: 4, text: "world" },
      { start: 4, end: 7, text: "Goodbye" },
    ];
    const secondary = [
      { start: 0.1, end: 1.1, text: "你" },
      { start: 1.1, end: 3.8, text: "好，世界" },
      { start: 4.2, end: 6.8, text: "再见" },
    ];

    expect(alignSecondaryCues(source, secondary)).toEqual(["你 好，世界", "好，世界", "再见"]);
  });

  it("matches regional language codes to the requested language", () => {
    expect(languageMatches("zh-Hans", "zh-CN")).toBe(true);
    expect(languageMatches("en-US", "en")).toBe(true);
    expect(languageMatches("ja", "ko")).toBe(false);
  });
});

describe("generated transcript cue shaping", () => {
  it("uses word timestamps to split paragraph-sized ASR segments into readable timed lines", () => {
    const cues = transcriptSegmentsToCues([
      {
        start_time: 0,
        end_time: 5,
        text: "所以我们打开设置。然后来到网络。",
        tokens: [
          { start_time: 0, end_time: 0.4, text: "所以" },
          { start_time: 0.4, end_time: 0.9, text: "我们" },
          { start_time: 0.9, end_time: 1.5, text: "打开" },
          { start_time: 1.5, end_time: 2.1, text: "设置" },
          { start_time: 2.4, end_time: 2.9, text: "然后" },
          { start_time: 2.9, end_time: 3.5, text: "来到" },
          { start_time: 3.5, end_time: 4.2, text: "网络" },
        ],
      },
    ]);

    expect(cues).toEqual([
      {
        start: 0,
        end: 2.1,
        text: "所以我们打开设置。",
        tokens: [
          { start: 0, end: 0.4, text: "所以" },
          { start: 0.4, end: 0.9, text: "我们" },
          { start: 0.9, end: 1.5, text: "打开" },
          { start: 1.5, end: 2.1, text: "设置。" },
        ],
      },
      {
        start: 2.4,
        end: 4.2,
        text: "然后来到网络。",
        tokens: [
          { start: 2.4, end: 2.9, text: "然后" },
          { start: 2.9, end: 3.5, text: "来到" },
          { start: 3.5, end: 4.2, text: "网络。" },
        ],
      },
    ]);
  });

  it("splits on a meaningful pause even without punctuation", () => {
    const cues = transcriptSegmentsToCues([
      {
        start_time: 0,
        end_time: 4,
        text: "hello world again",
        tokens: [
          { start_time: 0, end_time: 0.5, text: "hello" },
          { start_time: 0.5, end_time: 1, text: "world" },
          { start_time: 2, end_time: 2.5, text: "again" },
        ],
      },
    ]);

    expect(cues).toEqual([
      {
        start: 0,
        end: 1,
        text: "hello world",
        tokens: [
          { start: 0, end: 0.5, text: "hello" },
          { start: 0.5, end: 1, text: "world" },
        ],
      },
      { start: 2, end: 2.5, text: "again", tokens: [{ start: 2, end: 2.5, text: "again" }] },
    ]);
  });

  it("falls back to segment timing for transcripts produced without word alignment", () => {
    expect(transcriptSegmentsToCues([
      { start_time: 1.2, end_time: 3.5, text: "Legacy transcript" },
    ])).toEqual([{ start: 1.2, end: 3.5, text: "Legacy transcript" }]);
  });

  it("still breaks legacy paragraph segments into sentence-sized transcript rows", () => {
    expect(transcriptSegmentsToCues([
      { start_time: 0, end_time: 4, text: "第一句。第二句。" },
    ])).toEqual([
      { start: 0, end: 2, text: "第一句。" },
      { start: 2, end: 4, text: "第二句。" },
    ]);
  });
});
