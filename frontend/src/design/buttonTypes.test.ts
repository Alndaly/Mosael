/**
 * 按钮的 type:`Button` / `IconButton` 不写 type 就是 `type="button"`(components/ui/button.tsx),**要提交表单的那一颗写
 * `type="submit"`,其余不写**。
 *
 * HTML 的默认是 submit:`<form>` 里任何一颗没写 type 的按钮(展开、清空、换一个选项)点了都会顺带把整张表单交出去。
 * 换基础件时踩到过 —— 模型设置里一颗原生 `<button type="button">` 换成 `<Button>`,点「自己描述这个端点」就把整张表单存了。
 * 默认改成 button 之后,风险反过来:该提交的那颗忘了写 submit,点它、按回车都不提交。这条盯三件事:
 * - `Button` / `IconButton` 上不写 `type="button"`(那是默认,写了只是噪声,也让「哪颗是提交」不显眼);
 * - 一张 `<form>` 里有按钮,就得有一颗提交的(里面写了 `type="submit"`,或者表单外面用 `form={id}` 指过来的那颗);
 * - 写了 `type="submit"` 的按钮要么在 `<form>` 里,要么用 `form=` 指着一张表单 —— 否则它什么也不提交。
 *
 * 只有一个输入框、没有按钮的表单(地址栏、改名)按回车照样提交,这是浏览器的隐式提交,不用按钮。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { childrenOf, openTags, readSource, tsxSources } from "@/design/jsxSource";

const BUTTONS = new Set(["Button", "IconButton"]);
const SUBMITTERS = new Set(["Button", "IconButton", "button", "input"]);
const OWNERS = ["components/ui/"];

type Problem = string;

export function buttonTypeProblems(code: string): Problem[] {
  const problems: Problem[] = [];
  const tags = openTags(code);
  const spans = tags
    .filter((tag) => tag.tag === "form" && !tag.selfClosing)
    .map((tag) => {
      const inner = childrenOf(code, tag) ?? "";
      return { tag, from: tag.end, to: tag.end + inner.length };
    });
  const insideForm = (at: number) => spans.find((span) => span.from <= at && at < span.to);
  const externalSubmit = tags.some((tag) => BUTTONS.has(tag.tag) && tag.attrs.get("type") === '"submit"' && tag.attrs.has("form"));
  for (const tag of tags) {
    const type = tag.attrs.get("type");
    if (BUTTONS.has(tag.tag) && type === '"button"') problems.push(`${tag.line}: <${tag.tag} type="button"> —— 默认就是,别写`);
    if (SUBMITTERS.has(tag.tag) && type === '"submit"' && !tag.attrs.has("form") && !insideForm(tag.start)) {
      problems.push(`${tag.line}: <${tag.tag} type="submit"> 不在 <form> 里,也没有 form= 指着一张表单`);
    }
  }
  for (const span of spans) {
    const inner = tags.filter((tag) => span.from <= tag.start && tag.start < span.to);
    const hasButton = inner.some((tag) => BUTTONS.has(tag.tag) || tag.tag === "button");
    const hasSubmit = inner.some((tag) => SUBMITTERS.has(tag.tag) && tag.attrs.get("type") === '"submit"');
    if (hasButton && !hasSubmit && !externalSubmit) problems.push(`${span.tag.line}: <form> 里有按钮,却没有一颗 type="submit"`);
  }
  return problems;
}

describe("按钮的 type", () => {
  it("Button 不写 type=button;表单有提交的那一颗;submit 的按钮连着一张表单", () => {
    const found = tsxSources()
      .filter((file) => !OWNERS.some((owner) => file.startsWith(owner)))
      .flatMap((file) => buttonTypeProblems(readSource(file)).map((problem) => `${file}:${problem}`));
    expect(found).toEqual([]);
  });

  it("认得出三种问题", () => {
    const code = [
      '<Button type="button">取消</Button>',
      "<form onSubmit={save}>",
      "  <Input />",
      "  <Button>保存</Button>",
      "</form>",
      '<Button type="submit">发出</Button>',
      "<form onSubmit={go}>",
      "  <Input />",
      "</form>",
    ].join("\n");
    expect(buttonTypeProblems(code)).toEqual([
      '1: <Button type="button"> —— 默认就是,别写',
      '6: <Button type="submit"> 不在 <form> 里,也没有 form= 指着一张表单',
      '2: <form> 里有按钮,却没有一颗 type="submit"',
    ]);
  });

  it("表单外面用 form= 指过来的那颗算这张表单的提交", () => {
    const code = ['<Button type="submit" form="f">存</Button>', '<form id="f" onSubmit={save}>', "  <Input />", "  <Button>清空</Button>", "</form>"].join("\n");
    expect(buttonTypeProblems(code)).toEqual([]);
  });
});
