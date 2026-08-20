/**
 * 「N 个子代理」的数据提取:从时间线里挑出 run_subagent 调用,并解出各自的存档。
 *
 * 存档在 result.details.subagent(sidecar 存的,不回填给模型)。三种形态都要接得住:
 * 结构化对象、字符串化 JSON(有的链路会把 result 先转成字符串)、以及**老版本没有存档** ——
 * 老卡照样进列表,详情里如实说没有轨迹,而不是把旧记录藏起来。
 */
import { describe, expect, it } from "vitest";

import { collectSubagentRuns } from "./SubagentPanel";
import type { AgentTimelineItem } from "./ToolCalls";

const archive = {
  task: "扫一遍素材找片头",
  steps: 3,
  error: null,
  trace: [
    { type: "text", text: "先列出全部素材" },
    { type: "tool", id: "s1", name: "list_assets", args: {}, result: { ok: 1 }, isError: false },
  ],
};

function runCall(result: unknown): AgentTimelineItem {
  return { type: "tool", tool: { id: "p1", name: "run_subagent", args: { task: "扫一遍素材找片头" }, status: "done", result } as never };
}

describe("collectSubagentRuns", () => {
  it("结构化存档解得出", () => {
    const runs = collectSubagentRuns([runCall({ details: { subagent: archive } })]);
    expect(runs).toHaveLength(1);
    expect(runs[0].archive?.steps).toBe(3);
    expect(runs[0].archive?.trace).toHaveLength(2);
  });

  it("字符串化的 result 也解得出 —— 有的链路会把它先转成字符串", () => {
    const runs = collectSubagentRuns([runCall(JSON.stringify({ details: { subagent: archive } }))]);
    expect(runs[0].archive?.steps).toBe(3);
  });

  it("老版本没存档:照样进列表,archive 为 null(详情里如实说没有轨迹)", () => {
    const runs = collectSubagentRuns([runCall({ content: [{ type: "text", text: "{}" }] })]);
    expect(runs).toHaveLength(1);
    expect(runs[0].archive).toBeNull();
  });

  it("别的工具调用不掺进来", () => {
    const timeline: AgentTimelineItem[] = [
      { type: "tool", tool: { id: "x", name: "list_assets", args: {}, status: "done" } as never },
      { type: "text", text: "好的" },
    ];
    expect(collectSubagentRuns(timeline)).toHaveLength(0);
  });
});
