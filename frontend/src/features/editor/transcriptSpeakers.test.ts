import { describe, expect, it } from "vitest";

import { speakerChipStyle, speakerHue, speakerLabel, speakersAreMeaningful } from "./transcriptSpeakers";

describe("speakersAreMeaningful", () => {
  it("单人时不值得标 —— 每行都一样的标签只是噪声", () => {
    expect(speakersAreMeaningful(["SPEAKER_00", "SPEAKER_00", "SPEAKER_00"])).toBe(false);
  });

  it("两个人时才标", () => {
    expect(speakersAreMeaningful(["SPEAKER_00", "SPEAKER_01"])).toBe(true);
  });

  it("没有说话人信息时不标", () => {
    expect(speakersAreMeaningful([null, undefined, "", "  "])).toBe(false);
  });

  it("一个人 + 一堆空的,仍然是一个人", () => {
    expect(speakersAreMeaningful(["SPEAKER_00", null, ""])).toBe(false);
  });

  it("空列表(还没转写)不标", () => {
    expect(speakersAreMeaningful([])).toBe(false);
  });
});

describe("speakerHue", () => {
  it("同一个人永远同色", () => {
    expect(speakerHue("SPEAKER_01")).toBe(speakerHue("SPEAKER_01"));
  });

  it("不同的人分得开", () => {
    expect(speakerHue("SPEAKER_00")).not.toBe(speakerHue("SPEAKER_01"));
  });
});

describe("speakerLabel", () => {
  it("引擎的写法换成人话", () => {
    expect(speakerLabel("SPEAKER_00")).toBe("说话人 00");
  });

  it("已经是人名的原样留着", () => {
    expect(speakerLabel("主持人")).toBe("主持人");
  });
});

describe("speakerChipStyle", () => {
  it("配色跟着主题走,不写死亮度 —— 否则深色主题下是一块亮斑", () => {
    const style = speakerChipStyle("SPEAKER_00");
    expect(style.background).toContain("var(--background)");
    expect(style.color).toContain("var(--foreground)");
  });
});
