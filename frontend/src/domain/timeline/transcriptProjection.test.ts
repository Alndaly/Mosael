import { describe, expect, it } from "vitest";

import { detectSilences, isFillerToken, projectTranscript, transcriptSegmentsForEditing, type SegmentLike } from "./transcriptProjection";

const seg = (id: string, start: number, end: number, text: string): SegmentLike => ({
  id,
  start_time: start,
  end_time: end,
  text,
});

const clip = (id: string, assetId: string, start: number, srcIn: number, srcOut: number) => ({
  id,
  asset_id: assetId,
  timeline_start: start,
  src_in: srcIn,
  src_out: srcOut,
});

describe("projectTranscript", () => {
  const segments = new Map([["a1", [seg("s1", 0, 2, "hello"), seg("s2", 2, 4, "world"), seg("s3", 5, 6, "tail")]]]);

  it("keeps only segments overlapping the clip src range and maps to timeline time", () => {
    const result = projectTranscript([clip("c1", "a1", 10, 1, 3)], segments);
    expect(result.map((r) => r.segmentId)).toEqual(["s1", "s2"]);
    // s1 visible from src 1..2 → timeline 10..11, clipped at its head
    expect(result[0].timelineStart).toBe(10);
    expect(result[0].timelineEnd).toBe(11);
    expect(result[0].clipped).toBe(true);
    // s2 visible from src 2..3 → timeline 11..12, clipped at its tail
    expect(result[1].timelineStart).toBe(11);
    expect(result[1].clipped).toBe(true);
  });

  it("marks fully contained segments as not clipped", () => {
    const result = projectTranscript([clip("c1", "a1", 0, 0, 6)], segments);
    expect(result.every((r) => !r.clipped)).toBe(true);
  });

  it("orders projection by clip timeline position across clips", () => {
    const result = projectTranscript(
      [clip("late", "a1", 20, 0, 2), clip("early", "a1", 0, 2, 4)],
      segments,
    );
    expect(result.map((r) => r.clipId)).toEqual(["early", "late"]);
    expect(result[0].segmentId).toBe("s2");
    expect(result[1].segmentId).toBe("s1");
  });

  it("returns nothing for assets without transcripts", () => {
    expect(projectTranscript([clip("c1", "missing", 0, 0, 5)], segments)).toEqual([]);
  });

  it("restores punctuation and spaces from segment text before rendering timed tokens", () => {
    const source = new Map<string, SegmentLike[]>([["a1", [{
      id: "punctuated",
      start_time: 0,
      end_time: 3,
      text: "你好。 Hello world!",
      tokens: [
        { start_time: 0, end_time: 0.4, text: "你" },
        { start_time: 0.4, end_time: 0.8, text: "好" },
        { start_time: 1, end_time: 1.5, text: "Hello" },
        { start_time: 1.6, end_time: 2.2, text: "world" },
      ],
    }]]]);

    const result = projectTranscript([clip("c1", "a1", 0, 0, 3)], source);

    expect(result).toHaveLength(2);
    expect(result.map((sentence) => sentence.text)).toEqual(["你好。", "Hello world!"]);
    expect(result.map((sentence) => sentence.tokens.map((token) => token.text).join(""))).toEqual([
      "你好。 ",
      "Hello world!",
    ]);
  });

  it("turns provider-sized paragraphs into readable rows at pauses", () => {
    const source = new Map<string, SegmentLike[]>([["a1", [{
      id: "paragraph",
      start_time: 0,
      end_time: 20,
      text: "first part second part",
      tokens: [
        { start_time: 0, end_time: 1, text: "first" },
        { start_time: 1.1, end_time: 2, text: "part" },
        { start_time: 4, end_time: 5, text: "second" },
        { start_time: 5.1, end_time: 6, text: "part" },
      ],
    }]]]);

    const result = projectTranscript([clip("c1", "a1", 0, 0, 20)], source);

    expect(result.map((sentence) => sentence.text)).toEqual(["first part", "second part"]);
    expect(new Set(result.map((sentence) => sentence.segmentId)).size).toBe(2);
  });
});

