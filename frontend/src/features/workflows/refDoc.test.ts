/**
 * 存的是 `{{node.output}}` 字符串,显示的是标签。这一步翻译错了会**悄悄改掉用户的配置** ——
 * 少个花括号、把两个引用粘成一个,都要等到运行时才发作。
 */
import { describe, expect, it } from "vitest";

import { docToString, filterRefs, parsePieces, piecesToDoc, piecesToString } from "@/features/workflows/refDoc";

describe("字符串 → 片段", () => {
  it("认得出引用和它两边的文字", () => {
    expect(parsePieces("你好 {{llm-1.text}} 再见")).toEqual([
      { type: "text", text: "你好 " },
      { type: "ref", ref: "llm-1.text" },
      { type: "text", text: " 再见" },
    ]);
  });

  it("两个引用要切成两个,不能吞掉中间那段", () => {
    // 贪婪匹配会把 `{{a}} 和 {{b}}` 整个当成一个引用。
    expect(parsePieces("{{a}} 和 {{b}}")).toEqual([
      { type: "ref", ref: "a" },
      { type: "text", text: " 和 " },
      { type: "ref", ref: "b" },
    ]);
  });

  it("没有引用就是一段纯文本", () => {
    expect(parsePieces("就一句话")).toEqual([{ type: "text", text: "就一句话" }]);
  });

  it("空串是空的", () => {
    expect(parsePieces("")).toEqual([]);
  });

  it("不成对的花括号原样留着,不当引用", () => {
    // 用户可能真的想写一个 `{{`;当成引用会把后面的内容一起吃掉。
    expect(parsePieces("{{ 没闭合")).toEqual([{ type: "text", text: "{{ 没闭合" }]);
  });
});

describe("往返必须严格互逆", () => {
  for (const text of [
    "",
    "纯文本",
    "{{a.b}}",
    "前 {{a.b}} 后",
    "{{a}}{{b}}",
    "换行\n第二段 {{x.y}}",
    "{{ 带空格.的引用 }}".replace(/\s+/g, ""),
  ]) {
    it(`「${text.replace(/\n/g, "\\n") || "(空)"}」`, () => {
      expect(piecesToString(parsePieces(text))).toBe(text);
    });
  }

  it("经过文档一圈也回得来", () => {
    const text = "前 {{a.b}} 后";
    expect(docToString(piecesToDoc(parsePieces(text)))).toBe(text);
  });
});

describe("文档 → 字符串", () => {
  it("多个段落用换行接起来", () => {
    // 用户按了回车就该留下换行,不能被悄悄拼成一行。
    const doc = {
      type: "doc",
      content: [
        { type: "paragraph", content: [{ type: "text", text: "一" }] },
        { type: "paragraph", content: [{ type: "text", text: "二" }] },
      ],
    };
    expect(docToString(doc)).toBe("一\n二");
  });

  it("空段落给空串,不是 undefined", () => {
    expect(docToString({ type: "doc", content: [{ type: "paragraph" }] })).toBe("");
    expect(docToString(null)).toBe("");
  });
});

describe("按输入筛选候选", () => {




  it("查询为空时给出全部候选", () => {
    // 刚敲下 @ 就该看见所有候选,而不是一片空白。
    expect(filterRefs(["{{a.b}}", "{{c.d}}"], "")).toEqual(["{{a.b}}", "{{c.d}}"]);
  });

  it("匹配的是去掉花括号后的名字", () => {
    // 用户敲的是 `@llm`,不是 `@{{llm`。
    expect(filterRefs(["{{llm-1.text}}", "{{http-1.json}}"], "llm")).toEqual(["{{llm-1.text}}"]);
  });

  it("大小写不敏感", () => {
    expect(filterRefs(["{{LLM-1.Text}}"], "llm")).toEqual(["{{LLM-1.Text}}"]);
  });

  it("匹配输出名那一半也算", () => {
    expect(filterRefs(["{{llm-1.text}}", "{{llm-1.json}}"], "json")).toEqual(["{{llm-1.json}}"]);
  });
});
