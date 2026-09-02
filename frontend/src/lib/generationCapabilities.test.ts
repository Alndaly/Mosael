/**
 * 参数控件由**模型的描述符**决定,不由 kind 写死。
 *
 * 这条防的 bug 很具体:视频那一支此前把参数名写死成 `resolution` / `aspect_ratio` /
 * `first_frame`,于是一个声明了 `size` 的模型 —— 万相就是 —— 在界面上**连尺寸这一栏都不出现**,
 * 发出去的参数里也没有它。描述符说了话而界面没听,而那套描述符存在的全部意义就是让界面照着它渲染。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { describe, expect, it } from "vitest";

import {
  booleanParameterKeys,
  defaultDuration,
  durationChoices,
  durationOptions,
  parseGenerationParameterInput,
  parameterChoiceEntries,
  sizeOptions,
  supportsParameter,
  videoResolutionOptions,
} from "@/lib/generationCapabilities";

type Model = Parameters<typeof sizeOptions>[0];

const wan = {
  kind: "video",
  capabilities: {
    parameter_keys: ["duration_seconds", "size", "first_frame"],
    sizes: ["832*480", "1280*720"],
    duration_seconds: [5],
  },
} as unknown as Model;

const seedance = {
  kind: "video",
  capabilities: {
    parameter_keys: ["duration_seconds", "resolution", "first_frame"],
    resolutions: ["480p", "720p", "1080p"],
    duration_seconds: [5, 10],
  },
} as unknown as Model;

describe("尺寸这一栏跟着描述符走", () => {
  it("声明了 size 的**视频**模型也有尺寸可选", () => {
    expect(supportsParameter(wan, "size")).toBe(true);
    expect(sizeOptions(wan)).toEqual(["832*480", "1280*720"]);
  });

  it("没声明 size 的视频模型不该凭空多出一栏", () => {
    expect(supportsParameter(seedance, "size")).toBe(false);
    expect(sizeOptions(seedance)).toEqual([]);
  });

  it("两家各拿各的那一档,互不干扰", () => {
    expect(videoResolutionOptions(seedance)).toEqual(["480p", "720p", "1080p"]);
    expect(videoResolutionOptions(wan)).toEqual([]);
    expect(durationOptions(wan)).toEqual([5]);
    expect(durationOptions(seedance)).toEqual([5, 10]);
  });

  it("视频模型不给尺寸兜底 —— 猜一个出来比不给更糟", () => {
    /** 图像有一组人人都认的常见尺寸,可以兜底;视频没有 ——
     *  猜出来的档位选中之后会被供应商拒掉,而用户以为那是能用的。 */
    const bare = { kind: "video", capabilities: { parameter_keys: ["size"] } } as unknown as Model;
    expect(sizeOptions(bare)).toEqual([]);
  });

  it("没有 parameter_keys 就不猜测参数能力", () => {
    const incomplete = { kind: "image", capabilities: {} } as unknown as Model;
    expect(supportsParameter(incomplete, "size")).toBe(false);
    expect(supportsParameter(incomplete, "anything")).toBe(false);
  });

  it("明确为空的 parameter_keys 表示未知能力_不能再猜默认参数", () => {
    const unknown = {
      kind: "video",
      capabilities: { modes: ["text-to-video"], parameter_keys: [] },
    } as unknown as Model;
    expect(supportsParameter(unknown, "duration_seconds")).toBe(false);
    expect(supportsParameter(unknown, "resolution")).toBe(false);
    expect(durationChoices(unknown)).toEqual([]);
    expect(videoResolutionOptions(unknown)).toEqual([]);
  });

  it("区间时长与自动值可以同时表达", () => {
    const automatic = {
      kind: "video",
      capabilities: {
        parameter_keys: ["duration_seconds"],
        duration_seconds: [],
        duration_special_values: [-1],
        min_duration_seconds: 4,
        max_duration_seconds: 6,
        default_duration_seconds: -1,
      },
    } as unknown as Model;
    expect(durationChoices(automatic)).toEqual([-1, 4, 5, 6]);
    expect(defaultDuration(automatic)).toBe(-1);
  });

  it("分辨率可以进一步收窄时长选项", () => {
    const veo = {
      kind: "video",
      capabilities: {
        parameter_keys: ["duration_seconds", "resolution"],
        duration_seconds: [4, 6, 8],
        duration_by_resolution: { "1080p": [8], "4k": [8] },
      },
    } as unknown as Model;
    expect(durationChoices(veo, "720p")).toEqual([4, 6, 8]);
    expect(durationChoices(veo, "1080p")).toEqual([8]);
    expect(durationChoices(veo, "4k")).toEqual([8]);
  });

  it("生成声音开关与仅能输出声音是两件事", () => {
    const switchable = { capabilities: { parameter_keys: ["duration_seconds"], supports_generate_audio: true } } as unknown as Model;
    const outputOnly = { capabilities: { parameter_keys: ["duration_seconds"], supports_audio: true } } as unknown as Model;
    expect(supportsParameter(switchable, "generate_audio")).toBe(true);
    expect(supportsParameter(outputOnly, "generate_audio")).toBe(false);
  });

  it("布尔控件来自描述符而不是前端硬编码", () => {
    const model = {
      capabilities: {
        parameter_keys: ["prompt_extend", "camera_fixed"],
        boolean_parameters: ["prompt_extend", "camera_fixed"],
      },
    } as unknown as Model;
    expect(booleanParameterKeys(model)).toEqual(["prompt_extend", "camera_fixed"]);
  });

  it("供应商枚举参数直接从描述符读取", () => {
    const model = {
      capabilities: {
        parameter_keys: ["quality", "output_format"],
        parameter_choices: { quality: ["auto", "high"], output_format: ["png", "webp"] },
      },
    } as unknown as Model;
    expect(parameterChoiceEntries(model)).toEqual([
      ["quality", ["auto", "high"]],
      ["output_format", ["png", "webp"]],
    ]);
  });

  it("工作流布尔值不保留为真值字符串", () => {
    expect(parseGenerationParameterInput("false")).toBe(false);
    expect(parseGenerationParameterInput("true")).toBe(true);
    expect(parseGenerationParameterInput("-1")).toBe(-1);
  });
});
