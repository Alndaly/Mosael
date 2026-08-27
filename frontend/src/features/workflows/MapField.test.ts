/**
 * 「名字 → 值」的映射,翻译要稳。
 *
 * 这类字段此前是一个 `{}` 的原始 JSON 框:想用上游输出得自己敲 `{"topic": "{{llm-1.text}}"}`,
 * 键名要背、引号逗号要记,而**写错了直到运行才知道** —— JSON 少个引号是解析失败(还算好),
 * 引用名写错则一路静默传个空值下去。
 */
import { describe, expect, it } from "vitest";

import { objectFromRows, rowsFromObject, suggestName } from "@/features/workflows/MapField";

describe("对象 ↔ 行", () => {
  it("保持插入顺序,不排序", () => {
    // 用户看到的顺序就该是他自己敲进去的顺序。
    expect(rowsFromObject({ b: "1", a: "2" }).map((r) => r.key)).toEqual(["b", "a"]);
  });

  it("非字符串的值原样显示得出来", () => {
    expect(rowsFromObject({ n: 3, ok: true })).toEqual([
      { key: "n", value: "3" },
      { key: "ok", value: "true" },
    ]);
  });

  it("不是对象就是空行", () => {
    expect(rowsFromObject(null)).toEqual([]);
    expect(rowsFromObject("x")).toEqual([]);
    expect(rowsFromObject([1, 2])).toEqual([]);
  });
});

describe("写回时还原类型", () => {
  it("数字和布尔还原,不留成字符串", () => {
    expect(objectFromRows([{ key: "n", value: "3" }, { key: "ok", value: "true" }])).toEqual({ n: 3, ok: true });
  });

  it("带 {{}} 的一律当字符串", () => {
    // 那是模板,要留给引擎插值 —— 万一它长得像数字也不能转。
    expect(objectFromRows([{ key: "t", value: "{{llm-1.text}}" }])).toEqual({ t: "{{llm-1.text}}" });
  });

  it("名字为空的行丢掉", () => {
    expect(objectFromRows([{ key: "  ", value: "x" }])).toEqual({});
  });

  it("值为空的行留着", () => {
    // "名字先起好、值待填"是很常见的中间态;删掉的话用户刚敲的名字会当场消失。
    expect(objectFromRows([{ key: "topic", value: "" }])).toEqual({ topic: "" });
  });

  it("往返稳定", () => {
    const original = { topic: "{{llm-1.text}}", n: 3, s: "hi" };
    expect(objectFromRows(rowsFromObject(original))).toEqual(original);
  });
});

describe("点上游 chip 加一行时,名字要猜得像样", () => {
  it("默认取输出名", () => {
    // `{{llm-1.text}}` 想喂给子图,多半就是想叫 text。
    expect(suggestName("{{llm-1.text}}", [])).toBe("text");
  });

  it("重名了跟上游节点名,而不是直接覆盖", () => {
    expect(suggestName("{{llm-1.text}}", [{ key: "text", value: "x" }])).toBe("llm_1_text");
  });

  it("再重就加序号", () => {
    const rows = [
      { key: "text", value: "x" },
      { key: "llm_1_text", value: "y" },
    ];
    expect(suggestName("{{llm-1.text}}", rows)).toBe("text_2");
  });
});
