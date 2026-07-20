import { MutationCache } from "@tanstack/react-query";

/**
 * A failed mutation must never be silent.
 *
 * api() throws on any non-2xx, and roughly fifty mutations across the app defined no onError at
 * all, so those failures produced nothing: no toast, no console entry, no change on screen. That
 * is indistinguishable from a dead button, and it cost real time — "the track buttons do
 * nothing" and "a provider misconfiguration shows no error" were both this, and in neither case
 * was the failure where it appeared to be.
 *
 * One cache-level handler covers every mutation at once. Two escape hatches, in priority order:
 *
 *   - a mutation with its own `onError` keeps full control and the fallback stands aside, so
 *     nothing double-toasts and no existing call site had to change;
 *   - `meta: { silentError: true }` opts out entirely, for the rare failure that genuinely does
 *     not concern the user.
 */
export function createMutationCache(report: (message: string) => void): MutationCache {
  return new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (mutation.options.onError || mutation.meta?.silentError) return;
      const message = error instanceof Error ? error.message : String(error);
      report(message.slice(0, 300) || "操作失败");
    },
  });
}
