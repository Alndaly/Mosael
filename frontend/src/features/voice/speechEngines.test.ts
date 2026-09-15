/**
 * 字幕配音能用哪些引擎。
 *
 * 这条判断值得单独测:错了不会报错,只会在**听到**的时候才发现 —— 一条 3 秒的字幕换回来一段
 * 双人播客。而它又恰好是最容易被"把引擎列表原样摆上去"顺手带进来的。
 */
import { describe, expect, it } from "vitest";

import { compactSpeechEngineChoices, speechEngineChoices } from "./speechEngines";

const engine = (id: string, voices: string[] = []) =>
  ({ id, label: id, needs_key: false, needs_voice_id: false, voices, note: "", ready: true }) as never;

describe("字幕配音的引擎选项", () => {
  it("播客引擎不在其中 —— 它产出的是一整段双人对话", () => {
    const choices = speechEngineChoices([engine("clone"), engine("volcano"), engine("volcano-podcast")]);
    expect(choices.map((item) => item.id)).toEqual(["clone", "volcano"]);
  });

  it("其余引擎原样保留,顺序不动 —— 顺序是后端定的(本地的排前面)", () => {
    const choices = speechEngineChoices([engine("clone"), engine("volcano"), engine("minimax")]);
    expect(choices.map((item) => item.id)).toEqual(["clone", "volcano", "minimax"]);
  });

  it("还没拉到引擎目录时是空列表,不是崩", () => {
    expect(speechEngineChoices(undefined)).toEqual([]);
  });
});

describe("紧凑工具行(画板音频卡片)的引擎选项", () => {
  it("报不出音色清单的引擎不摆出来 —— 那会是一个点开是空的下拉", () => {
    const choices = compactSpeechEngineChoices([
      engine("clone"),
      engine("edge", ["zh-CN-XiaoxiaoNeural"]),
      engine("alibaba"), // 开放模型集合,音色要手打 id
    ]);
    expect(choices.map((item) => item.id)).toEqual(["clone", "edge"]);
  });

  it("克隆是例外:它的音色来自工作区配音库,不在引擎描述符里", () => {
    expect(compactSpeechEngineChoices([engine("clone")]).map((one) => one.id)).toEqual(["clone"]);
  });

  it("播客引擎这一层也照样排除 —— 更紧的那一档不该把上一档放进来的东西漏回去", () => {
    const choices = compactSpeechEngineChoices([engine("volcano-podcast", ["a", "b"]), engine("edge", ["x"])]);
    expect(choices.map((one) => one.id)).toEqual(["edge"]);
  });
});
