/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

/**
 * 选择卡的问题和选项说明是**模型写的**,会带 `**强调**` 和 `代码` —— 按 markdown 渲染,
 * 不把记号原样摆在用户要做选择的那一行上。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const api = vi.fn(async (_path: string) => [
  {
    id: "q1",
    workspace_id: "w1",
    session_id: "s1",
    status: "pending",
    created_at: "2026-09-25T00:00:00Z",
    questions: [
      {
        header: "画幅",
        question: "成片用**哪个**比例?",
        multi_select: false,
        options: [{ label: "竖屏", description: "适合 `抖音`,**推荐**" }],
      },
    ],
  },
]);
vi.mock("@/api/client", () => ({ api: (path: string) => api(path) }));

import { InlineQuestions } from "@/features/agent/InlineQuestions";

it("问题和选项说明里的记号渲染成格式", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <InlineQuestions sessionId="s1" />
    </QueryClientProvider>,
  );
  expect((await screen.findByText("哪个")).tagName).toBe("STRONG");
  expect(screen.getByText("推荐").tagName).toBe("STRONG");
  expect(screen.getByText("抖音").tagName).toBe("CODE");
  // 选项是一整颗按钮:里面不能再有链接。
  expect(container.querySelector("button a")).toBeNull();
  expect(container.textContent).not.toMatch(/\*\*|`/);
});
