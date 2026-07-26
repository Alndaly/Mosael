import { describe, expect, it } from "vitest";

import type { Asset, Clip, Track } from "@/api/client";
import { sceneLayersAt } from "./sceneModel";

// Minimal structural fixtures — only the fields sceneLayersAt reads, cast to the generated types.
const clip = (id: string, start: number, dur: number, assetId: string | null): Clip =>
  ({ id, timeline_start: start, src_in: 0, src_out: dur, speed: 1, asset_id: assetId }) as unknown as Clip;
const track = (kind: string, position: number, clips: Clip[], muted = false): Track =>
  ({ id: `t${position}`, kind, position, muted, clips }) as unknown as Track;
const assets = (...pairs: [string, "video" | "image"][]): Map<string, Asset> =>
  new Map(pairs.map(([id, kind]) => [id, { id, kind } as unknown as Asset]));

describe("sceneLayersAt", () => {
  it("returns the single base layer for one video track", () => {
    const tracks = [track("video", 0, [clip("c1", 0, 5, "a1")])];
    const layers = sceneLayersAt(tracks, assets(["a1", "video"]), 2);
    expect(layers.map((l) => l.clip.id)).toEqual(["c1"]);
    expect(layers[0].isBase).toBe(true);
  });

  it("orders base first then overlays bottom→top, base flagged only on the bottom track", () => {
    // positions ascending = top row first; bottom-most (highest position) is the base.
    const tracks = [
      track("video", 0, [clip("top", 0, 10, "a")]),
      track("video", 1, [clip("mid", 0, 10, "a")]),
      track("video", 2, [clip("base", 0, 10, "a")]),
    ];
    const layers = sceneLayersAt(tracks, assets(["a", "video"]), 3);
    // Draw order (array order) is bottom→top: base, then mid, then top on top.
    expect(layers.map((l) => l.clip.id)).toEqual(["base", "mid", "top"]);
    expect(layers.map((l) => l.isBase)).toEqual([true, false, false]);
  });

  it("drops layers whose clip is not active at t (half-open [start, end))", () => {
    const tracks = [track("video", 0, [clip("c", 2, 3, "a")])]; // active on [2,5)
    const at = (t: number) => sceneLayersAt(tracks, assets(["a", "video"]), t).map((l) => l.clip.id);
    expect(at(1.99)).toEqual([]);
    expect(at(2)).toEqual(["c"]);
    expect(at(4.99)).toEqual(["c"]);
    expect(at(5)).toEqual([]); // clipEnd is exclusive
  });

  it("keeps an overlay whose base track has no active clip (base shorter than overlay / gap)", () => {
    const tracks = [
      track("video", 0, [clip("ov", 0, 20, "a")]), // overlay track, long clip
      track("video", 1, [clip("base", 0, 5, "a")]), // base track, ends at 5
    ];
    // At t=10 the base has ended; only the overlay remains — and it must NOT be flagged base.
    const layers = sceneLayersAt(tracks, assets(["a", "video"]), 10);
    expect(layers.map((l) => l.clip.id)).toEqual(["ov"]);
    expect(layers[0].isBase).toBe(false);
  });

  it("excludes text clips (no asset_id) and unknown/non-visual assets", () => {
    const tracks = [
      track("video", 0, [clip("txt", 0, 10, null), clip("aud", 0, 10, "voice")]),
      track("video", 1, [clip("base", 0, 10, "a")]),
    ];
    const layers = sceneLayersAt(tracks, assets(["a", "video"], ["voice", "video"]), 3);
    // txt has no asset; "voice" resolves but is on the base's search only if active — here it's an
    // overlay clip that IS a video asset, so it stays. txt is excluded.
    expect(layers.map((l) => l.clip.id)).toEqual(["base", "aud"]);
  });

  it("composites images and videos alike", () => {
    const tracks = [
      track("video", 0, [clip("pic", 0, 10, "img")]),
      track("video", 1, [clip("base", 0, 10, "vid")]),
    ];
    const layers = sceneLayersAt(tracks, assets(["img", "image"], ["vid", "video"]), 3);
    expect(layers.map((l) => l.clip.id)).toEqual(["base", "pic"]);
    expect(layers.map((l) => l.asset.kind)).toEqual(["video", "image"]);
  });

  it("ignores non-video tracks and returns [] when there are none", () => {
    expect(sceneLayersAt([track("audio", 0, [clip("a", 0, 5, "x")])], assets(["x", "video"]), 1)).toEqual([]);
    expect(sceneLayersAt([], new Map(), 1)).toEqual([]);
  });

  it("shows a muted video track's picture (muting is audio-only)", () => {
    const tracks = [track("video", 0, [clip("c", 0, 5, "a")], true)];
    expect(sceneLayersAt(tracks, assets(["a", "video"]), 2).map((l) => l.clip.id)).toEqual(["c"]);
  });
});
