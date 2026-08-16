/**
 * 配音前的语言提示。
 *
 * 这条判断的价值在于**它出现的时机**:文本就在眼前,选引擎的那一刻就能说。等到点下去、
 * 任务排队、再收到一条错误,用户已经等过一轮了。
 *
 * 它的风险则全在**误报**:一条错误的警告会让用户开始怀疑所有警告,所以判据只用硬证据。
 */
import { describe, expect, it } from "vitest";

import { detectScript, unspeakable, voiceLanguage } from "./dubLanguage";

describe("书写系统识别", () => {
  it("假名是日文的硬证据", () => {
    expect(detectScript("三日前のだったらちょっとお腹壊しちゃうかな")).toBe("ja");
    expect(detectScript("お漏らし。")).toBe("ja");
  });

  it("中文里夹一个「の」不是日文 —— 误报比漏报糟", () => {
    expect(detectScript("这个词在日语里叫の,很有意思")).toBe("");
  });

  it("中文和英文给不出任何证据 —— 汉字中日共用,拉丁字母几十种语言共用", () => {
    expect(detectScript("这是一段中文")).toBe("");
    expect(detectScript("Hello world")).toBe("");
    expect(detectScript("")).toBe("");
  });

  it("韩文同理", () => {
    expect(detectScript("안녕하세요 반갑습니다")).toBe("ko");
  });
});

describe("音色语言", () => {
  it("Edge 的 id 自带 locale", () => {
    expect(voiceLanguage("edge", "ja-JP-NanamiNeural")).toBe("ja");
    expect(voiceLanguage("edge", "zh-CN-XiaoxiaoNeural")).toBe("zh");
  });

  it("其余引擎看前缀,但只认已知语言 —— `my_custom_voice` 的 `my_` 不是语言代码", () => {
    expect(voiceLanguage("volcano", "zh_female_cancan_mars_bigtts")).toBe("zh");
    expect(voiceLanguage("volcano", "my_custom_voice_42")).toBe("");
  });
});

describe("念不念得了", () => {
  const ja = ["お漏らし。", "ここに寝てるんでしょ？"];

  it("日文交给本地克隆 —— 念不了,它只会产出一段听不懂的声音", () => {
    expect(unspeakable(ja, "clone", "")).toBe("ja");
  });

  it("日文配 ja 音色 —— 正是该放行的情形", () => {
    expect(unspeakable(ja, "edge", "ja-JP-NanamiNeural")).toBe("");
  });

  it("日文配中文音色 —— 拦", () => {
    expect(unspeakable(ja, "edge", "zh-CN-XiaoxiaoNeural")).toBe("ja");
    expect(unspeakable(ja, "volcano", "zh_female_cancan_mars_bigtts")).toBe("ja");
  });

  it("音色语言拿不准时一律当能念 —— 错误的警告会让人怀疑所有警告", () => {
    expect(unspeakable(ja, "openai", "alloy")).toBe("");
    expect(unspeakable(ja, "volcano", "my_custom_voice_42")).toBe("");
  });

  it("中文字幕不触发任何提示", () => {
    expect(unspeakable(["这是中文", "第二条"], "clone", "")).toBe("");
  });
});
