/**
 * Which decoder sources to keep alive when they leave the screen.
 *
 * Closing a source the moment its clip stops being under the playhead meant scrubbing back
 * across a cut re-fetched and re-parsed the whole proxy. Parking a few instead makes crossing
 * a boundary free in both directions.
 *
 * The budget is in BYTES, not entries: one long proxy costs far more than several short ones,
 * so a count-based cap would either pin hundreds of megabytes or evict uselessly early.
 *
 * Kept separate from the component so the policy can be tested without a canvas.
 */

export interface Parked {
  id: string;
  retainedBytes: number;
}

/**
 * Given the parked sources in least-recently-parked-first order, return the ids to close so the
 * total falls back within budget. Oldest go first; an entry larger than the whole budget is
 * still evicted rather than pinned forever.
 */
export function evictions(parked: readonly Parked[], budgetBytes: number): string[] {
  let total = 0;
  for (const item of parked) total += item.retainedBytes;
  const doomed: string[] = [];
  for (const item of parked) {
    if (total <= budgetBytes) break;
    total -= item.retainedBytes;
    doomed.push(item.id);
  }
  return doomed;
}
