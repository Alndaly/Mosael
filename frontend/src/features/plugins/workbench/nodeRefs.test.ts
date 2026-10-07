import { describe, expect, it } from "vitest";

import { MARKDOWN_REF } from "@/components/markdown/markdownRefs";
import { linkNodeRefs } from "./nodeRefs";

const link = (ref: string) => `[#${ref}](${MARKDOWN_REF}${ref})`;

describe("回复里指节点的写法换成定位链接", () => {
  it("根图的 #12、子图的 #12:5、负的编号;中文标点、括号、行首旁边都认", () => {
    expect(linkNodeRefs("#3 KSampler 的 steps 是 0(#459:451 缺模型),#-2 是组节点。"))
      .toBe(`${link("3")} KSampler 的 steps 是 0(${link("459:451")} 缺模型),${link("-2")} 是组节点。`);
    expect(linkNodeRefs("见 (#12) 和 #7:1:2")).toBe(`见 (${link("12")}) 和 ${link("7:1:2")}`);
    expect(linkNodeRefs("#4: KSampler"), "后面跟冒号说明的也认").toBe(`${link("4")}: KSampler`);
  });

  it("代码、链接、网址、HTML 实体、连着单词的、标题不动", () => {
    const untouched = ["`#12` 和 ``#3 ``", "`看 #12 的 steps`", "[#12](https://x.test/#12)", "https://github.com/a/b/issues#12", "&#123;", "issue#12",
                       "# 12 标题", "#12a", "#1:2:3:4:5:6:7:8:9:10:11:12:13:14:15:16:17:18"];
    for (const one of untouched) expect(linkNodeRefs(one), one).toBe(one);
  });

  it("围栏代码块里的整段不动,块外照常", () => {
    const text = ["先看 #4:", "```json", '{"id": "#4"}', "```", "~~~", "#5", "~~~", "再看 #6"].join("\n");
    expect(linkNodeRefs(text)).toBe(
      [`先看 ${link("4")}:`, "```json", '{"id": "#4"}', "```", "~~~", "#5", "~~~", `再看 ${link("6")}`].join("\n"));
  });
});
