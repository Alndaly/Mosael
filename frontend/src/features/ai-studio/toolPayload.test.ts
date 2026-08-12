/**
 * 工具调用的参数/结果,要显示**结果本身**,不是运输它的盒子。
 *
 * 真机上取到的一条 `get_workflow` 的结果长这样:
 *
 *     { "content": [ { "type": "text", "text": "{\n  \"id\": \"9d8db…\",\n  …" } ] }
 *
 * 外面是 MCP 的工具结果信封,里面那层才是真的返回值 —— 而它自己也是一段 JSON,于是被
 * `JSON.stringify(信封, null, 2)` 二次转义,用户看到的是满屏 `\n` 和 `\"`:
 *
 *     {
 *       "content": [
 *         {
 *           "type": "text",
 *           "text": "{\n  \"id\":
 *     \"9d8db21e34ad422d8a15e2068e7aafc
 *     3\",\n  \"workspace_id\":
 *
 * 在一个 250px 宽的侧栏里,这段东西读不出任何信息。拆掉信封、把里层的 JSON 重新排版之后,
 * 同样的数据是一份能看的结构。
 */
import { describe, expect, it } from "vitest";

import { readToolPayload } from "@/features/ai-studio/toolPayload";

describe("工具结果的显示文本", () => {
  it("拆掉 MCP 信封,里层是 JSON 就重新排版", () => {
    const envelope = {
      content: [{ type: "text", text: '{\n  "id": "abc",\n  "name": "新工作流"\n}' }],
    };

    expect(readToolPayload(envelope)).toBe('{\n  "id": "abc",\n  "name": "新工作流"\n}');
  });

  it("里层是散文就原样给出 —— 别硬当 JSON 解析", () => {
    const envelope = { content: [{ type: "text", text: "已删除 3 个片段。" }] };

    expect(readToolPayload(envelope)).toBe("已删除 3 个片段。");
  });

  it("多段文本按顺序接起来", () => {
    const envelope = {
      content: [
        { type: "text", text: "第一段" },
        { type: "text", text: "第二段" },
      ],
    };

    expect(readToolPayload(envelope)).toBe("第一段\n第二段");
  });

  it("信封里有非文本内容时不拆 —— 拆了会把那部分数据丢掉", () => {
    const envelope = { content: [{ type: "image", data: "..." }] };

    expect(readToolPayload(envelope)).toContain('"image"');
  });

  it("不是信封的对象照旧排版", () => {
    expect(readToolPayload({ a: 1 })).toBe('{\n  "a": 1\n}');
  });

  it("本来就是字符串就原样给", () => {
    expect(readToolPayload("plain")).toBe("plain");
  });

  it("空值给空串,不是 'null' 这四个字", () => {
    expect(readToolPayload(null)).toBe("");
    expect(readToolPayload(undefined)).toBe("");
  });

  it("里层 JSON 是紧凑写法时也重新排版 —— 一行几百字符在窄栏里同样读不了", () => {
    const envelope = { content: [{ type: "text", text: '{"id":"abc","n":1}' }] };

    expect(readToolPayload(envelope)).toBe('{\n  "id": "abc",\n  "n": 1\n}');
  });
});
