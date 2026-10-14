/** @vitest-environment jsdom */

/**
 * 插件页连接工具栏的「打开工作台」(ADR 0038):这个连接是 ComfyUI 编辑器、桌面壳开得了工作台时才摆;
 * 点了跳到这台 ComfyUI 的内嵌工作台(不带 `path` —— 开它画布上当前那张,不是指定哪一张)。收起时也在(同一排)。
 * 没报 ComfyUI 编辑器的、网页版(没有桥),都不摆 —— 网页版也不去问工作流库。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getWorkflowLibrary: vi.fn(), getLocalService: vi.fn(), ensureLocalService: vi.fn() }));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import type { PluginInstance } from "@/api/client";
import { OpenConnectionWorkbench } from "./OpenConnectionWorkbench";
import { resetWorkbench } from "./workbenchSession";

const instance = { id: "i1", name: "ComfyUI · 本机" } as PluginInstance;

function mount(target: PluginInstance = instance) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OpenConnectionWorkbench instance={target} workspaceId="w1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.getLocalService.mockReset().mockResolvedValue({ state: "running" });
  api.ensureLocalService.mockReset();
  api.getWorkflowLibrary.mockReset().mockResolvedValue({
    workflows: [], editor: { kind: "comfyui", url: "http://127.0.0.1:8188" },
  });
});
afterEach(() => {
  resetWorkbench();
  vi.unstubAllGlobals();
});

describe("连接工具栏的「打开工作台」", () => {
  it("ComfyUI 连接 + 桌面壳:摆;点了跳到这台的内嵌工作台(编辑器地址照工作流库那份)", async () => {
    const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "pluginConnOpenWorkbench" }));
    await waitFor(() =>
      expect(openComfyWorkbench).toHaveBeenCalledWith({
        connectionId: "i1", url: "http://127.0.0.1:8188", name: "ComfyUI · 本机",
      }),
    );
    expect(api.getWorkflowLibrary).toHaveBeenCalledWith("i1", "w1");
  });

  it("没报 ComfyUI 编辑器、网页版:都不摆;网页版不去问工作流库", async () => {
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench: vi.fn(), onComfyWorkbench: () => () => undefined });
    api.getWorkflowLibrary.mockResolvedValue({ workflows: [], editor: null });
    const noEditor = mount();
    await waitFor(() => expect(api.getWorkflowLibrary).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "pluginConnOpenWorkbench" })).toBeNull();
    noEditor.unmount();
    vi.unstubAllGlobals();
    mount();
    expect(screen.queryByRole("button", { name: "pluginConnOpenWorkbench" })).toBeNull();
    expect(api.getWorkflowLibrary, "网页版不去问").toHaveBeenCalledTimes(1);
  });

  it("连接被拦住(blocked_reason):摆着但点不动,也不去开工作台", async () => {
    const openComfyWorkbench = vi.fn();
    vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
    mount({ ...instance, blocked_reason: "连不上这台 ComfyUI" } as PluginInstance);
    const button = (await screen.findByRole("button", { name: "pluginConnOpenWorkbench" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(openComfyWorkbench).not.toHaveBeenCalled();
  });
});
