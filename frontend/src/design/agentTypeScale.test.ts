/**
 * 智能体时间线的字号**只有一个出处**。
 *
 * 这条棘轮存在的理由是它已经犯过两次,而且两次都不报错:
 *
 * 1. 画布助手那句「智能体思考中…」字号从外层继承成了 `text-ui-md`,比上面每一行都大一号 ——
 *    那次单独给那一行补了字号(见 features/agent/agentRow.ts 开头那段);
 * 2. 工具的结果卡同样没写字号,于是 `list_scenes` 返回的七个场景名和助手正文一样大,
 *    比回答本身还抢眼。
 *
 * 同一个毛病两处,因为**补的是那一处,不是那个概念**。助手正文是 16px,而工具步骤、思考、
 * 结果卡说的是"机器那一侧发生了什么",该小一档 —— 只要这一档没被写下来,它就会继续从外层
 * 继承成 16px,而画面上只是"看着有点大"。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const agentRow = readFileSync(join(SRC, "features/agent/agentRow.ts"), "utf8");
const toolCalls = readFileSync(join(SRC, "features/agent/ToolCalls.tsx"), "utf8");

/** `export const NAME = "…"` 里那串 class。 */
function classesOf(source: string, name: string): string {
  const match = source.match(new RegExp(`export const ${name} = "([^"]*)"`));
  expect(match, `${name} 不是一个字符串常量了?`).toBeTruthy();
  return match![1];
}
const sizeOf = (classes: string) => classes.match(/\btext-(ui-(?:2xs|xs|sm|md|lg))\b/)?.[1] ?? "";

const ROW_TOKENS = ["AGENT_ROW_CLASS", "AGENT_ROW_BODY_CLASS", "AGENT_ROW_TEXT_CLASS"];

describe("智能体时间线的字号", () => {
  it.each(ROW_TOKENS)("%s 自己写着字号,不靠继承", (name) => {
    expect(sizeOf(classesOf(agentRow, name))).not.toBe("");
  });

  it("三处是**同一档** —— 标题行和它展开的正文不该一大一小", () => {
    const sizes = new Set(ROW_TOKENS.map((name) => sizeOf(classesOf(agentRow, name))));
    expect([...sizes]).toHaveLength(1);
  });

  it("比助手正文小一档 —— 机器那一侧的信息不该和回答一样重", () => {
    // 正文是 text-ui-md(16px)。这一栏取 sm 或更小。
    expect(["ui-sm", "ui-xs", "ui-2xs"]).toContain(sizeOf(classesOf(agentRow, "AGENT_ROW_TEXT_CLASS")));
  });

  it("工具行的容器挂着这一档 —— 行的根是 <button>,根上的字号会被 `font: inherit` 吃掉", () => {
    // 所以光给 AGENT_ROW_CLASS 写字号不够,外层容器也要挂一份。
    expect(toolCalls).toContain("AGENT_ROW_TEXT_CLASS");
  });

  it("结果卡不自己造一个字号 —— 它跟容器那一档", () => {
    // 卡里更次要的东西(耗时、标签、代码块)各自写 xs/2xs,层级仍在;但**卡本身**不该写
    // text-ui-md,那会把它重新拉回正文那一档。
    const shapes = readFileSync(join(SRC, "features/agent/toolResultShapes.tsx"), "utf8");
    expect(shapes).not.toContain("text-ui-md");
  });
});
