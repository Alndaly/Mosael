/**
 * 渲染侧现在只保留一件事:认出 `show_widget` 的小界面(它画在发起它的那一行明细里)。
 *
 * 「哪个工具算做出了产出、该织进答案」那条固定规则已经删掉(维护者 2026-10-22):答案区只放智能体
 * 最后的正文,要展示什么由它在 markdown 里自己写。
 */
import { describe, expect, it } from "vitest";

import { SHOW_WIDGET_TOOL, widgetOfTool } from "@/features/agent/turnOutputs";
import type { ToolCall } from "@/features/agent/ToolCalls";

function tool(name: string, args: unknown, status: ToolCall["status"] = "done"): ToolCall {
  return { id: "t1", name, args, status, result: { ok: true } };
}

describe("show_widget 的小界面", () => {
  it("成功的那次,内容取自参数(不取自结果:结果只回一句「已显示」)", () => {
    expect(widgetOfTool(tool(SHOW_WIDGET_TOOL, { title: "地图", html: "<p>hi</p>" }))).toEqual({
      id: "t1",
      title: "地图",
      html: "<p>hi</p>",
    });
  });

  it("失败 / 空内容 / 别的工具:都不算(不给自己造一个坏掉的框)", () => {
    expect(widgetOfTool(tool(SHOW_WIDGET_TOOL, { html: "<p>hi</p>" }, "error"))).toBeNull();
    expect(widgetOfTool(tool(SHOW_WIDGET_TOOL, { html: "   " }))).toBeNull();
    expect(widgetOfTool(tool("get_job", { html: "<p>hi</p>" }))).toBeNull();
  });
});
