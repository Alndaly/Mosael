/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

function renderHistory(viewedRunId: string | null = "j1", onViewRun = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowRunHistory
        workflowId="wf1"
        registry={{ get: () => undefined }}
        viewedRunId={viewedRunId}
        onViewRun={onViewRun}
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

//: 「正在看哪一次」归编辑器:这里只显示它指的那一次,点别的一行是把选择交上去,自己不另记一份 ——
//: 此前面板自己记,于是在历史里点开旧的一次,画布和检查器还停在最近那次。
it("选中项由编辑器给;点另一行交给编辑器,面板自己不换", async () => {
  apiMocks.listWorkflowRuns.mockResolvedValue([
    { id: "new", kind: "workflow", status: "succeeded", message: "最新一次", created_at: "2026-09-19T05:00:00", updated_at: "2026-09-19T05:00:10", payload: {} },
    { id: "old", kind: "workflow", status: "failed", message: "较早一次", created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10", payload: {} },
  ]);
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  const onViewRun = vi.fn();
  renderHistory("old", onViewRun);

  const older = (await screen.findByText("较早一次")).closest("button")!;
  const newer = screen.getByText("最新一次").closest("button")!;
  expect(older.getAttribute("aria-current")).toBe("true");
  expect(newer.getAttribute("aria-current")).toBeNull();
  expect(apiMocks.listJobEvents).toHaveBeenCalledWith("old");

  fireEvent.click(newer);
  expect(onViewRun).toHaveBeenCalledWith("new");
  expect(older.getAttribute("aria-current"), "面板不自己换,等编辑器给").toBe("true");
});
