import { describe, expect, it } from "vitest";

import { projectTranscript, type SegmentLike } from "./transcriptProjection";

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
