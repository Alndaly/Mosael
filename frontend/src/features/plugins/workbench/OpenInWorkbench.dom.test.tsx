/** @vitest-environment jsdom */

/**
 * AI 工作台里选中的模型旁边的「在工作台里打开」(ADR 0038 §8):这个模型来自一个认领了工作流库的连接、桌面版开得了工作台时
 * 就摆;点了开的就是那一张。**摆不摆不看现问的工作流库** —— 它读不回来(本机服务停着、目录太大、超时)时按钮曾悄悄消失。
 * 没认领工作流库的连接、网页版,都不摆。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getWorkflowLibrary: vi.fn(), getLocalService: vi.fn(), listPluginPackages: vi.fn(),
  getPluginReachability: vi.fn(),
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { readHint } from "@/test/hint";

import { OpenInWorkbench } from "./OpenInWorkbench";
import { resetWorkbench } from "./workbenchSession";

function mount(model = "人像/古风.json") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OpenInWorkbench instanceId="i1" path={model} workspaceId="w1" />
    </QueryClientProvider>,
  );
}

async function clickReady() {
  let button = await screen.findByRole("button", { name: "workflowOpenInWorkbench" });
  //: 检查中按钮套着禁用壳，确认可用后 React 会把它重挂 —— 每次重新找，别握住旧节点。
  await waitFor(() => {
    button = screen.getByRole("button", { name: "workflowOpenInWorkbench" });
    expect(button.hasAttribute("disabled")).toBe(false);
  });
  fireEvent.click(button);
  return button;
}

function comfyPackage(provides = ["workflow_library"], address = "http://127.0.0.1:8189") {
  return {
    provides, summary_field: "base_url",
    instances: [{ id: "i1", name: "ComfyUI · 本机", config: { base_url: address }, blocked_reason: null }],
  };
}

beforeEach(() => {
  api.getLocalService.mockReset();
  api.getLocalService.mockResolvedValue(null);
  api.getPluginReachability.mockReset();
  api.getPluginReachability.mockResolvedValue({ reachable: true, address: "http://127.0.0.1:8189" });
  api.listPluginPackages.mockReset();
  api.listPluginPackages.mockResolvedValue([comfyPackage()]);
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
  it("选中的是这台 ComfyUI 上的一张工作流:点了用连接自己的地址在工作台里打开那一张,不现问工作流库", async () => {
    const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    await clickReady();
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledWith({
      connectionId: "i1", url: "http://127.0.0.1:8189", name: "ComfyUI · 本机", path: "人像/古风.json",
    }));
    //: 维护者报的「一直 loading」:本机服务停着时,先问库会在服务起来之前一直等到插件超时。
    expect(api.getWorkflowLibrary).not.toHaveBeenCalled();
  });

  it("连接没写地址:才去问工作流库,用它报的编辑器地址", async () => {
    api.listPluginPackages.mockResolvedValue([comfyPackage(["workflow_library"], "")]);
    const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    await clickReady();
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledWith(expect.objectContaining({ url: "http://127.0.0.1:8188" })));
    expect(api.getWorkflowLibrary).toHaveBeenCalledWith("i1", "w1");
  });

  it("摆出来之前不去现问工作流库", async () => {
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench: vi.fn(), onComfyWorkbench: () => () => undefined });
    mount();
    expect(await screen.findByRole("button", { name: "workflowOpenInWorkbench" })).toBeTruthy();
    expect(api.getWorkflowLibrary).not.toHaveBeenCalled();
  });

  it("连接没写地址、插件报的编辑器又不是 ComfyUI:点了说打不开,不乱开", async () => {
    api.listPluginPackages.mockResolvedValue([comfyPackage(["workflow_library"], "")]);
    api.getWorkflowLibrary.mockResolvedValue({ workflows: [], editor: { kind: "other", url: "http://x" } });
    const openComfyWorkbench = vi.fn();
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    await clickReady();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(openComfyWorkbench).not.toHaveBeenCalled();
  });

  it("远端那台连不上:按钮是灰的,悬停说是哪个地址连不上;点不了也就不去开", async () => {
    api.getPluginReachability.mockResolvedValue({ reachable: false, address: "http://127.0.0.1:8189" });
    const openComfyWorkbench = vi.fn();
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    //: 置灰之后 Hint 会给按钮多套一层(禁用的按钮自己收不到悬停),按钮重挂 —— 每次重新找。
    const current = () => screen.getByRole("button", { name: "workflowOpenInWorkbench" });
    await screen.findByRole("button", { name: "workflowOpenInWorkbench" });
    await waitFor(() => expect(current().hasAttribute("disabled")).toBe(true));
    const button = current();
    expect(await readHint(button)).toContain("workbenchOpenUnreachable");
    fireEvent.click(button);
    expect(openComfyWorkbench).not.toHaveBeenCalled();
  });

  it("本机服务停着:默认置灰,悬停说要先启动;不去问远端通不通", async () => {
    api.getLocalService.mockResolvedValue({ state: "stopped" });
    const openComfyWorkbench = vi.fn();
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    const button = await screen.findByRole("button", { name: "workflowOpenInWorkbench" });
    await waitFor(async () => expect(await readHint(button)).toContain("workbenchOpenServiceStopped"));
    expect(button.hasAttribute("disabled")).toBe(true);
    fireEvent.click(button);
    expect(openComfyWorkbench).not.toHaveBeenCalled();
    expect(api.getPluginReachability).not.toHaveBeenCalled();
  });

  it("没认领工作流库的连接、网页版:都不摆", async () => {
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench: vi.fn(), onComfyWorkbench: () => () => undefined });
    api.listPluginPackages.mockResolvedValue([comfyPackage([])]);
    const noLibrary = mount();
    await waitFor(() => expect(api.listPluginPackages).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "workflowOpenInWorkbench" })).toBeNull();
    noLibrary.unmount();
    vi.unstubAllGlobals();
    api.listPluginPackages.mockClear();
    mount();
    expect(screen.queryByRole("button", { name: "workflowOpenInWorkbench" })).toBeNull();
    expect(api.listPluginPackages, "网页版不去问").not.toHaveBeenCalled();
  });

  it("本机服务正在启动:置灰并说明还在启动", async () => {
    api.getLocalService.mockResolvedValue({ state: "starting" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench: vi.fn(), onComfyWorkbench: () => () => undefined });
    mount();
    const button = await screen.findByRole("button", { name: "workflowOpenInWorkbench" });
    await waitFor(async () => expect(await readHint(button)).toContain("workbenchOpenServiceStarting"));
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("本机服务已经在跑:不等、不摆「正在启动」", async () => {
    api.getLocalService.mockResolvedValue({ state: "running" });
    const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "workflowOpenInWorkbench" }));
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalled());
  });
});
