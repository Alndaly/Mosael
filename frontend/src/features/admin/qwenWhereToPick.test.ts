import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";

/**
 * 「Qwen3-TTS 装好之后,到底在哪儿切到它」—— 界面这一侧的那句话。
 *
 * 维护者在「管理 → 引擎 → 声音克隆」里装好 Qwen3-TTS 后,抬头的「引擎」下拉只有 F5-TTS /
 * Fish Speech,于是结论是"装了却切不过去"。那个下拉是**默认克隆引擎**(后端只收
 * `f5-tts|fish-speech`),Qwen3-TTS 是预置音色引擎、不克隆 —— 它本来就不属于那里,
 * 也不该被塞进去(塞进去等于让「声音克隆」撒谎,保存还会 422)。
 *
 * 真正要补的是**指路**:这一节的说明和那个下拉的名字都得说清 Qwen 去哪选。文案表是这两句话
 * 唯一的产地(组件只负责渲染 key),所以在这里钉住。
 */
describe("声音克隆那一节说清 Qwen3-TTS 去哪选", () => {
  it("中文:说明里点名 Qwen3-TTS、说它不克隆、并说出真正的入口", () => {
    const desc = messages["zh-CN"].voiceCloneDesc;
    expect(desc).toContain("Qwen3-TTS");
    // 不能让人以为它支持克隆。
    expect(desc).toContain("不克隆");
    // 真正的入口:剪辑台的「配音」或创作页「语音」。
    expect(desc).toContain("配音");
    expect(desc).toContain("语音");
    // 那个下拉装的是克隆引擎,不是"所有引擎"。
    expect(desc).toContain("克隆引擎");
  });

  it("英文:同一件事,不能只改中文", () => {
    const desc = messages["en-US"].voiceCloneDesc;
    expect(desc).toContain("Qwen3-TTS");
    expect(desc.toLowerCase()).toContain("doesn't clone");
    expect(desc).toContain("Dubbing");
    expect(desc).toContain("Speech");
    expect(desc).toContain("clone engine");
  });

  it("下拉的名字自己就说明是克隆引擎 —— 叫「引擎」会让人以为所有引擎都在这儿切", () => {
    expect(messages["zh-CN"].voiceCloneEngine).toContain("克隆");
    expect(messages["en-US"].voiceCloneEngine).toContain("clone");
  });
});
