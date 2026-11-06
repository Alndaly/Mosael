/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkflowsPanel } from "./WorkflowsPanel";

const getWorkflowLibrary = vi.hoisted(() => vi.fn());
const openWorkbench = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ getWorkflowLibrary: (...args: unknown[]) => getWorkflowLibrary(...args) }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("./workbenchSession", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./workbenchSession")>()),
  openWorkbench: (...args: unknown[]) => openWorkbench(...args),
}));

const TARGET = { instanceId: "i1", instanceName: "ComfyUI", workspaceId: "w1", url: "http://127.0.0.1:8188" };

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><WorkflowsPanel target={TARGET} /></QueryClientProvider>);
}

describe("工作流面板", () => {
  afterEach(() => {
    cleanup();
    getWorkflowLibrary.mockReset();
    openWorkbench.mockReset().mockResolvedValue({ ok: true, outcome: "opened" });
  });

  it("列出当前连接的工作流,点开一张时用同一个工作台打开;新建走 fresh", async () => {
    getWorkflowLibrary.mockResolvedValue({
      workflows: [{ label: "人像", path: "portrait.json", missing_nodes: [], missing_models: [] }],
      others: [], folders: [], trash: [], manager: { version: "" }, editor: null,
    });
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /人像/ }));
    await waitFor(() => expect(openWorkbench).toHaveBeenCalledWith(TARGET, { path: "portrait.json" }));

    fireEvent.click(screen.getByRole("button", { name: /workbenchWorkflowsNew/ }));
    await waitFor(() => expect(openWorkbench).toHaveBeenCalledWith(TARGET, { fresh: true }));
  });
});
