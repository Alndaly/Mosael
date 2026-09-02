import type { TranscriptCue } from "./shared/types";

export type TranscriptTokenInput = {
  start_time?: number;
  end_time?: number;
  text?: string;
};

export type TranscriptSegmentInput = TranscriptTokenInput & {
  tokens?: TranscriptTokenInput[];
};

const MAX_CUE_DURATION_SECONDS = 8;
const MAX_CUE_DISPLAY_UNITS = 48;
const SOFT_BREAK_DISPLAY_UNITS = 28;
const PAUSE_BREAK_SECONDS = 0.75;
const SENTENCE_END = /[.!?。！？…]["'”’）)\]]*$/u;
const SOFT_PUNCTUATION = /[,，;；:：、]["'”’）)\]]*$/u;
const NO_SPACE_BEFORE = /^[,.;:!?，。；：！？、…%％）)\]}”’]/u;
const NO_SPACE_AFTER = /[(（\[{“‘]$/u;
const TRAILING_SEPARATOR = /^[,.;:!?，。；：！？、…%％）)\]}”’]+$/u;
const CJK = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;

type ValidToken = { start: number; end: number; text: string };

function validToken(value: TranscriptTokenInput): ValidToken | null {
  const start = Number(value.start_time);
  const end = Number(value.end_time);
  const text = String(value.text || "").trim();
  if (!Number.isFinite(start) || !Number.isFinite(end) || !text) return null;
  return { start: Math.max(0, start), end: Math.max(Math.max(0, start), end), text };
}

function appendToken(text: string, next: string): string {
  if (!text) return next;
  return `${text}${transcriptTokensNeedSpace(text, next) ? " " : ""}${next}`;
}

export function transcriptTokensNeedSpace(previous: string, next: string): boolean {
  const previousCharacter = Array.from(previous).at(-1) || "";
  const nextCharacter = Array.from(next)[0] || "";
  return !(NO_SPACE_BEFORE.test(next) || NO_SPACE_AFTER.test(previous)
    || CJK.test(previousCharacter) || CJK.test(nextCharacter));
}

function displayUnits(text: string): number {
  return Array.from(text).reduce((total, character) => {
    if (/\s/u.test(character)) return total;
    return total + (CJK.test(character) ? 2 : 1);
  }, 0);
}

function restoreSegmentPunctuation(tokens: ValidToken[], segmentText: string): ValidToken[] {
  if (tokens.length === 0 || !segmentText.trim()) return tokens;
  const source = segmentText.trim();
  const searchable = source.toLocaleLowerCase();
  const restored = tokens.map((token) => ({ ...token }));
  let cursor = 0;

  for (let index = 0; index < restored.length; index += 1) {
    const token = restored[index];
    const needle = token.text.toLocaleLowerCase();
    const position = searchable.indexOf(needle, cursor);
    if (position < cursor) return tokens;
    const separator = source.slice(cursor, position).trim();
    if (separator) {
      if (index > 0 && TRAILING_SEPARATOR.test(separator)) restored[index - 1].text += separator;
      else token.text = `${separator}${token.text}`;
    }
    cursor = position + needle.length;
  }

  const trailing = source.slice(cursor).trim();
  if (trailing && TRAILING_SEPARATOR.test(trailing)) restored[restored.length - 1].text += trailing;
  return restored;
}

function tokensToCues(tokens: ValidToken[]): TranscriptCue[] {
  const cues: TranscriptCue[] = [];
  let line: ValidToken[] = [];
  let text = "";

  const flush = () => {
    if (line.length === 0 || !text) return;
    cues.push({
      start: line[0].start,
      end: line[line.length - 1].end,
      text,
      tokens: line.map((token) => ({ ...token })),
    });
    line = [];
    text = "";
  };

  tokens.forEach((token, index) => {
    line.push(token);
    text = appendToken(text, token.text);
    const next = tokens[index + 1];
    const duration = token.end - line[0].start;
    const pause = next ? next.start - token.end : 0;
    const units = displayUnits(text);
    const shouldBreak = !next
      || SENTENCE_END.test(text)
      || pause >= PAUSE_BREAK_SECONDS
      || duration >= MAX_CUE_DURATION_SECONDS
      || units >= MAX_CUE_DISPLAY_UNITS
      || (units >= SOFT_BREAK_DISPLAY_UNITS && SOFT_PUNCTUATION.test(text));
    if (shouldBreak) flush();
  });

  return cues;
}

