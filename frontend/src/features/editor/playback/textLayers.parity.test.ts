import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Track } from "@/api/client";
import { textLayers } from "@/features/editor/playback/textLayers";

/**
 * 文字层契约的前端一侧:跑 contracts/text-layer-cases.json —— 后端 tests/test_text_layer_parity.py
 * 跑的是**同一份文件**。改语义时先改语料,看着两侧一起红,再改两侧实现。
 */
const CONTRACT_PATH = fileURLToPath(new URL("../../../../../contracts/text-layer-cases.json", import.meta.url));

type ContractCase = {
  name: string;
  why: string;
  tracks: unknown[];
  expected: { subtitles: string[]; titles: string[]; subtitle_lanes: Record<string, number> };
};

const contract = JSON.parse(readFileSync(CONTRACT_PATH, "utf-8")) as {
  contract: string;
  version: number;
  cases: ContractCase[];
};

describe("text-layer contract", () => {
  it("corpus is present and versioned", () => {
    expect(contract.contract).toBe("text-layers");
    expect(typeof contract.version).toBe("number");
    expect(contract.cases.length).toBeGreaterThan(0);
  });

  for (const testCase of contract.cases) {
    it(testCase.name, () => {
      const layers = textLayers(testCase.tracks as Track[]);
      const actual = {
        subtitles: layers.subtitles.map((clip) => clip.id).sort(),
        titles: layers.titles.map((clip) => clip.id).sort(),
        subtitle_lanes: layers.subtitleLanes,
      };
      const expected = {
        subtitles: [...testCase.expected.subtitles].sort(),
        titles: [...testCase.expected.titles].sort(),
        subtitle_lanes: testCase.expected.subtitle_lanes,
      };
      expect(actual, testCase.why).toEqual(expected);
    });
  }
});
