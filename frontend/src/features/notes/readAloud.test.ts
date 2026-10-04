/**
 * 朗读:免费的 Edge 引擎一次只念一小段(试听接口收 200 字以内),所以按句切开、一段段念;音色按文字挑。
 */
import { expect, it } from "vitest";
import { READ_ALOUD_CHUNK, edgeVoiceFor, splitForSpeech } from "./readAloud";

it("按句切,每段不超过上限;一句本身超长就硬切", () => {
  const sentence = "这是一句不长不短的话。";
  const chunks = splitForSpeech(sentence.repeat(40));
  expect(chunks.length).toBeGreaterThan(1);
  expect(chunks.every((chunk) => chunk.length <= READ_ALOUD_CHUNK)).toBe(true);
  expect(chunks.join("")).toBe(sentence.repeat(40));
  //: 切在句号后面,不切在半句中间。
  expect(chunks[0].endsWith("。")).toBe(true);

  const runOn = "没有标点".repeat(100);
  expect(splitForSpeech(runOn).every((chunk) => chunk.length <= READ_ALOUD_CHUNK)).toBe(true);
  expect(splitForSpeech(runOn).join("")).toBe(runOn);
});

it("空白不念", () => {
  expect(splitForSpeech("  \n ")).toEqual([]);
});

it("有中文用中文音色,否则用英文音色", () => {
  expect(edgeVoiceFor("周一开会")).toBe("zh-CN-XiaoxiaoNeural");
  expect(edgeVoiceFor("Meeting on Monday")).toBe("en-US-AriaNeural");
});
