import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import type { Asset, Track } from "@/api/client";
import { audioGainAt, buildAudioSources } from "./audioMix";
const contract = JSON.parse(readFileSync(new URL("../../../../../contracts/audio-mix-cases.json", import.meta.url), "utf8"));
for (const c of contract.cases) {
  it(c.name, () => {
    const tracks = c.clips.map((clip: Record<string, unknown>) => ({ id: clip.id, kind: "audio", solo: clip.solo, duck: clip.duck, clips: [{ asset_id: "a", timeline_start: 0, src_in: 0, speed: 1, gain: 1, ...clip }] })) as Track[];
    const sources = buildAudioSources(tracks, new Map([["a", { id: "a", kind: "audio" } as Asset]]));
    for (const sample of c.samples) for (const source of sources) {
      expect(audioGainAt(source, sources, sample.t)).toBeCloseTo(sample.gains[source.key], 6);
      expect(audioGainAt(source, sources, sample.t, 0.5)).toBeCloseTo(sample.gains[source.key] * 0.5, 6);
      expect(audioGainAt(source, sources, sample.t, 1, true)).toBe(0);
    }
  });
}
