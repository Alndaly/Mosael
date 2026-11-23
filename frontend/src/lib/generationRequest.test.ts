/**
 * 生成请求参数的规则:**模型声明了 → 有值就发;没声明 → 一定不发**,不按种类分支。
 *
 * 这条规则此前抄了三份(AI 工作台、画板、工作流),其中 AI 工作台的图像分支从不发 `aspect_ratio` ——
 * 图像模型声明了宽高比,画板能选、工作台选不了。
 */
import { describe, expect, it } from "vitest";

import { DURATION_UNSET } from "@/lib/generationCapabilities";
import { requestParameters, type GenerationForm } from "@/lib/generationRequest";
import { emptyFrames } from "@/lib/sourceFrames";

type Model = Parameters<typeof requestParameters>[0];

function model(kind: string, parameterKeys: string[], extra: Record<string, unknown> = {}): Model {
  return { kind, capabilities: { parameter_keys: parameterKeys, ...extra } } as unknown as Model;
}

/** 每一栏都填上的表单:没声明的那些必须一个都不出现在结果里。 */
function fullForm(): GenerationForm {
  const frames = emptyFrames();
  frames.first_frame = [{ assetId: "", url: "https://example.test/a.png" }] as typeof frames.first_frame;
  return {
    size: "1024x1024",
    resolution: "2K",
    aspectRatio: "16:9",
    durationSeconds: 5,
    generateAudio: false,
    numImages: 3,
    seed: "42",
    instrumental: false,
    lyrics: "la la",
    frames,
  };
}

const HOST_PARAMETERS: Record<string, string> = {
  size: "size",
  resolution: "resolution",
  aspect_ratio: "aspect_ratio",
  duration_seconds: "duration_seconds",
  generate_audio: "generate_audio",
  num_images: "num_images",
  seed: "seed",
  instrumental: "instrumental",
  lyrics: "lyrics",
  first_frame: "first_frame_url",
};

describe("requestParameters:声明了才发", () => {
  it.each(Object.entries(HOST_PARAMETERS))("%s:声明了就发,没声明就不发", (declared, sent) => {
    const withIt = requestParameters(model("video", [declared], { max_images: 4 }), fullForm());
    expect(Object.keys(withIt)).toEqual([sent]);
    const without = requestParameters(model("video", []), fullForm());
    expect(without).toEqual({});
  });

  it("不按种类分支:图像模型声明了宽高比与带声,照样发(此前 AI 工作台从不发)", () => {
    const image = model("image", ["aspect_ratio", "generate_audio"]);
    expect(requestParameters(image, fullForm())).toEqual({ aspect_ratio: "16:9", generate_audio: false });
  });

  it("同一个模型,三处的表单值相同就得到同一份参数", () => {
    const video = model("video", ["aspect_ratio", "resolution", "duration_seconds", "generate_audio"]);
    const form: GenerationForm = { aspectRatio: "9:16", resolution: "720p", durationSeconds: 10, generateAudio: true };
    expect(requestParameters(video, form)).toEqual({
      aspect_ratio: "9:16",
      resolution: "720p",
      duration_seconds: 10,
      generate_audio: true,
    });
  });
});

describe("requestParameters:没填就不发", () => {
  it("时长 undefined 或 DURATION_UNSET = 让模型用自己的默认;-1 这类特殊值原样发", () => {
    const video = model("video", ["duration_seconds"]);
    expect(requestParameters(video, {})).toEqual({});
    expect(requestParameters(video, { durationSeconds: DURATION_UNSET })).toEqual({});
    expect(requestParameters(video, { durationSeconds: -1 })).toEqual({ duration_seconds: -1 });
  });

  it("空种子、空歌词不发;纯音乐不带歌词", () => {
    const audio = model("audio", ["seed", "lyrics", "instrumental"]);
    expect(requestParameters(audio, { seed: " ", lyrics: "" })).toEqual({});
    expect(requestParameters(audio, { instrumental: true, lyrics: "la" })).toEqual({ instrumental: true });
  });

  it("张数夹到 [1, 模型上限]", () => {
    const image = model("image", ["num_images"], { max_images: 4 });
    expect(requestParameters(image, { numImages: 9 })).toEqual({ num_images: 4 });
    expect(requestParameters(image, { numImages: 0 })).toEqual({ num_images: 1 });
  });
});

describe("requestParameters:通用开关、枚举、模型自己声明的参数", () => {
  it("开关没动过取声明的默认;有专属控件的(带声、纯音乐)不从通用开关里发", () => {
    const openai = model("image", ["transparent", "generate_audio"], {
      boolean_parameters: ["transparent", "generate_audio"],
      default_transparent: true,
    });
    expect(requestParameters(openai, {})).toEqual({ transparent: true });
    expect(requestParameters(openai, { booleanParameters: { transparent: false, generate_audio: true } })).toEqual({
      transparent: false,
    });
  });

  it("枚举没动过取声明的默认,再不然取第一个选项", () => {
    const openai = model("image", ["quality", "background"], {
      parameter_choices: { quality: ["low", "high"], background: ["auto", "opaque"] },
      default_background: "opaque",
    });
    expect(requestParameters(openai, { enumParameters: { quality: "high" } })).toEqual({
      quality: "high",
      background: "opaque",
    });
  });

  it("parameter_schema 里的参数只发用户动过的", () => {
    const comfy = model("image", ["steps", "cfg"], {
      parameter_schema: {
        steps: { type: "integer", default: 20 },
        cfg: { type: "number", default: 7 },
      },
    });
    expect(requestParameters(comfy, {})).toEqual({});
    expect(requestParameters(comfy, { declared: { steps: "30" } })).toEqual({ steps: 30 });
  });

  it("没有模型时什么都不发", () => {
    expect(requestParameters(null, fullForm())).toEqual({});
  });
});
