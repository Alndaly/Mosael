import { describe, expect, it } from "vitest";

import type { MessageKey } from "@/app/messages";
import { untitledEntryLabel } from "@/features/media/UrlImportDialog";

const messages: Partial<Record<MessageKey, string>> = {
  urlImportUntitledPart: "P{n} · 名字没取到",
  urlImportUntitledEntry: "第 {n} 条 · 名字没取到",
};
const t = (key: MessageKey) => messages[key] ?? key;

describe("名字没取到的条目画占位,不编名字", () => {
  it("B 站分 P 的地址带着 p=N:说第几 P", () => {
    expect(untitledEntryLabel("https://www.bilibili.com/video/BV1WAec6fE5N?p=2", 2, t)).toBe("P2 · 名字没取到");
  });

  it("没有分 P 号:说列表里第几条(翻页后从这一页的起点算)", () => {
    expect(untitledEntryLabel("https://example.com/watch?v=abc", 203, t)).toBe("第 203 条 · 名字没取到");
    expect(untitledEntryLabel("not a url", 1, t)).toBe("第 1 条 · 名字没取到");
  });
});
