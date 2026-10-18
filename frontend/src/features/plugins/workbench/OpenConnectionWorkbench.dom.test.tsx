/** @vitest-environment jsdom */

/**
 * 插件页连接工具栏的「打开工作台 / 在 ComfyUI 里打开」(ADR 0038)。
 *
 * 维护者问:那台**远端** ComfyUI(「连一台服务器」、可用、开了 100+ 个工具)那一排**没有**这颗按钮,而本机
 * `http://127.0.0.1:8189` 那份**有**。原因不是"只给本机摆"——是这颗按钮此前**要等整份工作流库读回来**才知道
 * 打开哪个地址(`editor.url`);那台远端的工作流库目录超过插件一问一答的上限,读不回来 → `editor` 没有 →
 * 按钮**悄没声地不摆了**(本机 3 张,读得回来,所以有)。这里钉住:
 *
 * - 工作流库读不回来时,照样摆:用**这个连接自己写的地址**(清单的 `summary_field`,宿主/用户写进去的那个,不拼路径);
 * - 目录读得回来、且插件报的是 ComfyUI 编辑器:仍用插件报的 `editor.url`(权威,和以前一样);
 * - 桌面壳(有 `openComfyWorkbench` 桥)进内嵌工作台;网页版开新标签页 —— 和 `workflowEditor` 那条「只开新标签页、
 *   留一句提示」同一条路;
 * - 一个地址都拿不到(没写地址、目录也读不回来):**摆着但点不动**,悬停说清为什么 —— 不能让人以为功能丢了;
 * - 插件报的编辑器不是 ComfyUI:不摆(那不是这个入口的事);
 * - 这个包根本没有「编辑界面」(没有认领 `workflow_library`):不摆。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getWorkflowLibrary: vi.fn(), getLocalService: vi.fn(), ensureLocalService: vi.fn() }));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => {
  //: 说明那两条留着占位符(真表里是 `{name}`、`{url}`):这里要看的是「悬停说得出哪台、哪个地址」
  const table: Record<string, string> = {
    pluginConnOpenComfyHint: "{name}:{url}",
    pluginConnOpenWorkbenchHint: "{name}:{url}",
  };
  return { useI18n: () => (key: string) => table[key] ?? key };
});

import type { PluginInstance, PluginPackage } from "@/api/client";
import { OpenConnectionWorkbench } from "./OpenConnectionWorkbench";
import { resetWorkbench } from "./workbenchSession";

/** 那台远端的地址(维护者截图里的那一台):ComfyUI 的网页和 API 在同一个源上。 */
const REMOTE = "https://u73126-97au-de9a57a8.weste.seetacloud.com:8443";

const pkg = {
  id: "dev.mosael.comfyui",
  name: "ComfyUI",
  provides: ["generation", "tools", "model_library", "workflow_library"],
  summary_field: "server_url",
} as unknown as PluginPackage;

const instance = {
  id: "i1",
  name: "ComfyUI · 远端",
  enabled: true,
  config: { server_url: REMOTE },
  tools: [],
} as unknown as PluginInstance;

const editor = { kind: "comfyui", url: REMOTE };

function mount(target: PluginInstance = instance, packageOf: PluginPackage = pkg) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OpenConnectionWorkbench pkg={packageOf} instance={target} workspaceId="w1" />
    </QueryClientProvider>,
  );
}

/** 桌面壳:有工作台那座桥。 */
function desktop() {
  const openComfyWorkbench = vi.fn().mockResolvedValue({ ok: true, outcome: "opened" });
  vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
  return openComfyWorkbench;
}

/** 悬停说明全文(和别的用例一样:指针移上去,等 tooltip)。 */
async function hintOf(button: HTMLElement): Promise<string> {
  fireEvent.pointerEnter(button);
  fireEvent.pointerMove(button);
  return (await screen.findByRole("tooltip", {}, { timeout: 2000 })).textContent ?? "";
}

beforeEach(() => {
  api.getLocalService.mockReset().mockResolvedValue({ state: "running" });
  api.ensureLocalService.mockReset();
  api.getWorkflowLibrary.mockReset().mockResolvedValue({ workflows: [], editor });
});
afterEach(() => {
  resetWorkbench();
  vi.unstubAllGlobals();
});

