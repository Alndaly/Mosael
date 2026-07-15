/**
 * Waveform helpers (pure). Peaks come from the backend cache covering the
 * whole asset; clips show only their src range.
 */

export function slicePeaks(
  peaks: number[],
  assetDuration: number,
  srcIn: number,
  srcOut: number,
): number[] {
  if (peaks.length === 0 || assetDuration <= 0 || srcOut <= srcIn) return [];
  const start = Math.max(0, Math.floor((srcIn / assetDuration) * peaks.length));
  const end = Math.min(peaks.length, Math.ceil((srcOut / assetDuration) * peaks.length));
  return peaks.slice(start, Math.max(end, start + 1));
}

/** Downsample (max-preserving) to at most target points for cheap rendering. */
export function downsamplePeaks(peaks: number[], target: number): number[] {
  if (peaks.length <= target || target <= 0) return peaks;
  const result: number[] = [];
  const step = peaks.length / target;
  for (let index = 0; index < target; index += 1) {
    const start = Math.floor(index * step);
    const end = Math.max(start + 1, Math.floor((index + 1) * step));
    let peak = 0;
    for (let cursor = start; cursor < end; cursor += 1) {
      if (peaks[cursor] > peak) peak = peaks[cursor];
    }
    result.push(peak);
  }
  return result;
}

/** SVG polygon points for a vertically mirrored waveform in a 0..1 box. */
export function waveformPolygonPoints(peaks: number[]): string {
  if (peaks.length === 0) return "";
  const n = peaks.length;
  const top = peaks.map((peak, index) => `${(index / (n - 1 || 1)).toFixed(4)},${(0.5 - peak / 2).toFixed(3)}`);
  const bottom = peaks
    .map((peak, index) => `${(index / (n - 1 || 1)).toFixed(4)},${(0.5 + peak / 2).toFixed(3)}`)
    .reverse();
  return [...top, ...bottom].join(" ");
}
