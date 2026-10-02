import { describe, expect, it } from "vitest";

import { translatedCue, translationSource } from "@/features/editor/subtitleTranslate";

describe("字幕再翻译", () => {
  it("双语字幕再翻一次:只翻原文那一行,译文换掉第二行,不越叠越多", () => {
    const once = translatedCue("你好", "Hello", true);
    expect(once).toBe("你好\nHello");
    expect(translationSource(once)).toBe("你好");
    const twice = translatedCue(once, "こんにちは", true);
    expect(twice).toBe("你好\nこんにちは");
  });

  it("不保留原文时就是译文本身", () => {
    expect(translatedCue("你好\nHello", "Bonjour", false)).toBe("Bonjour");
  });

  it("单行字幕整条送去翻", () => {
    expect(translationSource("  一句话 ")).toBe("一句话");
  });
});
