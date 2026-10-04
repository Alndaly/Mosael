/** @vitest-environment jsdom */

/**
 * 别的页面把「用这个模型 / 这几项参数去生成」交给 AI 工作台(模型库的「用它生成」):记下要什么、把工作台切到对的那一页、
 * 跳过去;生成页清单到了取走一次。
 */

import { beforeEach, describe, expect, it } from "vitest";

import { handOffToGeneration, takeGenerationHandoff } from "./generationHandoff";

const handoff = {
  providerProfileId: "p9",
  kind: "image",
  model: "portrait.json",
  declared: { "9.lora_name": "detail.safetensors" },
  promptWords: ["anima style"],
};

beforeEach(() => {
  window.localStorage.clear();
  window.location.hash = "#/plugins";
  takeGenerationHandoff(["image", "video", "audio"]);
});

describe("交给 AI 工作台去生成", () => {
  it("跳到 AI 工作台,图像 / 视频切到「生成」页,音频切到「音频」页的「音乐与音效」", () => {
    handOffToGeneration(handoff);
    expect(window.location.hash).toBe("#/ai");
    expect(window.localStorage.getItem("mosael:tab:ai-studio")).toBe("generate");
    takeGenerationHandoff(["image", "video"]);
    handOffToGeneration({ ...handoff, kind: "audio" });
    expect(window.localStorage.getItem("mosael:tab:ai-studio")).toBe("audio");
    expect(window.localStorage.getItem("mosael:tab:ai-studio-audio")).toBe("music");
  });

  it("只有管这一种的那一页取得走,取走一次就没了", () => {
    handOffToGeneration(handoff);
    expect(takeGenerationHandoff(["audio"])).toBeNull();
    expect(takeGenerationHandoff(["image", "video"])).toEqual(handoff);
    expect(takeGenerationHandoff(["image", "video"])).toBeNull();
  });
});
