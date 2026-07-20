import { describe, expect, it } from "vitest";

import { evictions, type Parked } from "./sourcePool";

const MB = 1024 * 1024;
const p = (id: string, mb: number): Parked => ({ id, retainedBytes: mb * MB });

describe("idle decoder-source pool", () => {
  it("keeps everything while under budget", () => {
    expect(evictions([p("a", 10), p("b", 20)], 96 * MB)).toEqual([]);
  });

  it("evicts oldest-first, and only as many as it takes", () => {
    // 40+30+30 = 100 over a 64MB budget. Dropping just the oldest leaves 60, which fits — so
    // "b" and "c" must survive. Evicting more than necessary would throw away a decoder we are
    // about to need again.
    expect(evictions([p("a", 40), p("b", 30), p("c", 30)], 64 * MB)).toEqual(["a"]);
  });

  it("keeps going when one eviction is not enough", () => {
    // 50+50+50 = 150 against 64MB: one drop leaves 100, two leave 50.
    expect(evictions([p("a", 50), p("b", 50), p("c", 50)], 64 * MB)).toEqual(["a", "b"]);
  });

  it("stops as soon as it is back under budget", () => {
    expect(evictions([p("a", 100), p("b", 5)], 64 * MB)).toEqual(["a"]);
  });

  it("counts bytes, not entries — one long proxy can outweigh several short ones", () => {
    const many = [p("s1", 4), p("s2", 4), p("s3", 4), p("s4", 4)];
    expect(evictions(many, 96 * MB)).toEqual([]);
    expect(evictions([p("long", 400)], 96 * MB)).toEqual(["long"]);
  });

  it("evicts an entry bigger than the whole budget rather than pinning it forever", () => {
    expect(evictions([p("huge", 500)], 96 * MB)).toEqual(["huge"]);
  });

  it("handles an empty pool", () => {
    expect(evictions([], 96 * MB)).toEqual([]);
  });
});