describe("detectSilences", () => {
  const clip = { id: "c1", asset_id: "a1", timeline_start: 2, src_in: 0, src_out: 10 };

  it("finds gaps between token speech intervals", () => {
    const segments = new Map([
      [
        "a1",
        [
          {
            id: "s1",
            start_time: 1,
            end_time: 4,
            text: "hello world",
            tokens: [
              { start_time: 1, end_time: 2, text: "hello" },
              { start_time: 3.5, end_time: 4, text: "world" },
            ],
          },
          { id: "s2", start_time: 6, end_time: 9, text: "again" },
        ],
      ],
    ]);
    const gaps = detectSilences([clip], segments, 0.6);
    expect(gaps.map((g) => [g.srcStart, g.srcEnd])).toEqual([
      [0, 1],
      [2, 3.5],
      [4, 6],
      [9, 10],
    ]);
    expect(gaps[0].timelineStart).toBe(2);
  });

  it("respects the minimum gap", () => {
    const segments = new Map([["a1", [{ id: "s1", start_time: 0, end_time: 9.7, text: "x" }]]]);
    expect(detectSilences([clip], segments, 0.6)).toEqual([]);
  });
});

describe("isFillerToken", () => {
  it("matches Chinese and English fillers, ignoring punctuation and case", () => {
    expect(isFillerToken("呃")).toBe(true);
    expect(isFillerToken("嗯,")).toBe(true);
    expect(isFillerToken("嗯，")).toBe(true);
    expect(isFillerToken("Um")).toBe(true);
    expect(isFillerToken("hello")).toBe(false);
  });
});

describe("token clamping at clip edges", () => {
  it("keeps and clamps tokens that straddle the clip window", () => {
    const clip = { id: "c1", asset_id: "a1", timeline_start: 0, src_in: 1.0, src_out: 3.0 };
    const segments = new Map<string, SegmentLike[]>([
      [
        "a1",
        [
          {
            id: "s1",
            start_time: 0.5,
            end_time: 3.5,
            text: "abcd",
            tokens: [
              { start_time: 0.5, end_time: 0.9, text: "a" }, // fully outside → dropped
              { start_time: 0.8, end_time: 1.4, text: "b" }, // straddles src_in → clamped
              { start_time: 1.5, end_time: 2.0, text: "c" }, // inside → kept
              { start_time: 2.8, end_time: 3.4, text: "d" }, // straddles src_out → clamped
            ],
          },
        ],
      ],
    ]);
    const projected = projectTranscript([clip], segments);
    const tokens = projected.flatMap((sentence) => sentence.tokens);
    expect(tokens.map((t) => t.text)).toEqual(["b", "c", "d"]);
    expect(tokens[0]).toMatchObject({ start_time: 1.0, end_time: 1.4 });
    expect(tokens[2]).toMatchObject({ start_time: 2.8, end_time: 3.0 });
  });
});

