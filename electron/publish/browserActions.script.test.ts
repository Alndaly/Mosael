/**
 * 「执行脚本」的 input 只作为 JSON 数据交进脚本,从不拼进代码。
 *
 * 用 node:vm 真跑包好的脚本:要验的就是「包完之后脚本的语义没变、上游的文字改写不了脚本」。
 */
import { runInNewContext } from "node:vm";

import { describe, expect, it } from "vitest";

import { scriptWithInput } from "./browserActions";

describe("执行脚本:input 只作为数据交进脚本", () => {
  const run = (expression: string, input: unknown) => runInNewContext(scriptWithInput(expression, input));

  it("表达式读得到 input", () => {
    expect(run("input.count + 1", { count: 41 })).toBe(42);
  });

  it("好几句、最后一句是结果的脚本照样能用", () => {
    expect(run("const words = input.text.split(' ');\nwords.length", { text: "a b c" })).toBe(3);
  });

  it("上游交来一段带引号和代码的文字,它只是一个字符串,改写不了脚本", () => {
    const hostile = `"); globalThis.pwned = true; ("`;
    const context: Record<string, unknown> = {};
    const value = runInNewContext(scriptWithInput("input.title", { title: hostile }), context);
    expect(value).toBe(hostile);
    expect(context.pwned).toBeUndefined();
  });

  it("结尾是注释也不吞掉收尾的大括号", () => {
    expect(run("input.x // 取 x", { x: 7 })).toBe(7);
  });

  it("没给 input(智能体直接跑的脚本)原样执行", () => {
    expect(scriptWithInput("document.title", undefined)).toBe("document.title");
  });
});
