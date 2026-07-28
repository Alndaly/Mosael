import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Asset, Clip, Track } from "@/api/client";
import { sceneLayersAt } from "@/features/editor/playback/sceneModel";

/**
 * The frontend half of the scene contract: runs contracts/scene-cases.json, the SAME file the
 * backend's tests/test_scene_parity.py runs.
 *
 * Preview and export cannot share one implementation — preview must evaluate locally at 60fps over
 * uncommitted drag drafts, export must stay headless, backend-side and claimable by an external
 * worker (ADR-0002). So the model necessarily exists in two languages, and agreement is enforced by
 * a language-neutral corpus instead of by shared code. Change the semantics in the corpus FIRST,
 * watch both sides go red, then fix both — patching an implementation and back-filling the corpus
 * demotes it to an echo of the code and protects nothing.
 */
const CONTRACT_PATH = fileURLToPath(new URL("../../../../../contracts/scene-cases.json", import.meta.url));

type ContractLayer = { clip: string; track: string; isBase: boolean };
type ContractCase = {
  name: string;
  why?: string;
  assets: Record<string, { kind: string }>;
  tracks: unknown[];
  samples: { t: number; layers: ContractLayer[] }[];
};

const contract = JSON.parse(readFileSync(CONTRACT_PATH, "utf-8")) as {
  contract: string;
  version: number;
  cases: ContractCase[];
};

function assetMap(assets: Record<string, { kind: string }>): Map<string, Asset> {
  return new Map(Object.entries(assets).map(([id, a]) => [id, { id, ...a } as unknown as Asset]));
}

describe("scene contract", () => {
  it("corpus is present and versioned", () => {
    // A missing corpus that silently skips is the worst outcome: both sides "pass" with no contract run.
    expect(contract.contract).toBe("scene");
    expect(typeof contract.version).toBe("number");
    expect(contract.cases.length).toBeGreaterThan(0);
  });

  for (const testCase of contract.cases) {
    describe(testCase.name, () => {
      const tracks = testCase.tracks as unknown as Track[];
      const assets = assetMap(testCase.assets);

      for (const sample of testCase.samples) {
        it(`layers @ t=${sample.t}`, () => {
          const actual = sceneLayersAt(tracks, assets, sample.t).map((layer) => ({
            clip: (layer.clip as Clip).id,
            track: layer.trackId,
            isBase: layer.isBase,
          }));
          expect(actual, testCase.why).toEqual(sample.layers);
        });
      }
    });
  }
});
