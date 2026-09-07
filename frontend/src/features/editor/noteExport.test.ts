import { describe, expect, it } from "vitest";

import { buildNoteExport, type NoteExportLine } from "./noteExport";

const line = (text: string, start: number, end: number, extra: Partial<NoteExportLine> = {}): NoteExportLine =>
  ({ text, start, end, assetId: "a1", ...extra });

describe("buildNoteExport", () => {
  const lines = [line("这是我工作室的 mac mini。", 0, 3.8), line("但功能异常强大。", 3.8, 5.3)];

  it("正文形状把连着说的句子并成一段", () => {
    expect(buildNoteExport(lines, "plain", "演示").markdown)
      .toBe("这是我工作室的 mac mini。但功能异常强大。");
  });

  it("停顿超过 1.5s 就另起一段", () => {
    const withPause = [...lines, line("出门在外需要用电脑。", 9, 12)];
    expect(buildNoteExport(withPause, "plain", "演示").markdown)
      .toBe("这是我工作室的 mac mini。但功能异常强大。\n\n出门在外需要用电脑。");
  });

  it("引用形状每句一个块,带时间", () => {
    expect(buildNoteExport(lines, "cited", "演示").markdown).toBe(
      "> 这是我工作室的 mac mini。\n\n演示 · 0.0–3.8s\n\n> 但功能异常强大。\n\n演示 · 3.8–5.3s",
    );
  });

  it("两种形状共用同一份来源", () => {
    const plain = buildNoteExport(lines, "plain", "演示");
    const cited = buildNoteExport(lines, "cited", "演示");
    expect(plain.sources).toEqual(cited.sources);
    expect(plain.sources).toHaveLength(2);
    expect(plain.sources[0]).toMatchObject({ kind: "asset", id: "a1", start: 0, end: 3.8 });
  });

  it("双语字幕两行都留下,并且独占一段", () => {
    const bilingual = [line("你好。", 0, 1, { secondary: "Hello." }), line("再见。", 1, 2)];
    expect(buildNoteExport(bilingual, "plain", "字幕").markdown).toBe("你好。\nHello.\n\n再见。");
    expect(buildNoteExport(bilingual, "cited", "字幕").markdown)
      .toBe("> 你好。\n> Hello.\n\n字幕 · 0.0–1.0s\n\n> 再见。\n\n字幕 · 1.0–2.0s");
  });

  it("译文与原文相同的行不重复写两遍", () => {
    const same = [line("Hello.", 0, 1, { secondary: "Hello." })];
    expect(buildNoteExport(same, "plain", "字幕").markdown).toBe("Hello.");
  });

  it("空行不产生空引用块,也不产生空来源", () => {
    const withBlank = [line("  ", 0, 1), line("有内容。", 1, 2)];
    const draft = buildNoteExport(withBlank, "cited", "演示");
    expect(draft.markdown).toBe("> 有内容。\n\n演示 · 1.0–2.0s");
    expect(draft.sources).toHaveLength(1);
  });

  it("拿不到素材 id 时只导正文,不伪造出处", () => {
    const orphan = [line("一句话。", 0, 1, { assetId: undefined })];
    expect(buildNoteExport(orphan, "plain", "演示").sources).toEqual([]);
  });
});
