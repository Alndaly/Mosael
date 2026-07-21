import { describe, expect, it } from "vitest";

import { agentTurnParts, type ToolCall } from "@/components/agent/ToolCalls";

const tool = (patch: Partial<ToolCall>): ToolCall => ({
  id: "tool-1",
  name: "list_workflows",
  status: "done",
  args: {},
  result: {},
  ...patch,
});

describe("agentTurnParts", () => {
  it("preserves the timeline order instead of moving tools before all text", () => {
    const parts = agentTurnParts(
      [
        { type: "text", text: "先说明。" },
        { type: "tool", tool: tool({ id: "tool-1" }) },
        { type: "text", text: "再总结。" },
      ],
      [],
      "先说明。再总结。",
    );

    expect(parts.map((part) => part.type)).toEqual(["text", "tool", "text"]);
  });

  it("falls back to the old persisted shape when no timeline exists", () => {
    const parts = agentTurnParts(undefined, [tool({ id: "tool-1" })], "旧消息正文");

    expect(parts.map((part) => part.type)).toEqual(["tool", "text"]);
  });
});