describe("连接工具栏的「打开工作台 / 在 ComfyUI 里打开」", () => {
  it("桌面壳 + 插件报了 ComfyUI 编辑器:摆;点了跳到这台的内嵌工作台(地址照插件报的编辑器)", async () => {
    const openComfyWorkbench = desktop();
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "pluginConnOpenWorkbench" }));
    await waitFor(() =>
      expect(openComfyWorkbench).toHaveBeenCalledWith({
        connectionId: "i1", url: REMOTE, name: "ComfyUI · 远端",
      }),
    );
    expect(api.getWorkflowLibrary).toHaveBeenCalledWith("i1", "w1");
  });

  it("工作流库读不回来(那台远端的目录太大):桌面壳照样摆,点它用**这个连接写的地址**开工作台", async () => {
    // 那台远端的工作流库整份超过插件一问一答的上限:整份不收,`editor` 也就拿不到。
    api.getWorkflowLibrary.mockRejectedValue(new Error("插件输出超过大小限制 (1MB)"));
    const openComfyWorkbench = desktop();
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "pluginConnOpenWorkbench" }));
    await waitFor(() =>
      expect(openComfyWorkbench, "不是本机默认地址,是这个连接写的那个").toHaveBeenCalledWith({
        connectionId: "i1", url: REMOTE, name: "ComfyUI · 远端",
      }),
    );
  });

  it("网页版:摆「在 ComfyUI 里打开」,新标签页开这个连接的地址;不去问工作流库", async () => {
    const opened = vi.fn(() => null);
    vi.stubGlobal("open", opened);
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "pluginConnOpenComfy" }));
    expect(opened).toHaveBeenCalledWith(REMOTE, "_blank", "noopener,noreferrer");
    expect(api.getWorkflowLibrary, "网页版不为了这颗按钮去拉整份工作流库").not.toHaveBeenCalled();
  });

  it("网页版 + 工作流库读不回来:照样摆,还是用这个连接写的地址", async () => {
    api.getWorkflowLibrary.mockRejectedValue(new Error("插件输出超过大小限制 (1MB)"));
    const opened = vi.fn(() => null);
    vi.stubGlobal("open", opened);
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "pluginConnOpenComfy" }));
    expect(opened).toHaveBeenCalledWith(REMOTE, "_blank", "noopener,noreferrer");
  });

  it("摆着的按钮说得清开的是哪台、哪个地址", async () => {
    vi.stubGlobal("open", vi.fn(() => null));
    mount();
    const button = await screen.findByRole("button", { name: "pluginConnOpenComfy" });
    const hint = await hintOf(button);
    expect(hint).toContain(REMOTE);
    expect(hint).toContain("ComfyUI · 远端");
  });

  it("目录读得回来、插件报了编辑器:仍用插件报的地址(权威),不是连接里那个", async () => {
    const openComfyWorkbench = desktop();
    const other = { ...instance, config: { server_url: "http://127.0.0.1:9999" } } as PluginInstance;
    api.getWorkflowLibrary.mockResolvedValue({ workflows: [], editor: { kind: "comfyui", url: REMOTE } });
    mount(other);
    const button = await screen.findByRole("button", { name: "pluginConnOpenWorkbench" });
    //: 目录回来之前先按连接里那个地址摆(不让按钮闪掉);回来之后换成插件报的那个 —— 悬停看得到
    fireEvent.pointerEnter(button);
    fireEvent.pointerMove(button);
    await waitFor(() =>
      expect(screen.getByRole("tooltip").textContent, "插件报的编辑器地址优先").toContain(REMOTE),
    );
    fireEvent.click(button);
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledWith(expect.objectContaining({ url: REMOTE })));
  });

  it("连接被拦住(blocked_reason):摆着但点不动,也不去开", async () => {
    const openComfyWorkbench = desktop();
    mount({ ...instance, blocked_reason: "连不上这台 ComfyUI" } as PluginInstance);
    const button = (await screen.findByRole("button", { name: "pluginConnOpenWorkbench" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(openComfyWorkbench).not.toHaveBeenCalled();
  });

  it("一个地址都拿不到(没写地址、目录也读不回来):摆着但点不动,悬停说清为什么", async () => {
    api.getWorkflowLibrary.mockRejectedValue(new Error("插件输出超过大小限制 (1MB)"));
    const openComfyWorkbench = desktop();
    mount({ ...instance, config: {} } as PluginInstance);
    const button = (await screen.findByRole("button", { name: "pluginConnOpenWorkbench" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(openComfyWorkbench).not.toHaveBeenCalled();
    expect(await hintOf(button), "不能让人以为功能丢了").toContain("workflowMenuNoEditor");
  });

  it("插件报的编辑器不是 ComfyUI:不摆(那不是这个入口的事)", async () => {
    api.getWorkflowLibrary.mockResolvedValue({ workflows: [], editor: { kind: "other", url: REMOTE } });
    desktop();
    mount();
    //: 目录回来之前按连接里那个地址先摆着;回来一看不是 ComfyUI 编辑器,收掉
    await waitFor(() => expect(screen.queryByRole("button", { name: "pluginConnOpenWorkbench" })).toBeNull());
  });

  it("这个包没有工作流库(没有编辑界面):不摆", () => {
    const plain = { ...pkg, provides: ["generation", "tools"] } as PluginPackage;
    mount(instance, plain);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
