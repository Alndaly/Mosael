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
  declaredParameters,
  declaredParameterValue,
  defaultDuration,
  durationChoices,
  durationOptions,
  hasEnoughText,
  parseGenerationParameterInput,
  parameterChoiceEntries,
  promptMode,
  promptToSend,
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

/**
 * 模型**自己声明的**参数(插件生成供应商,ADR 0020):ComfyUI 的一张工作流有它自己的采样器、步数。
 * 三个界面照同一份声明渲染,不认识 ComfyUI,也不为它开分支。
 */
describe("模型自己声明的参数", () => {
  const comfy = {
    kind: "image",
    capabilities: {
      parameter_keys: ["seed", "3.steps", "3.sampler_name", "3.denoise", "9.filename_prefix", "reference_image"],
      parameter_schema: {
        "3.denoise": { type: "number", title: "KSampler · denoise", default: 1, minimum: 0, maximum: 1, multipleOf: 0.01, "x-advanced": true },
        "3.steps": { type: "integer", title: "KSampler · steps", default: 20, minimum: 1, maximum: 150 },
        "3.sampler_name": { type: "string", enum: ["euler", "dpmpp_2m"], default: "euler" },
        "9.filename_prefix": { type: "string", "x-multiline": true },
        // 声明了 schema 却不在 parameter_keys 里的不算:参数键是契约,schema 只是它的说明书
        "ghost": { type: "integer" },
        // 认不出的类型不渲染
        "3.weird": { type: "object" },
      },
    },
  } as unknown as Model;

  it("按声明给出控件所需的一切,常用的在前、高级的在后", () => {
    const parameters = declaredParameters(comfy);
    expect(parameters.map((one) => one.key)).toEqual(["3.steps", "3.sampler_name", "9.filename_prefix", "3.denoise"]);
    const [steps, sampler, prefix, denoise] = parameters;
    expect(steps).toMatchObject({ type: "integer", label: "KSampler · steps", defaultValue: 20, minimum: 1, maximum: 150, step: 1 });
    expect(sampler).toMatchObject({ label: "3.sampler_name", options: ["euler", "dpmpp_2m"], defaultValue: "euler" });
    expect(prefix).toMatchObject({ multiline: true, advanced: false });
    expect(denoise).toMatchObject({ advanced: true, step: 0.01 });
  });

  it("没声明 schema 的模型一个都没有 —— 内置模型不受影响", () => {
    expect(declaredParameters({ capabilities: { parameter_keys: ["size"] } } as unknown as Model)).toEqual([]);
    expect(declaredParameters(null)).toEqual([]);
  });

  it("值按声明的类型发出去;空 = 不发,让模型用它自己的默认", () => {
    const [steps, sampler] = declaredParameters(comfy);
    expect(declaredParameterValue(steps, "30.7")).toBe(30);
    expect(declaredParameterValue(steps, "")).toBeUndefined();
    expect(declaredParameterValue(steps, "abc")).toBeUndefined();
    // 声明成文本的,长得像数字也是文本 —— 否则提交时被校验器按类型拦下
    expect(declaredParameterValue({ ...sampler, options: [] }, "123")).toBe("123");
    expect(declaredParameterValue({ ...sampler, type: "boolean" }, "false")).toBe(false);
  });
});

describe("提示词要不要写(描述符的 prompt)", () => {
  const withPrompt = (prompt?: string, keys: string[] = []) =>
    ({ capabilities: { parameter_keys: keys, ...(prompt === undefined ? {} : { prompt }) } }) as unknown as Model;

  it("没说、说了认不出的值,都按要写;只认那三个值", () => {
    expect(promptMode(null)).toBe("required");
    expect(promptMode(withPrompt())).toBe("required");
    expect(promptMode(withPrompt("sometimes"))).toBe("required");
    expect(promptMode(withPrompt("optional"))).toBe("optional");
    expect(promptMode(withPrompt("none"))).toBe("none");
  });

  it("够不够提交:和后端 validate_text_inputs 同一套判据", () => {
    expect(hasEnoughText(withPrompt("none"), "")).toBe(true);
    expect(hasEnoughText(withPrompt("optional"), "")).toBe(true);
    expect(hasEnoughText(withPrompt(), "  ")).toBe(false);
    expect(hasEnoughText(withPrompt(), "一只猫")).toBe(true);
    // 会唱歌词的模型只给歌词也行;不会唱的给了也不算;纯音乐要描述
    expect(hasEnoughText(withPrompt(undefined, ["lyrics"]), "", "[Verse] 啦")).toBe(true);
    expect(hasEnoughText(withPrompt(), "", "[Verse] 啦")).toBe(false);
    expect(hasEnoughText(withPrompt(undefined, ["lyrics"]), "", "啦", true)).toBe(false);
  });

  it("不收提示词的模型发空串 —— 换模型之前框里写过的字不跟着发出去", () => {
    expect(promptToSend(withPrompt("none"), "上一个模型的提示词")).toBe("");
    expect(promptToSend(withPrompt("optional"), "更清楚")).toBe("更清楚");
    expect(promptToSend(withPrompt(), "一只猫")).toBe("一只猫");
  });
});
