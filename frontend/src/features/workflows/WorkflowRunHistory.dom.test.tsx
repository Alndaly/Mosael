/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listWorkflowRuns: vi.fn(),
  listJobEvents: vi.fn(),
  listJobChildren: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import { WorkflowRunHistory } from "@/features/workflows/WorkflowRunHistory";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderHistory() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowRunHistory
        workflowId="wf1"
        registry={{ get: () => undefined }}
        mode="docked"
        onModeChange={vi.fn()}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

//: 用户点了停止的那一次:列表行说「已取消」(走 i18n,不是英文原文 cancelled),
//: 停下时在跑的那一步也说已取消,而不是一个红叉「失败」。
it("被取消的运行:没有 message 时说状态的译名;在跑的那一步显示已取消", async () => {
  apiMocks.listWorkflowRuns.mockResolvedValue([
    { id: "j1", kind: "workflow", status: "cancelled", message: "", created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10", payload: {} },
  ]);
  apiMocks.listJobEvents.mockResolvedValue([
    { id: "e1", job_id: "j1", type: "workflow.node.started", created_at: "2026-09-19T04:00:01Z", payload: { node_id: "gen", name: "生成" } },
    { id: "e2", job_id: "j1", type: "job.cancelled", created_at: "2026-09-19T04:00:10Z", payload: {} },
  ]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  renderHistory();

  expect(await screen.findByText("runStatus_cancelled")).toBeInTheDocument();
  expect(screen.queryByText("cancelled")).toBeNull();
  expect(await screen.findByText("wfStepCancelled")).toBeInTheDocument();
});
