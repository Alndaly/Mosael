/**
 * 搜索结果里把命中的那几个字标出来。
 *
 * 这件事只有一个硬性要求:**切出来的片段拼回去必须和原文一模一样**。高亮说到底是"把一段
 * 文字分成命中/未命中两种片段再各自渲染",一旦漏字、多字、顺序变了,用户看到的标题就不是
 * 库里那条了 —— 那比不高亮糟得多。所以每条用例都顺带验一次"拼得回去"。
 *
 * 另一条:**查询词是用户输入的,不能拿去拼正则**。搜一个 `(` 会让 `new RegExp` 直接抛,
 * 整个搜索框白屏。这里全程用 indexOf 扫,不碰正则。
 */
import { describe, expect, it } from "vitest";

import { splitByQuery } from "@/lib/highlight";

const rebuilt = (text: string, query: string) =>
  splitByQuery(text, query)
    .map((part) => part.text)
    .join("");

describe("高亮切分", () => {
  it("命中的那段被单独切出来", () => {
    expect(splitByQuery("AI原生剪辑神器", "原生")).toEqual([
      { text: "AI", match: false },
      { text: "原生", match: true },
      { text: "剪辑神器", match: false },
    ]);
  });

  it("大小写不敏感,但**显示的是原文的大小写**", () => {
    expect(splitByQuery("Mibu Studio", "mibu")).toEqual([
      { text: "Mibu", match: true },
      { text: " Studio", match: false },
    ]);
  });

  it("出现多次就标多次", () => {
    expect(splitByQuery("aXaXa", "a").filter((part) => part.match)).toHaveLength(3);
    expect(rebuilt("aXaXa", "a")).toBe("aXaXa");
  });

  it("没命中就整段返回,不切", () => {
    expect(splitByQuery("abc", "z")).toEqual([{ text: "abc", match: false }]);
  });

  it("空查询不高亮任何东西", () => {
    expect(splitByQuery("abc", "")).toEqual([{ text: "abc", match: false }]);
    expect(splitByQuery("abc", "   ")).toEqual([{ text: "abc", match: false }]);
  });

  it("**正则元字符当普通字符处理** —— 搜一个 ( 不该让整个搜索框炸掉", () => {
    expect(() => splitByQuery("f(x) = 1", "(")).not.toThrow();
    expect(splitByQuery("f(x) = 1", "(").filter((part) => part.match)).toEqual([{ text: "(", match: true }]);
    expect(rebuilt("f(x) = 1", "(")).toBe("f(x) = 1");
  });

  it("片段拼回去永远等于原文", () => {
    for (const [text, query] of [
      ["这可能是B站第一个AI原生剪辑神器", "原"],
      ["Mibu-推广视频-全功能版.mp4", "-"],
      ["", "a"],
      ["aaa", "aa"],
    ] as const) {
      expect(rebuilt(text, query), `${text} / ${query}`).toBe(text);
    }
  });

  it("查询比原文还长时不会切出空片段", () => {
    expect(splitByQuery("ab", "abcd")).toEqual([{ text: "ab", match: false }]);
  });
});
