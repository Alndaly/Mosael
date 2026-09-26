import { describe, expect, it } from "vitest";

import { noteSnippet } from "./noteSnippet";

describe("笔记的一行摘要只留读得懂的字", () => {
  it("代码块围栏、图片地址、表格竖线和分隔行都不露出来(截图里那一条)", () => {
    const markdown = "```shell\necho a\n```\n大卡司\n![](https://example.com/images/20260902164446959.png)\n| da | das |\n| --- | --- |\n| 1 | 2 |";
    //: 代码块的语言名(shell)也是围栏的一部分,不是正文。
    expect(noteSnippet(markdown)).toBe("echo a 大卡司 da das 1 2");
  });

  it("粗体、标题、引用、列表记号去掉,链接留文字", () => {
    expect(noteSnippet("# 标题\n> 引一句\n- 编号:**KP-7734**,见[文档](https://x.y)")).toBe("标题 引一句 编号:KP-7734,见文档");
  });

  it("超长截断并带省略号", () => {
    expect(noteSnippet("字".repeat(130), 120)).toBe(`${"字".repeat(120)}…`);
  });
});
