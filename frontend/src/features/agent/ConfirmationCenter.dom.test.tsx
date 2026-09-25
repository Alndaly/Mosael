/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

/**
 * 全局确认卡的摘要来自后端文案目录,写着「⚠️ **不隔离**,直接在你的电脑上运行一段 Python」——
 * 这是用户点「批准」之前唯一会读的一行,星号原样露着就把最要紧的那个词淹没了。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

vi.mock("@/api/client", () => ({
  api: async () => [
    {
      id: "c1",
      tool: "run_host_code",
      summary: "⚠️ **不隔离**,直接在你的电脑上运行",
      permission: "write",
      requested_by: "mcp",
      payload: {},
    },
  ],
}));

import { ConfirmationCenter } from "@/features/agent/ConfirmationCenter";

it("摘要里的 **强调** 渲染成粗体", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <ConfirmationCenter workspaceId="w1" />
    </QueryClientProvider>,
  );
  expect((await screen.findByText("不隔离")).tagName).toBe("STRONG");
  expect(container.textContent).not.toContain("**");
});
