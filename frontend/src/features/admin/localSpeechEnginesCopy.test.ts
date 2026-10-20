import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";

/**
 * 这一页管的是**本机跑**的语音引擎,这是维护者原话:「管理页面应该是管理本地引擎 —— 只不过有一些
 * 已经装在 Mosael 内嵌了,有些需要用户自行点击下载」。
 *
 * 所以:标题要点明「本地」;说明里要把范围说穿 —— 本机跑、有的随应用带着、有的要下权重;
 * **云端引擎(Edge TTS)不在这里** —— 它不在本机跑、也没有权重,不该作为一行混进来,
 * 选它的入口在剪辑台的「配音」或创作页「语音」的引擎下拉里。
 *
 * 这里钉文案;渲染与那条「表里没有 Edge 行」的回归在 localSpeechEngines.dom.test.tsx。
 */
describe("这一节的标题点明是「本地」引擎", () => {
  it("中文标题是「本地语音合成引擎」", () => {
    expect(messages["zh-CN"].voiceCloneTitle).toBe("本地语音合成引擎");
  });

  it("英文标题同义:Local speech synthesis engines(首字母大写,其余小写,照现有规则)", () => {
    expect(messages["en-US"].voiceCloneTitle).toBe("Local speech synthesis engines");
  });
});

describe("说明里讲清范围:本机跑、两种来源、云端引擎的去处", () => {
  it("中文:本机跑 / 随应用带着 / 要下权重 / 云端引擎不在这里 / 配音 / 语音 都在", () => {
    const desc = messages["zh-CN"].voiceCloneDesc;
    expect(desc).toContain("本机跑");
    expect(desc).toContain("随应用带着");
    expect(desc).toContain("要下权重");
    expect(desc).toContain("云端引擎");
    expect(desc).toContain("不在这里");
    expect(desc).toContain("配音");
    expect(desc).toContain("语音");
  });

  it("中文:这句加在最后,没有打乱原有句子", () => {
    const desc = messages["zh-CN"].voiceCloneDesc;
    //: 原有最后一句停在「占位音」;新加的那句整个在它后面。
    expect(desc.indexOf("本机跑")).toBeGreaterThan(desc.indexOf("占位音"));
    expect(desc.indexOf("云端引擎")).toBeGreaterThan(desc.indexOf("本机跑"));
  });

  it("英文同义,不能只改中文", () => {
    const desc = messages["en-US"].voiceCloneDesc;
    for (const needle of [
      "run on this machine",
      "ship with the app",
      "download",
      "Cloud engines",
      "not here",
      "Dubbing",
      "Speech",
    ]) {
      expect(desc).toContain(needle);
    }
    //: 英文也是接在原来那句之后。
    expect(desc.indexOf("run on this machine")).toBeGreaterThan(desc.indexOf("placeholder tone"));
  });

  it("Cloud engines 那句点名 Edge 是打比方,不是把 Edge 收进这一节", () => {
    //: 说明里提到 Edge 只为指路;表里的行由后端引擎目录来,`/api/tts/models` 里没有 Edge。
    expect(messages["en-US"].voiceCloneDesc).toContain("Edge");
    expect(messages["zh-CN"].voiceCloneDesc).toContain("Edge");
  });
});
