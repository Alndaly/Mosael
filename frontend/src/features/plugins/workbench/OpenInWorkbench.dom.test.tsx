/** @vitest-environment jsdom */

/**
 * AI 工作台里选中的模型旁边的「在工作台里打开」(ADR 0038 §8):这个模型是那个连接的工作流库里的一张 ComfyUI 工作流、桌面版
 * 开得了工作台时才有;点了开的就是那一张。不是工作流的模型、插件没报 ComfyUI 编辑器的、网页版,都不摆。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getWorkflowLibrary: vi.fn(), getLocalService: vi.fn(), ensureLocalService: vi.fn() }));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { OpenInWorkbench } from "./OpenInWorkbench";
import { resetWorkbench } from "./workbenchSession";

function mount(model = "人像/古风.json") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OpenInWorkbench instanceId="i1" instanceName="ComfyUI · 本机" model={model} workspaceId="w1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.getLocalService.mockReset();
  api.getLocalService.mockResolvedValue(null);
  api.ensureLocalService.mockReset();
  api.getWorkflowLibrary.mockReset();
  api.getWorkflowLibrary.mockResolvedValue({
    workflows: [{ path: "人像/古风.json" }], editor: { kind: "comfyui", url: "http://127.0.0.1:8188" },
  });
});
afterEach(() => {
  resetWorkbench();
  vi.unstubAllGlobals();
});

describe("AI 工作台里的「在工作台里打开」", () => {
  it("选中的是这台 ComfyUI 上的一张工作流:点了在工作台里打开那一张", async () => {
    const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "workflowOpenInWorkbench" }));
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledWith({
      connectionId: "i1", url: "http://127.0.0.1:8188", name: "ComfyUI · 本机", path: "人像/古风.json",
    }));
    expect(api.getWorkflowLibrary).toHaveBeenCalledWith("i1", "w1");
  });

  it("不是工作流的模型、插件没报 ComfyUI 编辑器、网页版:都不摆", async () => {
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench: vi.fn(), onComfyWorkbench: () => () => undefined });
    const builtin = mount("__builtin__");
    await waitFor(() => expect(api.getWorkflowLibrary).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "workflowOpenInWorkbench" })).toBeNull();
    builtin.unmount();
    api.getWorkflowLibrary.mockResolvedValue({ workflows: [{ path: "人像/古风.json" }], editor: null });
    const noEditor = mount();
    await waitFor(() => expect(api.getWorkflowLibrary).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "workflowOpenInWorkbench" })).toBeNull();
    noEditor.unmount();
    vi.unstubAllGlobals();
    mount();
    expect(screen.queryByRole("button", { name: "workflowOpenInWorkbench" })).toBeNull();
    expect(api.getWorkflowLibrary, "网页版不去问").toHaveBeenCalledTimes(2);
  });

  it("连接背后是停着的本机服务:先请宿主起好,按钮上写「正在启动」,就绪了才开", async () => {
    let ready: (value: unknown) => void = () => undefined;
    api.getLocalService.mockResolvedValue({ state: "stopped" });
    api.ensureLocalService.mockReturnValue(new Promise((resolve) => (ready = resolve)));
    const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "workflowOpenInWorkbench" }));
    expect(await screen.findByRole("button", { name: "localServiceOpenStarting" })).toBeTruthy();
    expect(api.ensureLocalService).toHaveBeenCalledWith("i1");
    expect(openComfyWorkbench, "等它就绪再开").not.toHaveBeenCalled();
    ready({ state: "running" });
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "workflowOpenInWorkbench" })).toBeTruthy();
  });

  it("本机服务已经在跑:不等、不摆「正在启动」", async () => {
    api.getLocalService.mockResolvedValue({ state: "running" });
    const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "workflowOpenInWorkbench" }));
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalled());
    expect(api.ensureLocalService).not.toHaveBeenCalled();
  });
});
