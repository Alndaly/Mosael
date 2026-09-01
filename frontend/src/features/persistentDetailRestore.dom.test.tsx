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
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import type { Workspace } from "@/api/client";
import { BoardsView } from "@/features/boards/BoardsView";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";

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
    localStorage.setItem("openstudio:selected:boards:w1", "board-1");
    renderWithQuery(<BoardsView workspace={workspace} />);

    expect(screen.getByTestId("boards-detail-restoring")).toBeInTheDocument();
    expect(screen.queryByText("navBoards")).toBeNull();
  });

  it("工作流首帧保持详情上下文,不闪现工作流列表", () => {
    localStorage.setItem("openstudio:selected:workflows", "workflow-1");
    renderWithQuery(<WorkflowsView workspace={workspace} />);

    expect(screen.getByTestId("workflows-detail-restoring")).toBeInTheDocument();
    expect(screen.queryByText("navWorkflows")).toBeNull();
  });

  it("工作流对象先恢复、节点类型仍在加载时也不回落列表", async () => {
    localStorage.setItem("openstudio:selected:workflows", "workflow-1");
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
