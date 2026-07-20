import { MutationObserver, QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { createMutationCache } from "./mutationErrors";

/** Run one mutation against a client wired with the fallback, and report what it surfaced. */
async function runMutation(options: Record<string, unknown>): Promise<string[]> {
  const reported: string[] = [];
  const client = new QueryClient({
    mutationCache: createMutationCache((message) => reported.push(message)),
    defaultOptions: { mutations: { retry: false } },
  });
  const observer = new MutationObserver(client, options as never);
  await observer.mutate().catch(() => undefined);
  return reported;
}

const failing = { mutationFn: async () => Promise.reject(new Error("Track not found")) };

describe("mutation error fallback", () => {
  it("surfaces a failure that the call site ignores", async () => {
    // The default before this existed: ~50 mutations failed with nothing shown at all, which
    // looks exactly like a button that does nothing.
    expect(await runMutation(failing)).toEqual(["Track not found"]);
  });

  it("stands aside when the mutation handles its own error", async () => {
    const seen: string[] = [];
    const reported = await runMutation({
      ...failing,
      onError: (error: Error) => seen.push(error.message),
    });
    expect(seen).toEqual(["Track not found"]);
    expect(reported).toEqual([]); // no double toast
  });

  it("honours an explicit opt-out", async () => {
    expect(await runMutation({ ...failing, meta: { silentError: true } })).toEqual([]);
  });

  it("says nothing when the mutation succeeds", async () => {
    expect(await runMutation({ mutationFn: async () => "ok" })).toEqual([]);
  });

  it("handles a rejection that is not an Error", async () => {
    const reported = await runMutation({ mutationFn: async () => Promise.reject("plain string") });
    expect(reported).toEqual(["plain string"]);
  });

  it("truncates a huge message rather than rendering a wall of text", async () => {
    const reported = await runMutation({
      mutationFn: async () => Promise.reject(new Error("x".repeat(5000))),
    });
    expect(reported[0]).toHaveLength(300);
  });

  it("falls back to a readable message when the error carries none", async () => {
    expect(await runMutation({ mutationFn: async () => Promise.reject(new Error("")) })).toEqual([
      "操作失败",
    ]);
  });
});
