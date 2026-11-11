/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowsPanel } from "./WorkflowsPanel";

const getWorkflowLibrary = vi.hoisted(() => vi.fn());
const getBundledWorkflows = vi.hoisted(() => vi.fn());
const installBundledWorkflows = vi.hoisted(() => vi.fn());
const openWorkflow = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({
  getWorkflowLibrary: (...args: unknown[]) => getWorkflowLibrary(...args),
  getBundledWorkflows: (...args: unknown[]) => getBundledWorkflows(...args),
  installBundledWorkflows: (...args: unknown[]) => installBundledWorkflows(...args),
}));
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
    getBundledWorkflows.mockReset();
    installBundledWorkflows.mockReset();
    openWorkflow.mockReset().mockResolvedValue({ ok: true });
  });

  it("官方范例:每张单独安装,只发这一张的文件名", async () => {
    getWorkflowLibrary.mockResolvedValue({ workflows: [], others: [], folders: [], trash: [], manager: { version: "" }, editor: null });
    getBundledWorkflows.mockResolvedValue({
      id: "official", title: "官方工作流范例", folder: "mosael/examples", description: "",
      workflows: [{ path: "mosael/examples/h3.json", file: "h3.json", name: "H3", description: "长片", category: "video",
        installed: false, outdated: false, missing_nodes: [], missing_models: [], problem: "" }],
    });
    installBundledWorkflows.mockResolvedValue({ folder: "mosael/examples", installed: ["mosael/examples/h3.json"], updated: [], skipped: [], workflows: [] });
    renderPanel();
    expect(screen.queryByRole("button", { name: "workflowBundleInstallOne" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: /官方工作流范例|workflowBundleInstall/ }));
    fireEvent.click(await screen.findByRole("button", { name: "workflowBundleInstallOne" }));
    await waitFor(() => expect(installBundledWorkflows).toHaveBeenCalledWith("i1", ["h3.json"], "mosael/examples", false));
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
