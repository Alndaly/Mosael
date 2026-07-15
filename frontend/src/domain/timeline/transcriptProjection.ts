/**
 * Transcript projection (plan §14.5): the transcript view is a projection of
 * asset transcripts through clip source ranges — never a second edit state.
 * Pure functions only.
 */

export interface ProjectableClip {
  id: string;
  asset_id: string | null;
  timeline_start: number;
  src_in: number;
  src_out: number;
}

export interface TokenLike {
  start_time: number;
  end_time: number;
  text: string;
}

export interface SegmentLike {
  id: string;
  start_time: number;
  end_time: number;
  text: string;
  speaker?: string | null;
  tokens?: TokenLike[];
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
  /** Tokens fully visible through the clip window, in source time. */
  tokens: TokenLike[];
}

export function projectTranscript(
  clips: ProjectableClip[],
  segmentsByAsset: Map<string, SegmentLike[]>,
): ProjectedSegment[] {
  const projected: ProjectedSegment[] = [];
  const ordered = [...clips].sort((a, b) => a.timeline_start - b.timeline_start);
  for (const clip of ordered) {
    const segments = clip.asset_id ? (segmentsByAsset.get(clip.asset_id) ?? []) : [];
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
        tokens: (segment.tokens ?? []).filter(
          (token) => token.start_time >= clip.src_in && token.end_time <= clip.src_out,
        ),
      });
    }
  }
  return projected;
}

/* ---------- Silence & filler detection ---------- */

export interface SilenceGap {
  clipId: string;
  srcStart: number;
  srcEnd: number;
  timelineStart: number;
  duration: number;
}

/**
 * Gaps inside a clip's source window where no transcript speech happens.
 * Uses token timing when present, segment bounds otherwise.
 */
export function detectSilences(
  clips: ProjectableClip[],
  segmentsByAsset: Map<string, SegmentLike[]>,
  minGap = 0.6,
): SilenceGap[] {
  const gaps: SilenceGap[] = [];
  const ordered = [...clips].sort((a, b) => a.timeline_start - b.timeline_start);
  for (const clip of ordered) {
    const segments = clip.asset_id ? (segmentsByAsset.get(clip.asset_id) ?? []) : [];
    if (segments.length === 0) continue;
    const speech: Array<[number, number]> = [];
    for (const segment of segments) {
      const intervals: TokenLike[] =
        segment.tokens && segment.tokens.length > 0
          ? segment.tokens
          : [{ start_time: segment.start_time, end_time: segment.end_time, text: segment.text }];
      for (const item of intervals) {
        const start = Math.max(item.start_time, clip.src_in);
        const end = Math.min(item.end_time, clip.src_out);
        if (end > start) speech.push([start, end]);
      }
    }
    speech.sort((a, b) => a[0] - b[0]);
    let cursor = clip.src_in;
    const push = (from: number, to: number) => {
      if (to - from >= minGap) {
        gaps.push({
          clipId: clip.id,
          srcStart: from,
          srcEnd: to,
          timelineStart: clip.timeline_start + (from - clip.src_in),
          duration: to - from,
        });
      }
    };
    for (const [start, end] of speech) {
      push(cursor, start);
      cursor = Math.max(cursor, end);
    }
    push(cursor, clip.src_out);
  }
  return gaps;
}

const FILLER_WORDS = new Set([
  "呃", "嗯", "唔", "啊这", "那个", "这个那个", "就是说", "然后就是",
  "um", "uh", "uhm", "er", "erm", "hmm", "like", "you know",
]);

export function isFillerToken(text: string): boolean {
  return FILLER_WORDS.has(text.trim().toLowerCase().replace(/[,。,.!?!?]/g, ""));
}
