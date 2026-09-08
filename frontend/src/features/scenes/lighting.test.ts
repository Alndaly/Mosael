/**
 * 打光预设与它交给模型的那段话。
 *
 * 这一套的价值全在"**灯位和文字是配套的**":灯位渲进参考帧说"光从哪来",文字说"这是什么光"。
 * 任何一半悄悄失效,症状都只是"生成出来的光不对",而那种问题没人会去查代码。
 */
import { describe, expect, it } from "vitest";

import {
  CUSTOM_PRESET,
  LIGHTING_PRESETS,
  kelvinRgb,
  lightingPrompt,
  presetById,
  presetGroups,
} from "./lighting";

describe("预设表", () => {
  it("每一档都配了提示词 —— 少一句就等于那一档只有一半", () => {
    for (const preset of LIGHTING_PRESETS) {
      expect(preset.prompt.trim(), preset.id).not.toBe("");
      expect(preset.hint.trim(), preset.id).not.toBe("");
    }
  });

  it("id 不重复,否则 presetById 会静默取到第一个", () => {
    const ids = LIGHTING_PRESETS.map((preset) => preset.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("按用途分组,而且同组的挨在一起", () => {
    // presetGroups 按**相邻**归组(顺序是有意排的,默认档在最前)。隔开写会渲染出两个
    // 同名小标题 —— 插件那边的「添加」菜单刚栽过这一下。
    const groups = presetGroups().map(([name]) => name);
    expect(new Set(groups).size).toBe(groups.length);
    expect(groups.length).toBeGreaterThanOrEqual(3);
  });

  it("默认那一档在最前", () => {
    expect(LIGHTING_PRESETS[0].id).toBe("studio-soft");
  });
});

describe("交给模型的那段话", () => {
  it("选了预设就用它写好的那句", () => {
    const preset = presetById("golden-hour")!;
    expect(lightingPrompt({ preset: "golden-hour", ...preset.values })).toBe(preset.prompt);
  });

  it("手动调过之后按当时的数现生成 —— 不能什么都不说", () => {
    // 「什么都不说」会让模型自己发挥打光,而那正是这一整套要消除的。
    const text = lightingPrompt({
      preset: CUSTOM_PRESET,
      azimuth: 180,
      elevation: 10,
      intensity: 6,
      temperature: 2800,
      softness: 0.05,
    });
    expect(text).toContain("后方");
    expect(text).toContain("低角度");
    expect(text).toContain("暖色调");
    expect(text).toContain("锐利");
  });

  it("认不出的预设 id 也要给出一句话", () => {
    // 老场景存着一个后来删掉的预设 id 时,不能退化成空字符串。
    expect(lightingPrompt({ preset: "removed-preset", azimuth: 35, elevation: 55,
                            intensity: 2.5, temperature: 5500, softness: 0.35 })).not.toBe("");
  });
});

describe("色温", () => {
  it("暖的偏红、冷的偏蓝,中性大致持平", () => {
    const [warmR, , warmB] = kelvinRgb(2000);
    expect(warmR).toBeGreaterThan(warmB);
    const [coolR, , coolB] = kelvinRgb(10000);
    expect(coolB).toBeGreaterThan(coolR);
    const [r, g, b] = kelvinRgb(6500);
    expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(0.25);
  });

  it("超出范围的输入不会算出 NaN 或越界", () => {
    for (const kelvin of [0, -100, 1e9]) {
      for (const channel of kelvinRgb(kelvin)) {
        expect(Number.isFinite(channel)).toBe(true);
        expect(channel).toBeGreaterThanOrEqual(0);
        expect(channel).toBeLessThanOrEqual(1);
      }
    }
  });
});
