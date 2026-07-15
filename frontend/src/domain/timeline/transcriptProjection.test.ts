import { describe, expect, it } from "vitest";

import { detectSilences, isFillerToken, projectTranscript, type SegmentLike } from "./transcriptProjection";

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
    const [projected] = projectTranscript([clip], segments);
    expect(projected.tokens.map((t) => t.text)).toEqual(["b", "c", "d"]);
    expect(projected.tokens[0]).toMatchObject({ start_time: 1.0, end_time: 1.4 });
    expect(projected.tokens[2]).toMatchObject({ start_time: 2.8, end_time: 3.0 });
  });
});
