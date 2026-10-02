import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Clip, Track } from "@/api/client";
import { clipEnd } from "@/domain/timeline/geometry";
import { stackedSubtitleText, textLayers } from "@/features/editor/playback/textLayers";

/**
 * 文字层契约的前端一侧:跑 contracts/text-layer-cases.json —— 后端 tests/test_text_layer_parity.py
 * 跑的是**同一份文件**。改语义时先改语料,看着两侧一起红,再改两侧实现。
 *
 * subtitle_frames 是导出烧进成片的那几段。预览不切段:Monitor 每一刻取在场的字幕(左闭右开,和它的
 * 场景键 monitorSceneKey 同一个判据)交给 stackedSubtitleText 合成一框。所以这里按段取样 —— 每段的起点、
 * 中点、终点前一刻、终点,以及最前和最后之外 —— 看此刻合成出来的字是不是那一段(段外就是空)。
 */
const CONTRACT_PATH = fileURLToPath(new URL("../../../../../contracts/text-layer-cases.json", import.meta.url));

type Frame = { start: number; end: number; text: string };

type ContractCase = {
  name: string;
  why: string;
  tracks: unknown[];
  expected: { subtitles: string[]; titles: string[]; subtitle_lanes: Record<string, number>; subtitle_frames: Frame[] };
};

const contract = JSON.parse(readFileSync(CONTRACT_PATH, "utf-8")) as {
  contract: string;
  version: number;
  cases: ContractCase[];
};

/** 预览此刻画的那一框字:和 Monitor 一样,先取 t 时刻在场的字幕,再合成。 */
function previewTextAt(subtitles: Clip[], lanes: Record<string, number>, t: number): string {
  return stackedSubtitleText(
    subtitles.filter((clip) => clip.timeline_start <= t && t < clipEnd(clip)),
    lanes,
  );
}

function samples(frames: Frame[]): number[] {
  const times = frames.flatMap((frame) => [frame.start, (frame.start + frame.end) / 2, frame.end - 1e-3, frame.end]);
  return [-1, ...times, Math.max(0, ...frames.map((frame) => frame.end)) + 1];
}

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

      const frames = testCase.expected.subtitle_frames;
      for (const t of samples(frames)) {
        const frame = frames.find((one) => one.start <= t && t < one.end);
        expect(previewTextAt(layers.subtitles, layers.subtitleLanes, t), `${testCase.why}(t = ${t})`).toBe(frame?.text ?? "");
      }
    });
  }
});
