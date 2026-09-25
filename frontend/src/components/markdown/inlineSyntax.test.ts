import { describe, expect, it } from "vitest";

import { parseInline, toPlainText } from "./inlineSyntax";

/**
 * 数据里一行字的 markdown。规则和官网 website/src/lib/inline-markdown.ts 是同一套 ——
 * 这里的用例也照着那边的来,两边哪天走岔了,先在这里红。
 */
describe("parseInline", () => {
  it("行内记号各自落成对应的节点", () => {
    expect(parseInline("把**限时直链**交回")).toEqual([
      { type: "text", value: "把" },
      { type: "strong", children: [{ type: "text", value: "限时直链" }] },
      { type: "text", value: "交回" },
    ]);
    expect(parseInline("`export default` 一个组件")[0]).toEqual({ type: "code", value: "export default" });
    expect(parseInline("*斜*_体_").map((node) => node.type)).toEqual(["emphasis", "emphasis"]);
    expect(parseInline("~~旧~~")[0].type).toBe("delete");
    expect(parseInline("[文档](https://example.com)")[0]).toEqual({
      type: "link",
      href: "https://example.com",
      children: [{ type: "text", value: "文档" }],
    });
    expect(parseInline("<https://example.com>")[0]).toMatchObject({ type: "link", href: "https://example.com" });
  });

  it("空一行是换行,单个换行只是空格", () => {
    expect(parseInline("第一段\n\n第二段").map((node) => node.type)).toEqual(["text", "break", "text"]);
    expect(parseInline("同一段\n接着写")).toEqual([{ type: "text", value: "同一段 接着写" }]);
  });

  it("中文标点紧贴着收尾记号也认", () => {
    // 发布说明里的写法:「**3D 场景能隐藏物体、能删镜头,** 从 Blender…」
    expect(parseInline("**能删镜头,** 从")[0].type).toBe("strong");
    expect(parseInline("**价格一键预填:** 内置")[0].type).toBe("strong");
  });
});

describe("toPlainText", () => {
  it("去掉记号只留字面", () => {
    expect(toPlainText("⚠️ **不隔离**,直接在你的电脑上运行")).toBe("⚠️ 不隔离,直接在你的电脑上运行");
    expect(toPlainText("每行一条 `素材id` 或 `素材id:角色`")).toBe("每行一条 素材id 或 素材id:角色");
    expect(toPlainText("见 [文档](https://example.com) 与 ![图](a.png)")).toBe("见 文档 与 图");
    expect(toPlainText("第一段\n\n  第二段")).toBe("第一段 第二段");
  });

  it("不是记号的星号、下划线、反引号原样留着", () => {
    // snake_case 的名字不能被拆成斜体 —— 旧的剥法把 `_` 一把删掉,run_host_code 成了 runhostcode。
    expect(toPlainText("run_host_code 和 snake_case_name")).toBe("run_host_code 和 snake_case_name");
    expect(toPlainText("2 * 3 * 4")).toBe("2 * 3 * 4");
    expect(toPlainText("没收尾的 **粗体")).toBe("没收尾的 **粗体");
    expect(toPlainText("单个 ` 反引号")).toBe("单个 ` 反引号");
    expect(toPlainText("转义 \\*不是斜体\\*")).toBe("转义 *不是斜体*");
    // 代码里的记号不再解析。
    expect(toPlainText("`a*b*c` 与 `{{…}}`")).toBe("a*b*c 与 {{…}}");
  });
});
