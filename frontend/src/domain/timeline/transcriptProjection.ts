/**
 * Transcript projection (plan §14.5): the transcript view is a projection of
 * asset transcripts through clip source ranges — never a second edit state.
 * Pure functions only.
 */

export interface ProjectableClip {
  id: string;
  asset_id: string;
  timeline_start: number;
  src_in: number;
  src_out: number;
}

export interface SegmentLike {
  id: string;
  start_time: number;
  end_time: number;
  text: string;
  speaker?: string | null;
}

export interface ProjectedSegment {
  segmentId: string;
  clipId: string;
  text: string;
  speaker: string | null;
  /** Segment bounds mapped onto the sequence timeline, clamped to the clip. */
  timelineStart: number;
  timelineEnd: number;
  /** Visible portion in asset source time — what a transcript edit removes. */
  srcStart: number;
  srcEnd: number;
  /** True when the clip trims into the middle of this segment. */
  clipped: boolean;
}

export function projectTranscript(
  clips: ProjectableClip[],
  segmentsByAsset: Map<string, SegmentLike[]>,
): ProjectedSegment[] {
  const projected: ProjectedSegment[] = [];
  const ordered = [...clips].sort((a, b) => a.timeline_start - b.timeline_start);
  for (const clip of ordered) {
    const segments = segmentsByAsset.get(clip.asset_id) ?? [];
    for (const segment of segments) {
      if (segment.end_time <= clip.src_in || segment.start_time >= clip.src_out) continue;
      const visibleStart = Math.max(segment.start_time, clip.src_in);
      const visibleEnd = Math.min(segment.end_time, clip.src_out);
      projected.push({
        segmentId: segment.id,
        clipId: clip.id,
        text: segment.text,
        speaker: segment.speaker ?? null,
        timelineStart: clip.timeline_start + (visibleStart - clip.src_in),
        timelineEnd: clip.timeline_start + (visibleEnd - clip.src_in),
        srcStart: visibleStart,
        srcEnd: visibleEnd,
        clipped: segment.start_time < clip.src_in || segment.end_time > clip.src_out,
      });
    }
  }
  return projected;
}
