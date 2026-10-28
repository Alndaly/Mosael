/**
 * 配音前的语言提示。
 *
 * 这条判断的价值在于**它出现的时机**:文本就在眼前,选引擎的那一刻就能说。等到点下去、
 * 任务排队、再收到一条错误,用户已经等过一轮了。
 *
 * 它的风险则全在**误报**:一条错误的警告会让用户开始怀疑所有警告,所以判据只用硬证据。
 */
import { describe, expect, it } from "vitest";

import { detectScript, hasVoiceFor, pickVoiceFor, unspeakable } from "./dubLanguage";

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

describe("念不念得了 —— 音色的语言只认目录上的声明(ADR 0087)", () => {
  const ja = ["お漏らし。", "ここに寝てるんでしょ？"];
  const voice = (...languages: string[]) => ({ languages });

  it("日文交给只装了中英权重的本地克隆 —— 念不了", () => {
    expect(unspeakable(ja, "builtin:clone", null, ["zh", "en"])).toBe("ja");
  });

  it("装上日语权重之后就念得了 —— 语言能力是**权重**的属性,不是引擎的", () => {
    expect(unspeakable(ja, "builtin:clone", null, ["zh", "en", "ja"])).toBe("");
  });

  it("日文配声明了 ja 的音色 —— 正是该放行的情形;BCP 47 只看主语言", () => {
    expect(unspeakable(ja, "builtin:edge", voice("ja-JP"))).toBe("");
    expect(unspeakable(ja, "builtin:volcano", voice("ja"))).toBe("");
  });

  it("日文配声明了中文的音色 —— 拦", () => {
    expect(unspeakable(ja, "builtin:edge", voice("zh-CN"))).toBe("ja");
    expect(unspeakable(ja, "builtin:volcano", voice("zh"))).toBe("ja");
  });

  it("目录没声明语言(OpenAI 的多语言音色、账号里自建的)一律当能念 —— 错误的警告会让人怀疑所有警告", () => {
    expect(unspeakable(ja, "builtin:openai", voice())).toBe("");
    expect(unspeakable(ja, "builtin:volcano", null)).toBe("");
  });

  it("**不从 id 里猜**:id 长得像中文音色,目录没说,就不拦", () => {
    expect(unspeakable(ja, "builtin:volcano", { languages: [] })).toBe("");
  });

  it("中文字幕不触发任何提示", () => {
    expect(unspeakable(["这是中文", "第二条"], "builtin:clone", null, ["zh", "en"])).toBe("");
  });
});


describe("默认就选对,而不是先选错再警告", () => {
  const edgeVoices = [
    { id: "zh-CN-XiaoxiaoNeural", languages: ["zh-CN"] },
    { id: "en-US-AriaNeural", languages: ["en-US"] },
    { id: "ja-JP-NanamiNeural", languages: ["ja-JP"] },
  ];

  it("日文字幕 + Edge → 直接落在声明了日语的音色上", () => {
    // 用户选了 Edge 却看到「晓晓」和一条警告,只会以为选错了引擎 —— 他没错,是默认值错了。
    expect(pickVoiceFor("ja", edgeVoices)).toBe("ja-JP-NanamiNeural");
  });

  it("挑不出来时返回空串 —— 保持引擎自己的默认,不硬塞一个", () => {
    expect(pickVoiceFor("ja", [{ id: "zh_female_cancan_mars_bigtts", languages: ["zh"] }])).toBe("");
    expect(pickVoiceFor("", edgeVoices)).toBe("");
  });

  it("有没有能念的,决定提示说「换音色」还是「换引擎」", () => {
    expect(hasVoiceFor("ja", edgeVoices)).toBe(true);
    expect(hasVoiceFor("ja", [{ id: "zh_female_cancan_mars_bigtts", languages: ["zh"] }])).toBe(false);
  });
});

describe("占位符替换", () => {
  it("同名占位符出现两次时要全换掉", () => {
    // `.replace()` 只换第一个 —— 界面上会留一个字面的 {lang}(真出过,截图为证)。
    const template = "这些字幕是{lang},…下一份{lang}模型(约 {size} GB)";
    expect(template.replaceAll("{lang}", "日语").replace("{size}", "1.4")).not.toContain("{lang}");
    expect(template.replace("{lang}", "日语")).toContain("{lang}");
  });
});
