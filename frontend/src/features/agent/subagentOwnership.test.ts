import { describe, expect, it } from "vitest";

import { collectCitations } from "./citations";
import { toolCallIds, turnBlocks, type AgentTimelineItem } from "./ToolCalls";

const parentTool = { id: "parent", name: "run_subagent", status: "done" } as const;
const timeline: AgentTimelineItem[] = [
  { type: "tool", tool: parentTool },
  {
    type: "subtool",
    parent_id: "parent",
    tool: {
      id: "child",
      name: "fetch_url",
      status: "done",
      result: [{ url: "https://example.com/source", title: "Source" }],
    },
  },
];

describe("subagent UI ownership", () => {
  it("父对话只渲染父工具卡", () => {
    expect(turnBlocks(timeline)).toEqual([{ type: "tools", tools: [parentTool] }]);
    expect([...toolCallIds([timeline])]).toEqual(["parent"]);
  });

  it("子智能体来源不冒充父回答的引用", () => {
    expect(collectCitations(timeline).size).toBe(0);
  });
});
