/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listBoards: vi.fn(),
  listWorkflows: vi.fn(),
  fetchWorkflowNodeTypes: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import type { Workspace } from "@/api/client";
import { BoardsView } from "@/features/boards/BoardsView";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";
import { gotoSection } from "@/lib/deepLink";

const workspace = { id: "w1", name: "测试工作区" } as Workspace;

function pending<T>(): Promise<T> {
  return new Promise(() => undefined);
}

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("刷新详情页时恢复持久化选择", () => {
  beforeEach(() => {
    localStorage.clear();
    apiMocks.listBoards.mockReset().mockReturnValue(pending());
    apiMocks.listWorkflows.mockReset().mockReturnValue(pending());
    apiMocks.fetchWorkflowNodeTypes.mockReset().mockReturnValue(pending());
  });

  it("创意画板首帧保持详情上下文,不闪现画板列表", () => {
    localStorage.setItem("mosael:selected:boards:w1", "board-1");
    renderWithQuery(<BoardsView workspace={workspace} />);

    expect(screen.getByTestId("boards-detail-restoring")).toBeInTheDocument();
    expect(screen.queryByText("navBoards")).toBeNull();
  });

  it("工作流首帧保持详情上下文,不闪现工作流列表", () => {
    localStorage.setItem("mosael:selected:workflows", "workflow-1");
    renderWithQuery(<WorkflowsView workspace={workspace} />);

    expect(screen.getByTestId("workflows-detail-restoring")).toBeInTheDocument();
    expect(screen.queryByText("navWorkflows")).toBeNull();
  });

  it("工作流对象先恢复、节点类型仍在加载时也不回落列表", async () => {
    localStorage.setItem("mosael:selected:workflows", "workflow-1");
    let resolveWorkflows!: (value: Array<Record<string, unknown>>) => void;
    apiMocks.listWorkflows.mockReturnValue(new Promise((resolve) => {
      resolveWorkflows = resolve;
    }));
    renderWithQuery(<WorkflowsView workspace={workspace} />);

    await act(async () => resolveWorkflows([
      {
        id: "workflow-1",
        workspace_id: "w1",
        name: "测试工作流",
        description: "",
        graph: { nodes: [], edges: [] },
      },
    ]));
    await waitFor(() => expect(apiMocks.listWorkflows).toHaveBeenCalled());
    expect(screen.getByTestId("workflows-detail-restoring")).toBeInTheDocument();
    expect(screen.queryByText("navWorkflows")).toBeNull();
  });
});

describe("从页面起点进来(统计页的数字)时不恢复上次的详情", () => {
  beforeEach(() => {
    localStorage.clear();
    window.location.hash = "#/statistics";
    apiMocks.listWorkflows.mockReset().mockResolvedValue([
      { id: "workflow-1", workspace_id: "w1", name: "上次开着的那条", description: "", graph: { nodes: [], edges: [] }, created_at: "2026-09-20T00:00:00", updated_at: "2026-09-20T00:00:00" },
    ]);
    apiMocks.fetchWorkflowNodeTypes.mockReset().mockReturnValue(pending());
  });

  it("工作流页落在列表 —— 首帧就是,不先闪一下详情;之后从侧栏回来也还是列表", async () => {
    // 用户上次停在某条工作流的详情里。侧栏点回来恢复它是对的(上面几条);从数字点进来不是。
    localStorage.setItem("mosael:selected:workflows", "workflow-1");
    gotoSection("workflows");
    expect(window.location.hash).toBe("#/workflows");

    const first = renderWithQuery(<WorkflowsView workspace={workspace} />);
    expect(screen.queryByTestId("workflows-detail-restoring")).toBeNull();
    expect(await screen.findByText("上次开着的那条")).toBeInTheDocument();
    expect(screen.queryByTestId("workflows-detail-restoring")).toBeNull();
    // 看到的是列表,记住的也得是列表:否则下次从侧栏进来,又跳回那条旧详情。
    await waitFor(() => expect(localStorage.getItem("mosael:selected:workflows")).toBeNull());
    first.unmount();

    renderWithQuery(<WorkflowsView workspace={workspace} />);
    expect(await screen.findByText("上次开着的那条")).toBeInTheDocument();
    expect(screen.queryByTestId("workflows-detail-restoring")).toBeNull();
  });
});
