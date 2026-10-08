/** @vitest-environment jsdom */

/**
 * 别的页面把「用这个模型 / 这几项参数去生成」交给 AI 工作台(模型库的「用它生成」):记下要什么、跳到创作分区、
 * 筛选换成那一种;创作页清单到了取走一次。
 */

import { beforeEach, describe, expect, it } from "vitest";

import { CREATION_FILTER_EVENT } from "./aiStudioLink";
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
  takeGenerationHandoff();
});

describe("交给 AI 工作台去生成", () => {
  it("跳到创作分区,筛选换成交过来的那一种(ADR 0055)", () => {
    const filters: string[] = [];
    const onFilter = (event: Event) => filters.push(String((event as CustomEvent).detail));
    window.addEventListener(CREATION_FILTER_EVENT, onFilter);
    handOffToGeneration(handoff);
    expect(window.location.hash).toBe("#/ai?tab=create");
    handOffToGeneration({ ...handoff, kind: "audio" });
    window.removeEventListener(CREATION_FILTER_EVENT, onFilter);
    expect(filters).toEqual(["image", "audio"]);
    //: 不再往本机写分区:地址里说了
    expect(window.localStorage.getItem("mosael:tab:ai-studio")).toBeNull();
  });

  it("创作页取走一次就没了", () => {
    handOffToGeneration(handoff);
    expect(takeGenerationHandoff()).toEqual(handoff);
    expect(takeGenerationHandoff()).toBeNull();
  });
});