describe("speed-adjusted clips (source seconds ≠ timeline seconds)", () => {
  const segments = new Map([["a1", [seg("s1", 0, 2, "hello"), seg("s2", 2, 4, "world")]]]);

  it("maps transcript segments through playback speed", () => {
    // 2× :源 0..4 只占时间线 2s。s1(源 0..2)→ 时间线 10..11;s2(源 2..4)→ 11..12
    const fast = { ...clip("c1", "a1", 10, 0, 4), speed: 2 };
    const result = projectTranscript([fast], segments);
    expect(result.map((r) => [r.timelineStart, r.timelineEnd])).toEqual([
      [10, 11],
      [11, 12],
    ]);
  });

  it("maps at half speed too (source stretches on the timeline)", () => {
    const slow = { ...clip("c1", "a1", 0, 0, 4), speed: 0.5 };
    const result = projectTranscript([slow], segments);
    expect(result.map((r) => [r.timelineStart, r.timelineEnd])).toEqual([
      [0, 4],
      [4, 8],
    ]);
  });

  it("keeps speed=1 and missing speed identical (no regression)", () => {
    const plain = projectTranscript([clip("c1", "a1", 10, 0, 4)], segments);
    const explicit = projectTranscript([{ ...clip("c1", "a1", 10, 0, 4), speed: 1 }], segments);
    expect(explicit).toEqual(plain);
  });

  it("places silences and their durations in timeline time", () => {
    // 语音 0..1 与 3..4,中间 1..3 静音;2× → 时间线上从 +0.5 起、长 1s
    const speech = new Map([
      ["a1", [{ ...seg("s1", 0, 4, "x"), tokens: [
        { start_time: 0, end_time: 1, text: "a" },
        { start_time: 3, end_time: 4, text: "b" },
      ] }]],
    ]);
    const fast = { ...clip("c1", "a1", 0, 0, 4), speed: 2 };
    const gaps = detectSilences([fast], speech, 0.5);
    expect(gaps).toHaveLength(1);
    expect(gaps[0].srcStart).toBe(1);
    expect(gaps[0].timelineStart).toBe(0.5);
    expect(gaps[0].duration).toBe(1);
  });
});

describe("兜底切分(没有词级时间戳时)", () => {
  const clip = { id: "c1", asset_id: "a1", timeline_start: 0, src_in: 0, src_out: 60 };
  // 一整段中文,句号后不空格 —— ASR 直出与 AI 修复后最常见的形状。
  const chinese = "小小玲珑,但功能异常强大。由于我有很多张手机卡,但出门只带一部手机。出门在外需要用电脑工作。";

  it("中文段落按句号切开,不再退化成一整块", () => {
    const rows = transcriptSegmentsForEditing([
      { id: "s1", start_time: 0, end_time: 30, text: chinese, tokens: [] },
    ]);
    expect(rows.map((row) => row.text)).toEqual([
      "小小玲珑,但功能异常强大。",
      "由于我有很多张手机卡,但出门只带一部手机。",
      "出门在外需要用电脑工作。",
    ]);
    // 时长按字数权重分摊,首尾锚在原段边界上。
    expect(rows[0].start_time).toBe(0);
    expect(rows[rows.length - 1].end_time).toBe(30);
  });

  it("英文小数不被当成句号", () => {
    const rows = transcriptSegmentsForEditing([
      { id: "s1", start_time: 0, end_time: 10, text: "The value is 3.5 and 0.8 overall.", tokens: [] },
    ]);
    expect(rows).toHaveLength(1);
  });

  it("句末的中文引号跟着上一句走", () => {
    const rows = transcriptSegmentsForEditing([
      { id: "s1", start_time: 0, end_time: 10, text: "他说「很好。」然后走了。", tokens: [] },
    ]);
    expect(rows.map((row) => row.text)).toEqual(["他说「很好。」", "然后走了。"]);
  });

  it("有词级时间戳时切得比按标点更细 —— 生成字幕必须走这条路", () => {
    // 逐字稿页与生成字幕读同一个接口;两边都带 tokens,结果才会是同一份。
    const tokens = [
      { start_time: 0, end_time: 1, text: "小小" },
      { start_time: 1, end_time: 2, text: "玲珑" },
      // 停顿 ≥ 0.75s 就断句,即使这里一个句号都没有。
      { start_time: 3, end_time: 4, text: "但功能" },
      { start_time: 4, end_time: 5, text: "异常强大" },
    ];
    const rows = transcriptSegmentsForEditing([
      { id: "s1", start_time: 0, end_time: 5, text: "小小玲珑但功能异常强大", tokens },
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0].text).toBe("小小玲珑");
    expect(rows[1].text).toBe("但功能异常强大");
  });

  it("投影到时间线后,句数与逐字稿页一致", () => {
    const withTokens = projectTranscript([clip], new Map([["a1", [
      { id: "s1", start_time: 0, end_time: 30, text: chinese, tokens: [] },
    ]]]));
    expect(withTokens).toHaveLength(3);
  });
});
