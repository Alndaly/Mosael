/** @vitest-environment jsdom */

/** 画板生成节点底栏的「在工作台里打开」:和创作页那颗同一个动作,只是底栏里只摆图标;没开成的原因走提示。 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getWorkflowLibrary: vi.fn(), getLocalService: vi.fn(), ensureLocalService: vi.fn(), listPluginPackages: vi.fn(),
}));
const toast = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/api/client", () => api);
vi.mock("sonner", () => ({ toast }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { OpenInWorkbenchIcon } from "./OpenInWorkbenchIcon";
import { resetWorkbench, workbenchSnapshot } from "./workbenchSession";

function mount(form: string | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OpenInWorkbenchIcon instanceId="i1" path="田园/krea2.json" form={form} workspaceId="w1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.getLocalService.mockReset().mockResolvedValue(null);
  api.listPluginPackages.mockReset().mockResolvedValue([{
    provides: ["workflow_library"], summary_field: "base_url",
    instances: [{ id: "i1", name: "4090", config: { base_url: "http://10.0.0.2:8188" }, blocked_reason: null }],
  }]);
  api.getWorkflowLibrary.mockReset().mockResolvedValue({ workflows: [], editor: { kind: "comfyui", url: "http://10.0.0.2:8188" } });
  toast.error.mockReset();
});
afterEach(() => {
  resetWorkbench();
  vi.unstubAllGlobals();
});

describe("画板节点的「在工作台里打开」", () => {
  it("点了在工作台里打开节点选的那张工作流", async () => {
    const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "workflowOpenInWorkbench" }));
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledWith({
      connectionId: "i1", url: "http://10.0.0.2:8188", name: "4090", path: "田园/krea2.json",
    }));
  });

  it("那台上找不到这张:用提示说出来", async () => {
    vi.stubGlobal("mosaelBrowser", {
      openComfyWorkbench: vi.fn().mockResolvedValue({ ok: true, outcome: "missing" }), onComfyWorkbench: () => () => undefined,
    });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "workflowOpenInWorkbench" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("workflowEditorMissing"));
  });

  it("节点选的是一张表单:开的是表单所在那张工作流,工作台记下要停在那张表单上", async () => {
    const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount("田园/krea2.json#k20");
    fireEvent.click(await screen.findByRole("button", { name: "workflowOpenInWorkbench" }));
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledWith(expect.objectContaining({ path: "田园/krea2.json" })));
    expect(workbenchSnapshot().focus).toEqual({ model: "田园/krea2.json#k20" });
  });
});
