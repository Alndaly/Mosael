import { describe, expect, it } from "vitest";

import { MAX_SCRIPT_TURNS, MAX_TURN_CHARS, parseScript, scriptFromDialogue, scriptProblems } from "./podcastScript";

const NAMES = ["大壹先生(男)", "咪仔同学"] as const;

describe("粘进来的字拆成照稿念的几段", () => {
  it("一行一段,没写前缀的两人轮流,空行跳过", () => {
    expect(parseScript("大家好\n\n今天聊聊\n先说结论", NAMES)).toEqual([
      { speaker: 0, text: "大家好" },
      { speaker: 1, text: "今天聊聊" },
      { speaker: 0, text: "先说结论" },
    ]);
  });

  it("认得 A: / B:(全角冒号也认)和发音人的名字,前缀拿掉", () => {
    expect(parseScript("B:我先来\nA:好\n咪仔同学:又是我\n大壹先生:嗯", NAMES)).toEqual([
      { speaker: 1, text: "我先来" },
      { speaker: 0, text: "好" },
      { speaker: 1, text: "又是我" },
      { speaker: 0, text: "嗯" },
    ]);
  });

  it("认不出的前缀是正文的一部分(「注意:」不是发音人),接着轮到的那一位念", () => {
    expect(parseScript("A:开场\n注意:这句不是谁的名字", NAMES)).toEqual([
      { speaker: 0, text: "开场" },
      { speaker: 1, text: "注意:这句不是谁的名字" },
    ]);
  });

  it("从光标那一段的下一位接着拆", () => {
    expect(parseScript("接上\n再接", NAMES, 1).map((turn) => turn.speaker)).toEqual([1, 0]);
  });
});

describe("稿子交不交得出去", () => {
  it("空的、超过 60 段、某段超过 280 字都说出来", () => {
    expect(scriptProblems([{ speaker: 0, text: "  " }]).empty).toBe(true);
    const many = Array.from({ length: MAX_SCRIPT_TURNS + 1 }, (_, index) => ({ speaker: (index % 2) as 0 | 1, text: "句" }));
    expect(scriptProblems(many).tooMany).toBe(true);
    expect(scriptProblems(many.slice(0, MAX_SCRIPT_TURNS)).tooMany).toBe(false);
    expect(scriptProblems([{ speaker: 0, text: "短" }, { speaker: 1, text: "长".repeat(MAX_TURN_CHARS + 1) }]).tooLong).toEqual([1]);
    expect(scriptProblems([{ speaker: 0, text: "字".repeat(MAX_TURN_CHARS) }]).tooLong).toEqual([]);
  });
});

it("改稿再念:对谈稿按这次的两位还原成 A / B", () => {
  const speakers = ["voice-a", "voice-b"];
  expect(
    scriptFromDialogue(
      [
        { speaker: "voice-b", text: "我先说" },
        { speaker: "voice-a", text: "好" },
        { speaker: "someone", text: "认不出的接着轮" },
        { speaker: "voice-a", text: " " },
      ],
      speakers,
    ),
  ).toEqual([
    { speaker: 1, text: "我先说" },
    { speaker: 0, text: "好" },
    { speaker: 1, text: "认不出的接着轮" },
  ]);
});
