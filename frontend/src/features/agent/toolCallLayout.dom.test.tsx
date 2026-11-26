/** @vitest-environment jsdom */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToolCalls tools={[tool]} />
    </QueryClientProvider>,
  );
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

  it("结果里的 error 不会被画成成功", () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ToolCalls
          tools={[{
            id: "tool-failed-result",
            name: "update_asset",
            status: "done",
            result: { error: "素材已经不存在了" },
          }]}
        />
      </QueryClientProvider>,
    );
    const row = container.querySelector<HTMLElement>("[data-tool-call]")!;
    expect(row.getAttribute("data-tool-status")).toBe("error");
    expect(container.textContent).toContain("素材已经不存在了");
  });
});
