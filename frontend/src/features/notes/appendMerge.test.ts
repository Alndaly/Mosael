import { describe, expect, it } from "vitest";

import { mergeAppendedNote } from "./appendMerge";
import type { Note, NoteSource } from "@/api/domains/notes";

const source = (id: string): NoteSource => ({ kind: "asset", id, label: "演示", quote: id });

const note = (over: Partial<Note> = {}): Note => ({
  id: "n1", workspace_id: "w1", revision: 1, title: "标题", markdown: "开头",
  sources: [], tags: [], topics: [], project_id: null, favorite: false, trashed: false,
  created_at: "", updated_at: "", ...over,
} as Note);

describe("mergeAppendedNote", () => {
  const known = note({ revision: 1, markdown: "开头" });

  it("没有本地改动时,合并结果就是服务端那一版", () => {
    const server = note({ revision: 2, markdown: "开头\n\n追加的一段" });
    expect(mergeAppendedNote(known, server, known)?.markdown).toBe("开头\n\n追加的一段");
  });

  it("本地未保存的编辑一个字都不动,尾巴接在它后面", () => {
    const server = note({ revision: 2, markdown: "开头\n\n追加的一段" });
    const local = note({ revision: 1, markdown: "开头,我正在写的话" });
    const merged = mergeAppendedNote(known, server, local);
    expect(merged?.markdown).toBe("开头,我正在写的话\n\n追加的一段");
    // 修订号跟着服务端 —— 下一次保存的 base_revision 才是对的。
    expect(merged?.revision).toBe(2);
  });

  it("连续两次追加都能接住", () => {
    const first = note({ revision: 2, markdown: "开头\n\n第一句" });
    const local = note({ revision: 1, markdown: "开头,我在写" });
    const afterFirst = mergeAppendedNote(known, first, local)!;
    const second = note({ revision: 3, markdown: "开头\n\n第一句\n\n第二句" });
    expect(mergeAppendedNote(first, second, afterFirst)?.markdown)
      .toBe("开头,我在写\n\n第一句\n\n第二句");
  });

  it("正文别处被改过就不合并 —— 交回冲突条,不猜", () => {
    const server = note({ revision: 2, markdown: "换了个开头\n\n追加的一段" });
    expect(mergeAppendedNote(known, server, known)).toBeNull();
  });

  it("别人把结尾改长了也不算追加 —— 少了分隔符就认不得", () => {
    // 这一条是判据从 startsWith 收紧到"认后端的拼接形状"的理由:没有分隔符时,
    // 「开头」→「开头被别人改了」同样满足 startsWith,合出来会是谁都没写过的话。
    const server = note({ revision: 2, markdown: "开头被别人改了" });
    expect(mergeAppendedNote(known, server, note({ markdown: "开头,我在写" }))).toBeNull();
  });

  it("空文档被追加:整份都是新内容,不留空分隔符", () => {
    const empty = note({ revision: 1, markdown: "" });
    const server = note({ revision: 2, markdown: "第一句" });
    expect(mergeAppendedNote(empty, server, empty)?.markdown).toBe("第一句");
  });

  it("服务端没有前进就不动", () => {
    expect(mergeAppendedNote(known, note({ revision: 1, markdown: "开头" }), known)).toBeNull();
  });

  it("双方的来源都保留,不重复", () => {
    const base = note({ revision: 1, markdown: "开头", sources: [source("a")] });
    const server = note({ revision: 2, markdown: "开头\n\n追加", sources: [source("a"), source("b")] });
    const local = note({ revision: 1, markdown: "开头", sources: [source("a"), source("c")] });
    expect(mergeAppendedNote(base, server, local)?.sources).toEqual([source("a"), source("b"), source("c")]);
  });

  it("本地删掉的来源会被带回来 —— 宁可多一条,不静默丢出处", () => {
    const base = note({ revision: 1, markdown: "开头", sources: [source("a")] });
    const server = note({ revision: 2, markdown: "开头\n\n追加", sources: [source("a")] });
    const local = note({ revision: 1, markdown: "开头", sources: [] });
    expect(mergeAppendedNote(base, server, local)?.sources).toEqual([source("a")]);
  });
});
