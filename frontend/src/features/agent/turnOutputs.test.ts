/** 一轮回答的产出:哪些素材算「这一轮做出来的」、回执带来的归给谁、智能体给的小界面。 */
import { describe, expect, it } from "vitest";

import type { AgentTimelineItem, ToolCall } from "@/features/agent/ToolCalls";
import { producedByTool, receivedAssetIdsByMessage, turnWidgets } from "@/features/agent/turnOutputs";

function tool(name: string, result: unknown, extra: Partial<ToolCall> = {}): { type: "tool"; tool: ToolCall } {
  return { type: "tool", tool: { id: `${name}-${Math.random()}`, name, status: "done", result, ...extra } };
}

describe("这一轮做出来的素材", () => {
  it("任务终态的 result 是产物:生成的多张、渲染的一份都认", () => {
    expect(producedByTool(tool("get_job", { id: "j", status: "succeeded", result: { asset_ids: ["a", "b"] } }).tool)).toEqual(["a", "b"]);
    expect(producedByTool(tool("get_job", { id: "j", status: "succeeded", result: { asset_id: "r" } }).tool)).toEqual(["r"]);
  });

  it("没跑完、失败的任务什么都没做出来", () => {
    expect(producedByTool(tool("get_job", { status: "running", result: { asset_ids: ["a"] } }).tool)).toEqual([]);
    expect(producedByTool(tool("get_job", { status: "failed", result: { asset_id: "a" } }).tool)).toEqual([]);
  });

  it("从一份素材派生出来的才算,原料本身不算", () => {
    const grid = tool("split_image_grid", { asset_ids: ["c1", "c2"], source_asset_id: "src" });
    expect(producedByTool(grid.tool)).toEqual(["c1", "c2"]);
    const mask = tool("create_mask", { asset_id: "m", source_asset_id: "src" });
    expect(producedByTool(mask.tool)).toEqual(["m"]);
  });

  it("同步工具直接交回的产出(computer_screenshot):produced_asset_ids 算,平铺的 asset_ids 不算", () => {
    expect(
      producedByTool(tool("computer_screenshot", { window: "main", produced_asset_ids: ["shot1"] }).tool),
    ).toEqual(["shot1"]);
    // 平铺 asset_ids 是「碰过的」读法 —— 一份随便什么的 id 列表不能进答案区。
    expect(producedByTool(tool("some_list", { asset_ids: ["a", "b"] }).tool)).toEqual([]);
  });

  it("碰过的不算产出:分析的图、改标签的那份、解析文档的那份", () => {
    // 这些结果顶层也带 asset_id,但它们说的是「我对这份做了什么」,不是「我做出了这份」。
    expect(producedByTool(tool("analyze_image", { asset_id: "mine", description: "一只猫" }).tool)).toEqual([]);
    expect(producedByTool(tool("parse_document", { asset_id: "doc", extraction_id: "e", job_id: "j" }).tool)).toEqual([]);
  });

  it("运行时包过一层的结果照样认(MCP 的 {result}、pi 的 details.data、文本 JSON)", () => {
    const wrapped = { result: { status: "succeeded", result: { asset_ids: ["w"] } } };
    expect(producedByTool(tool("get_job", wrapped).tool)).toEqual(["w"]);
    const text = { content: [{ type: "text", text: JSON.stringify({ status: "succeeded", result: { asset_id: "t" } }) }] };
    expect(producedByTool(tool("get_job", text).tool)).toEqual(["t"]);
  });

});

describe("回执带来的素材归给接着的那一条回答", () => {
  const receipt = (id: string, assetIds: string[], extra: Record<string, unknown> = {}) => ({
    id,
    role: "job_receipt",
    payload: { job_id: `job-${id}`, asset_ids: assetIds, ...extra },
  });

  it("连着到的几条回执归给同一条回答,之前的回答不沾", () => {
    const { byMessage, pending } = receivedAssetIdsByMessage([
      { id: "u1", role: "user" },
      { id: "a1", role: "assistant" },
      receipt("r1", ["x"]),
      receipt("r2", ["y", "z"]),
      { id: "a2", role: "assistant" },
    ]);
    expect(byMessage.get("a1")).toBeUndefined();
    expect(byMessage.get("a2")).toEqual(["x", "y", "z"]);
    expect(pending).toEqual([]);
  });

  it("回执搭了用户那一轮的车:回执、他那句话、回答 —— 还是归给那条回答", () => {
    const { byMessage } = receivedAssetIdsByMessage([receipt("r1", ["x"]), { id: "u2", role: "user" }, { id: "a2", role: "assistant" }]);
    expect(byMessage.get("a2")).toEqual(["x"]);
  });

  it("后面还没有回答的(那一轮正在跑)记成 pending;没交给智能体的不算", () => {
    const { pending } = receivedAssetIdsByMessage([
      { id: "a1", role: "assistant" },
      receipt("r1", ["x"]),
      receipt("r2", ["w"], { undelivered: true }),
    ]);
    expect(pending).toEqual(["x"]);
  });
});

describe("智能体给的小界面", () => {
  it("只认成功了的 show_widget,内容取自参数", () => {
    const timeline: AgentTimelineItem[] = [
      { type: "tool", tool: { id: "w1", name: "show_widget", status: "done", args: { title: "地图", html: "<div>map</div>" }, result: { shown: true } } },
      { type: "tool", tool: { id: "w2", name: "show_widget", status: "error", args: { title: "坏的", html: "<div/>" } } },
      { type: "tool", tool: { id: "w3", name: "show_widget", status: "done", args: { title: "空的", html: "  " } } },
      { type: "tool", tool: { id: "w4", name: "list_assets", status: "done", args: { html: "<b>不是</b>" } } },
    ];
    expect(turnWidgets(timeline)).toEqual([{ id: "w1", title: "地图", html: "<div>map</div>" }]);
  });
});
