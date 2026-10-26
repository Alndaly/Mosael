/** @vitest-environment jsdom */

import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));

import { ToolCalls } from "@/features/agent/ToolCalls";

const LONG_PLUGIN_TOOL = "plugin__9d18419c50224e83a0b191ad00d3019c__server_status";

function renderLongPluginTool() {
  const tool = {
    id: "tool-1",
    name: LONG_PLUGIN_TOOL,
    status: "done" as const,
    usage: { duration_seconds: 1.5 },
  };
  render(<ToolCalls tools={[tool]} />);
  return screen.getByText(LONG_PLUGIN_TOOL);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("工具调用行的长标题", () => {
  it("插件工具名参与收缩并截断,不会把右侧耗时挤出这一行", () => {
    const name = renderLongPluginTool();
    expect(name.className).toContain("truncate");
    expect(name.className).toContain("min-w-0");
    expect(name.className).not.toContain("flex-none");
  });
});
