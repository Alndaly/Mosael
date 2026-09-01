import type { TranscriptCue } from "./shared/types";

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
