/**
 * 界面文案表里**不出现模板写法**(`{{…}}`)。
 *
 * 引用在界面上是「节点标题 · 输出 · 子路径」的标签(nodeForms/RefToken),人从下拉里挑、在编辑器里敲 @ 插,从来不用
 * 手写 `{{节点.输出}}`。可循环 / 子图的提示此前写着「子流程内用 {{loop.item}}」,就绪检查写着「代码里的 {{…}}」——
 * 用户明确不想再在界面上看到这种写法。后端节点目录的说明同一条,见 backend/tests/test_ui_copy_has_no_template_syntax.py。
 */
import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

describe("界面文案表", () => {
  it.each(Object.keys(messages))("%s:没有一条摆着 {{…}}", (locale) => {
    const table = messages[locale as keyof typeof messages] as Record<string, string>;
    const offenders = Object.entries(table).filter(([, text]) => typeof text === "string" && text.includes("{{"));
    expect(offenders.map(([key]) => key)).toEqual([]);
  });
});