function splitFallbackText(text: string): string[] {
  const lines: string[] = [];
  let line = "";
  const flush = () => {
    const value = line.trim();
    if (value) lines.push(value);
    line = "";
  };

  for (const character of Array.from(text.trim())) {
    line += character;
    const units = displayUnits(line);
    if (
      SENTENCE_END.test(line)
      || (units >= MAX_CUE_DISPLAY_UNITS && (SOFT_PUNCTUATION.test(line) || /\s/u.test(character)))
      || units >= MAX_CUE_DISPLAY_UNITS * 1.25
    ) flush();
  }
  flush();
  return lines;
}

function fallbackSegmentToCues(segment: ValidToken): TranscriptCue[] {
  const lines = splitFallbackText(segment.text);
  if (lines.length <= 1) return [{ start: segment.start, end: segment.end, text: segment.text }];
  const weights = lines.map((line) => Math.max(1, displayUnits(line)));
  const total = weights.reduce((sum, value) => sum + value, 0);
  const duration = segment.end - segment.start;
  let consumed = 0;
  return lines.map((text, index) => {
    const start = segment.start + duration * (consumed / total);
    consumed += weights[index];
    const end = index === lines.length - 1
      ? segment.end
      : segment.start + duration * (consumed / total);
    return { start, end, text };
  });
}

/**
 * Convert ASR storage segments into navigation-friendly transcript rows. Word alignment is the
 * source of truth when available; provider-sized paragraphs are only a compatibility fallback.
 */
export function transcriptSegmentsToCues(segments: TranscriptSegmentInput[]): TranscriptCue[] {
  return segments.flatMap((segment) => {
    const tokens = (segment.tokens || [])
      .map(validToken)
      .filter((token): token is ValidToken => token !== null)
      .sort((left, right) => left.start - right.start);
    if (tokens.length > 0) return tokensToCues(restoreSegmentPunctuation(tokens, String(segment.text || "")));
    const fallback = validToken(segment);
    return fallback ? fallbackSegmentToCues(fallback) : [];
  });
}

function baseLanguage(value: string): string {
  return value.trim().toLocaleLowerCase().split(/[-_]/, 1)[0] || "";
}

export function languageMatches(available: string, requested: string): boolean {
  const left = available.trim().toLocaleLowerCase().replace(/_/g, "-");
  const right = requested.trim().toLocaleLowerCase().replace(/_/g, "-");
  return Boolean(left && right && (left === right || baseLanguage(left) === baseLanguage(right)));
}

/**
 * Project a second subtitle track onto the source timeline. Subtitle providers segment the
 * same sentence differently, so array indexes are not meaningful; temporal overlap is.
 */
export function alignSecondaryCues(source: TranscriptCue[], secondary: TranscriptCue[]): string[] {
  return source.map((cue) => {
    const matches = secondary.filter((candidate) => candidate.end > cue.start && candidate.start < cue.end);
    if (matches.length > 0) return matches.map((candidate) => candidate.text).join(" ");
    const midpoint = (cue.start + cue.end) / 2;
    const nearest = secondary.reduce<TranscriptCue | null>((best, candidate) => {
      const distance = Math.abs((candidate.start + candidate.end) / 2 - midpoint);
      const bestDistance = best ? Math.abs((best.start + best.end) / 2 - midpoint) : Number.POSITIVE_INFINITY;
      return distance < bestDistance ? candidate : best;
    }, null);
    return nearest && Math.abs((nearest.start + nearest.end) / 2 - midpoint) <= 1 ? nearest.text : "";
  });
}
