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
  /** Playback rate. Source seconds are NOT timeline seconds when this isn't 1 — see srcToTimeline. */
  speed?: number;
}

/**
 * A source time inside the clip → where it lands on the sequence timeline.
 *
 * Dividing by speed is the whole point: at 2× a word 10s into the source plays 5s into the clip.
 * Mapping without it put every transcript word (and every detected silence) progressively further
 * off on any speed-adjusted clip — clicking a word seeked to the wrong place, and silence ranges
 * highlighted the wrong stretch of timeline.
 */
function srcToTimeline(clip: ProjectableClip, srcTime: number): number {
  return clip.timeline_start + (srcTime - clip.src_in) / (clip.speed || 1);
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

const SENTENCE_END = /[.!?。！？…]["'”’）)\]]*\s*$/u;
const SOFT_PUNCTUATION = /[,，;；:：、]["'”’）)\]]*\s*$/u;
const CJK = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;
const MAX_SENTENCE_SECONDS = 8;
const MAX_SENTENCE_UNITS = 48;
const SOFT_BREAK_UNITS = 28;
const PAUSE_BREAK_SECONDS = 0.75;

function displayUnits(text: string): number {
  return Array.from(text).reduce((total, character) => {
    if (/\s/u.test(character)) return total;
    return total + (CJK.test(character) ? 2 : 1);
  }, 0);
}

/**
 * ASR providers keep punctuation in the paragraph text but often omit it from word timings. The
 * editor renders timed words so they remain clickable; carry the exact separators (including
 * English spaces) onto the preceding token instead of choosing between timing and readable text.
 */
function restoreTokenFormatting(tokens: TokenLike[], segmentText: string): TokenLike[] {
  if (tokens.length === 0 || !segmentText.trim()) return tokens;
  const source = segmentText.trim();
  const searchable = source.toLocaleLowerCase();
  const restored = tokens.map((token) => ({ ...token, text: token.text.trim() }));
  let cursor = 0;

  for (let index = 0; index < restored.length; index += 1) {
    const token = restored[index];
    const needle = token.text.toLocaleLowerCase();
    if (!needle) return tokens;
    const position = searchable.indexOf(needle, cursor);
    if (position < cursor) return tokens;
    const separator = source.slice(cursor, position);
    if (separator) {
      if (index > 0) restored[index - 1].text += separator;
      else token.text = `${separator}${token.text}`;
    }
    cursor = position + needle.length;
  }

  const trailing = source.slice(cursor);
  if (trailing) restored[restored.length - 1].text += trailing;
  return restored;
}

function fallbackParagraphSegments(segment: SegmentLike): SegmentLike[] {
  const parts = segment.text.match(/.*?[.!?。！？…](?:["'”’）)\]]+)?(?:\s+|$)|.+$/gu)
    ?.map((part) => part.trim())
    .filter(Boolean) ?? [];
  if (parts.length <= 1) return [segment];
  const weights = parts.map((part) => Math.max(1, displayUnits(part)));
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  const duration = segment.end_time - segment.start_time;
  let consumed = 0;
  return parts.map((text, index) => {
    const start = segment.start_time + duration * (consumed / total);
    consumed += weights[index];
    const end = index === parts.length - 1
      ? segment.end_time
      : segment.start_time + duration * (consumed / total);
    return { ...segment, id: `${segment.id}:${index}`, start_time: start, end_time: end, text };
  });
}

/** Convert provider-sized ASR paragraphs into stable, navigation-friendly editing rows. */
export function transcriptSegmentsForEditing(segments: SegmentLike[]): SegmentLike[] {
  return segments.flatMap((segment) => {
    const ordered = [...(segment.tokens ?? [])]
      .filter((token) => token.end_time > token.start_time && token.text.trim())
      .sort((left, right) => left.start_time - right.start_time);
    if (ordered.length === 0) return fallbackParagraphSegments(segment);

    const tokens = restoreTokenFormatting(ordered, segment.text);
    const rows: Array<{ tokens: TokenLike[]; text: string }> = [];
    let row: TokenLike[] = [];
    let text = "";
    const flush = () => {
      const rowText = text.trim();
      if (row.length > 0 && rowText) rows.push({ tokens: row, text: rowText });
      row = [];
      text = "";
    };

    tokens.forEach((token, index) => {
      row.push(token);
      text += token.text;
      const next = tokens[index + 1];
      const duration = token.end_time - row[0].start_time;
      const pause = next ? next.start_time - token.end_time : 0;
      const units = displayUnits(text);
      if (
        !next
        || SENTENCE_END.test(text)
        || pause >= PAUSE_BREAK_SECONDS
        || duration >= MAX_SENTENCE_SECONDS
        || units >= MAX_SENTENCE_UNITS
        || (units >= SOFT_BREAK_UNITS && SOFT_PUNCTUATION.test(text))
      ) flush();
    });

    if (rows.length <= 1) return [{ ...segment, tokens, text: segment.text.trim() || rows[0]?.text || "" }];
    return rows.map((item, index) => ({
      ...segment,
      id: `${segment.id}:${index}`,
      start_time: index === 0 ? segment.start_time : item.tokens[0].start_time,
      end_time: index === rows.length - 1 ? segment.end_time : item.tokens[item.tokens.length - 1].end_time,
      text: item.text,
      tokens: item.tokens,
    }));
  });
}

export function projectTranscript(
  clips: ProjectableClip[],
  segmentsByAsset: Map<string, SegmentLike[]>,
): ProjectedSegment[] {
  const projected: ProjectedSegment[] = [];
  const ordered = [...clips].sort((a, b) => a.timeline_start - b.timeline_start);
  for (const clip of ordered) {
    const segments = clip.asset_id
      ? transcriptSegmentsForEditing(segmentsByAsset.get(clip.asset_id) ?? [])
      : [];
    for (const segment of segments) {
      if (segment.end_time <= clip.src_in || segment.start_time >= clip.src_out) continue;
      const visibleStart = Math.max(segment.start_time, clip.src_in);
      const visibleEnd = Math.min(segment.end_time, clip.src_out);
      projected.push({
        segmentId: segment.id,
        clipId: clip.id,
        text: segment.text,
        speaker: segment.speaker ?? null,
        timelineStart: srcToTimeline(clip, visibleStart),
        timelineEnd: srcToTimeline(clip, visibleEnd),
        srcStart: visibleStart,
        srcEnd: visibleEnd,
        clipped: segment.start_time < clip.src_in || segment.end_time > clip.src_out,
        // Keep every token that intersects the clip window (clamped) — the old
        // fully-inside filter silently dropped words at trimmed edges, leaving
        // whole sentences without word-level editing.
        tokens: (segment.tokens ?? [])
          .filter((token) => token.end_time > clip.src_in && token.start_time < clip.src_out)
          .map((token) => ({
            ...token,
            start_time: Math.max(token.start_time, clip.src_in),
            end_time: Math.min(token.end_time, clip.src_out),
          })),
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
          timelineStart: srcToTimeline(clip, from),
          // 时间线上的实际时长(变速后源秒数 ≠ 时间线秒数)——UI 用它画区间宽度。
          duration: (to - from) / (clip.speed || 1),
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
  return FILLER_WORDS.has(text.trim().toLowerCase().replace(/[，。！？、,.;:!?…]/gu, ""));
}
