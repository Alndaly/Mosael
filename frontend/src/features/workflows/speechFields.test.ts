import { describe, expect, it } from "vitest";

import { speechFieldVisible, speechUsesClonedVoice } from "@/features/workflows/speechFields";

/**
 * 钉的是用户报的那句「音色和引擎音色 重复了」。
 *
 * 两条互斥的路被摊成并排字段:音色、引擎、引擎音色三格,两格名字里都带"音色",各自还写着
 * "用另一个时留空"。互斥关系摆成并排,读的人得自己在脑子里做那道推理 —— 而典型结果是
 * 两个都填或者两个都空。
 */
describe("语音合成的音色那一格", () => {
  it("选了克隆就只出配音库那一格", () => {
    expect(speechFieldVisible("synthesize_speech", "voice_id", "clone")).toBe(true);
    expect(speechFieldVisible("synthesize_speech", "engine_voice", "clone")).toBe(false);
    expect(speechFieldVisible("synthesize_speech", "engine_voice_resource", "clone")).toBe(false);
  });

  it("选了引擎就只出该引擎的音色", () => {
    expect(speechFieldVisible("synthesize_speech", "voice_id", "edge")).toBe(false);
    expect(speechFieldVisible("synthesize_speech", "engine_voice", "edge")).toBe(true);
  });

  it("两格永远不会同时出现", () => {
    // 这一条才是用户报的那件事本身 —— 上面两条是它的两个方向。
    for (const engine of ["", "  ", "clone", "edge", "volcano", "fish"]) {
      const both =
        speechFieldVisible("synthesize_speech", "voice_id", engine) &&
        speechFieldVisible("synthesize_speech", "engine_voice", engine);
      expect(both, `engine=${JSON.stringify(engine)} 时两格都出来了`).toBe(false);
    }
  });

  it("留空视作克隆", () => {
    // 已经存下来的工作流里只有 voice_id。留空显示成"选了引擎"的话,那一格会突然空掉,
    // 看起来像配置丢了。执行体那边同样把空当克隆。
    expect(speechUsesClonedVoice("")).toBe(true);
    expect(speechUsesClonedVoice(undefined)).toBe(true);
    expect(speechUsesClonedVoice("   ")).toBe(true);
    expect(speechUsesClonedVoice("edge")).toBe(false);
  });

  it("别的节点一律照旧", () => {
    expect(speechFieldVisible("llm", "voice_id", "edge")).toBe(true);
    expect(speechFieldVisible("publish", "engine_voice", "clone")).toBe(true);
  });
});
