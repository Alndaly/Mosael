/**
 * 「执行脚本」的 input 只作为 JSON 数据交进脚本,从不拼进代码。
 *
 * 用 node:vm 真跑包好的脚本:要验的就是「包完之后脚本的语义没变、上游的文字改写不了脚本」。
 */
import { createContext, runInContext, runInNewContext } from "node:vm";

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

describe("执行脚本:脚本自己声明的 input 不和交进来的那份打架", () => {
  //: 同一个上下文(同一页)上连跑:循环里的「执行脚本」就是这样,第二次不能撞「已声明」。
  const runIn = (context: object, expression: string, input: unknown) =>
    runInContext(scriptWithInput(expression, input), context);
  const given = { x: 7 };

  it.each([
    ["const", "const input = { v: 1 }; input.v", 1],
    ["let", "let input = 2; input", 2],
    ["var", "var input = 3; input", 3],
    ["function", "function input() { return 4 } input()", 4],
    ["class", "class input { static v = 5 } input.v", 5],
  ])("自己用 %s 声明了 input:不报 SyntaxError,读到的是自己的那个", (_kind, expression, expected) => {
    expect(runIn(createContext({}), expression, given)).toBe(expected);
  });

  it.each([{}, null])("没有入参(%j)的老脚本自己声明 input 照样能跑", (input) => {
    expect(runIn(createContext({}), "const input = { v: 1 }; input.v", input)).toBe(1);
    expect(runIn(createContext({}), "var input = 3; input", input)).toBe(3);
  });

  it("没声明就读到交进来的数据,脚本里的函数也读得到", () => {
    expect(runIn(createContext({}), "function f() { return input.x * 2 } f()", given)).toBe(14);
  });

  it("只拦 input 这一个名字:页面自己的 toString 之类照旧,不被换成 Object.prototype 上的那个", () => {
    const page = createContext({ toString: () => "page", valueOf: () => 42 });
    expect(runIn(page, "toString() + valueOf()", given)).toBe("page42");
  });

  it("最后一句的值就是结果;同一页上跑第二次不撞「已声明」", () => {
    const context = createContext({});
    expect(runIn(context, "const a = input.x; a + 1", given)).toBe(8);
    expect(runIn(context, "const a = input.x; a + 1", given)).toBe(8);
    expect(runIn(context, "const b = 1; b", {})).toBe(1);
    expect(runIn(context, "const b = 1; b", {})).toBe(1);
  });

  it("async IIFE 交回 Promise,解出来是 input 算出的值", async () => {
    await expect(runIn(createContext({}), "(async () => input.x + 1)()", given)).resolves.toBe(8);
  });

  it("return 只能写在函数里:IIFE 里的 return 照常,顶层 return 和不包时一样是语法错", () => {
    expect(runIn(createContext({}), "(() => { return input.x })()", given)).toBe(7);
    //: vm 里抛的 SyntaxError 是另一个 realm 的,按名字比
    expect(() => runIn(createContext({}), "return input.x", given)).toThrow(/Illegal return/);
    expect(() => runInNewContext("return 1")).toThrow(/Illegal return/);
  });
});
