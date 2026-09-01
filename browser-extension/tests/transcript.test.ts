import { describe, expect, it } from "vitest";

import { alignSecondaryCues, languageMatches } from "../src/transcript";

describe("bilingual transcript alignment", () => {
  it("maps differently segmented secondary subtitles onto the source timeline", () => {
    const source = [
      { start: 0, end: 2, text: "Hello" },
      { start: 2, end: 4, text: "world" },
      { start: 4, end: 7, text: "Goodbye" },
    ];
    const secondary = [
      { start: 0.1, end: 1.1, text: "你" },
      { start: 1.1, end: 3.8, text: "好，世界" },
      { start: 4.2, end: 6.8, text: "再见" },
    ];

    expect(alignSecondaryCues(source, secondary)).toEqual(["你 好，世界", "好，世界", "再见"]);
  });

  it("matches regional language codes to the requested language", () => {
    expect(languageMatches("zh-Hans", "zh-CN")).toBe(true);
    expect(languageMatches("en-US", "en")).toBe(true);
    expect(languageMatches("ja", "ko")).toBe(false);
  });
});
