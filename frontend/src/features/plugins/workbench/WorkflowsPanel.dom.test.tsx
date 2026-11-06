/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowsPanel } from "./WorkflowsPanel";

const getWorkflowLibrary = vi.hoisted(() => vi.fn());
const openWorkflow = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ getWorkflowLibrary: (...args: unknown[]) => getWorkflowLibrary(...args) }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("./workbenchSession", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./workbenchSession")>()),
  workbenchCall: (...args: unknown[]) => openWorkflow(...args),
}));

const TARGET = { instanceId: "i1", instanceName: "ComfyUI", workspaceId: "w1", url: "http://127.0.0.1:8188" };

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><WorkflowsPanel target={TARGET} /></QueryClientProvider>);
}

describe("工作流面板", () => {
  it("清单还在读时,加载占位吃满右栏剩余高度", () => {
    getWorkflowLibrary.mockReturnValue(new Promise(() => undefined));
    renderPanel();
    expect(screen.getByRole("status").className).toContain("flex-1");
  });

  afterEach(() => {
    cleanup();
    getWorkflowLibrary.mockReset();
    openWorkflow.mockReset().mockResolvedValue({ ok: true });
  });

  it("列出当前连接的工作流,点开一张时用同一个工作台打开;新建走 fresh", async () => {
    getWorkflowLibrary.mockResolvedValue({
      workflows: [{ label: "人像", path: "portrait.json", missing_nodes: [], missing_models: [] }],
      others: [], folders: [], trash: [], manager: { version: "" }, editor: null,
    });
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /人像/ }));
    await waitFor(() => expect(openWorkflow).toHaveBeenCalledWith({
      op: "openWorkflow", graph: null, name: "", path: "portrait.json", ops: [],
    }));

    fireEvent.click(screen.getByRole("button", { name: /workbenchWorkflowsNew/ }));
    await waitFor(() => expect(openWorkflow).toHaveBeenCalledWith({
      op: "openWorkflow", graph: { nodes: [] }, name: "", path: null, ops: [],
    }));
  });
});
