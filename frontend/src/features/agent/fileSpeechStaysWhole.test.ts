/**
 * **文件类永远整段一次。** 这条是源码级断言,不是行为测试:
 *
 * - 工作流 `synthesize_speech` 节点:产物进素材库,一次任务、整段文本;
 * - 画板音配音(AudioComposer → onSpeak):同样一次请求、整段文本;
 * - 笔记「存成素材」(readAloud.saveAsAudio):整段合成、建成素材。
 *
 * 它们**不读**「念回复时先出声」这个设置,也没有被改成按句流水线 —— 切分只发生在对话类的
 * 组合层(`speechPipeline`)。在这里用源码断言,是因为"没被改"本身没有可观察的行为:文件类
 * 走的是任务(job)/另一些端点,在单测里替身掉之后两条路看起来一样,只有调用点能证明。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(import.meta.dirname, "../../../..");
const AGENT_SETTING = /speak_early|speakEarly|speechPipeline|speakText|loadSpeechMode|prefetchSpeechMode/;
const AGENT_SPLITTER = /splitSpeech/;

function source(relative: string): string {
  return readFileSync(join(ROOT, relative), "utf8");
}

describe("文件类:整段一次,不读对话类的开关", () => {
  it("画板音配音的调用点不读设置、也没有按句切", () => {
    const composer = source("frontend/src/features/boards/AudioComposer.tsx");
    expect(composer).not.toMatch(AGENT_SETTING);
    expect(composer).not.toMatch(AGENT_SPLITTER);
    //: 交给 onSpeak 的是整段正文,不是句子数组。
    expect(composer).toContain("onSpeak({");
    expect(composer).toContain("text: body");
  });

  it("工作流 synthesize_speech 执行器不读设置、仍然一次建任务", () => {
    const backend = source("backend/app/domain/workflows/executors/subjobs.py");
    const start = backend.indexOf('@register("synthesize_speech")');
    const end = backend.indexOf("def clone_engine_problem");
    expect(start).toBeGreaterThan(0);
    expect(end).toBeGreaterThan(start);
    const executor = backend.slice(start, end);
    expect(executor).not.toMatch(AGENT_SETTING);
    expect(executor).not.toMatch(AGENT_SPLITTER);
    //: 一次 `start_synthesis`:整段文本进一个任务,产出素材。
    expect(executor).toContain("start_synthesis");
    expect(executor).toContain('text=str(config.get("text", ""))');
  });

  it("笔记「存成素材」仍然整段合成;设置只影响朗读,不影响保存", () => {
    const readAloud = source("frontend/src/features/notes/readAloud.ts");
    expect(readAloud).not.toMatch(AGENT_SETTING);
    const save = readAloud.slice(readAloud.indexOf("function saveAsAudio"), readAloud.indexOf("function play("));
    expect(save).toContain("synthesizeWithEngine");
    expect(save).toContain("text,");
    expect(save).not.toContain("splitForSpeech");
    //: 工具条上点「存为音频素材」时传的是一整段(只按接口字数上限截断)。
    expect(readAloud).toContain("saveAsAudio(workspaceId, text.slice(0, SAVE_LIMIT)");
  });
});
