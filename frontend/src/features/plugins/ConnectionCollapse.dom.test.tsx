/** @vitest-environment jsdom */

/**
 * 插件页的连接能收起(用户原话:「插件页面我希望每一个连接可以收起 这样方便查看」)。所有插件通用:
 *
 * - 收起时一行看清:名字、关键地址(清单的 `summary_field`)、状态(可用 / 已停用 / 要处理的原因)、开了几个工具、
 *   常用动作(刷新、模型库、工作流库、启用开关、删除);
 * - 只有一个连接默认展开;多个默认收起,刚新建的那个展开;收起状态按连接记在本机,读写存储出错也不影响;
 * - 「全部收起 / 全部展开」在插件头部,连接多于一个时才有;
 * - 标题行是按钮(aria-expanded);
 * - 要处理的(停用了要重新授权、缺配置)收起时也标出来,展开后定位到出问题的那一项。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  listPluginCredentials: vi.fn().mockResolvedValue([]),
  savePluginCredentials: vi.fn(),
  listPluginInvocations: vi.fn().mockResolvedValue([]),
  listPluginPermissions: vi.fn().mockResolvedValue([]),
  listPluginMarket: vi.fn().mockResolvedValue({ plugins: [] }),
  fetchWorkflowFieldOptions: vi.fn().mockResolvedValue([]),
  setPluginPermissions: vi.fn().mockResolvedValue([]),
  updatePluginInstance: vi.fn().mockResolvedValue({}),
  createPluginInstance: vi.fn(),
  getModelLibrary: vi.fn().mockResolvedValue({ folders: [], models: [], missing: [], download: { route: "none", note: "" }, downloads: [] }),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));

import { getModelLibrary, type PluginInstance, type PluginPackage } from "@/api/client";
import { ConnectionCard, PackageDetail } from "./PluginsView";
import { CONNECTIONS_OPEN_KEY, readOpenConnections } from "./connectionOpen";

const pkg = {
  id: "dev.mosael.comfyui",
  name: "ComfyUI",
  version: "1.9.0",
  kind: "process",
  multiple: true,
  permissions: ["network:comfyui", "network:huggingface"],
  provides: ["generation", "tools", "model_library", "workflow_library"],
  summary_field: "server_url",
  config_fields: [{ key: "server_url", label: "服务器地址", type: "string", required: true, secret: false, options: [], help: "" }],
  credential_fields: [],
  oauth: null,
  bundled: true,
  instances: [],
} as unknown as PluginPackage;

function connection(overrides: Partial<PluginInstance>): PluginInstance {
  return {
    id: "c1",
    package_id: pkg.id,
    name: "本机",
    enabled: true,
    config: { server_url: "http://127.0.0.1:8188" },
    blocked_reason: "",
    pending_permissions: [],
    permissions_added: false,
    authorization: "",
    tools: [
      { name: "list_models", label: "列出模型文件", description: "列出模型文件", exposed: true, provides: [], used_by: [], form: {} },
      { name: "interrupt", label: "中断任务", description: "中断任务", exposed: false, provides: [], used_by: [], form: {} },
    ],
    capability_status: { generation: { models: 13, refreshed_at: "2026-10-04T12:00:00Z", error: "" } },
    ...overrides,
  } as unknown as PluginInstance;
}

/** 点标题行展开的那种:展开状态在外面(和插件页一样),点的是卡片自己的标题按钮。 */
function Toggled({ instance }: { instance: PluginInstance }) {
  const [open, setOpen] = React.useState(false);
  return <ConnectionCard pkg={pkg} instance={instance} workspaceId="w1" open={open} onOpenChange={setOpen} />;
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("收起的连接", () => {
  it("一行看清:名字、关键地址、状态、开了几个工具、常用动作;正文不渲染", () => {
    const onOpenChange = vi.fn();
    wrap(<ConnectionCard pkg={pkg} instance={connection({})} workspaceId="w1" open={false} onOpenChange={onOpenChange} />);
    const toggle = screen.getByRole("button", { name: /本机/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.textContent).toContain("http://127.0.0.1:8188");
    expect(toggle.textContent).toContain("pluginConnStateOk");
    expect(toggle.textContent).toContain("pluginExposedCount");
    expect(screen.getByRole("button", { name: "pluginRefreshModels" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "modelLibraryOpen" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "workflowLibraryOpen" })).toBeTruthy();
    expect(screen.getByRole("switch")).toBeTruthy();
    expect(screen.queryByText("pluginConnectionName"), "收起时配置项不摆出来").toBeNull();
    fireEvent.click(toggle);
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it("名字里已经写着地址就不再重复", () => {
    wrap(<ConnectionCard pkg={pkg} instance={connection({ name: "ComfyUI · http://127.0.0.1:8188" })} workspaceId="w1"
                         open={false} onOpenChange={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: /ComfyUI/ });
    expect(toggle.textContent?.split("http://127.0.0.1:8188").length).toBe(2);
  });

  it("插件更新后要重新授权:收起时也标出来,展开后定位到授权那一条", async () => {
    const instance = connection({
      blocked_reason: "插件更新后多要了 1 项权限:network:huggingface。……",
      pending_permissions: ["network:huggingface"],
      permissions_added: true,
    });
    wrap(<Toggled instance={instance} />);
    const toggle = screen.getByRole("button", { name: /本机/ });
    expect(toggle.textContent).toContain("pluginConnStateReauth");
    expect(toggle.textContent).toContain("插件更新后多要了 1 项权限");
    fireEvent.click(toggle);
    const notice = await screen.findByRole("alert");
    await waitFor(() => expect(notice.contains(document.activeElement)).toBe(true));
    expect(notice.closest("[data-connection-section='permissions']")).toBeTruthy();
  });

  it("缺必填配置:收起时说要处理,展开后定位到那一项", async () => {
    const instance = connection({ config: { server_url: "" }, blocked_reason: "缺少配置: 服务器地址" });
    wrap(<Toggled instance={instance} />);
    expect(screen.getByRole("button", { name: /本机/ }).textContent).toContain("pluginConnStateAction");
    fireEvent.click(screen.getByRole("button", { name: /本机/ }));
    const row = document.querySelector("[data-connection-section='config:server_url']") as HTMLElement;
    await waitFor(() => expect(row.contains(document.activeElement)).toBe(true));
  });

  it("模型库读不出来时点「去检查连接设置」:关掉模型库、展开这个连接、定位到服务器地址", async () => {
    vi.mocked(getModelLibrary).mockRejectedValueOnce(new Error("连不上这台 ComfyUI,确认它在运行、地址填对"));
    wrap(<Toggled instance={connection({})} />);
    const toggle = screen.getByRole("button", { name: /本机/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
    fireEvent.click(await screen.findByRole("button", { name: "modelLibraryCheckSettings" }));
    await waitFor(() => expect(screen.queryByText("modelLibraryErrorTitle")).toBeNull());
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const row = document.querySelector("[data-connection-section='config:server_url']") as HTMLElement;
    await waitFor(() => expect(document.activeElement).toBe(row.querySelector("input")));
  });

  it("出错的原文(errno、地址)不进标题行:那一行只说第一句人话,原文悬停看", async () => {
    const instance = connection({
      capability_status: { generation: { models: null, refreshed_at: null, error: "连不上这台 ComfyUI,确认它在运行、地址填对\nhttp://127.0.0.1:8188:[Errno 61] Connection refused" } },
    });
    wrap(<ConnectionCard pkg={pkg} instance={instance} workspaceId="w1" open={false} onOpenChange={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: /本机/ });
    expect(toggle.textContent).toContain("连不上这台 ComfyUI,确认它在运行、地址填对");
    expect(toggle.textContent).not.toContain("Errno");
  });

  it("停用的连接:说已停用,不当成出错", () => {
    wrap(<ConnectionCard pkg={pkg} instance={connection({ enabled: false, blocked_reason: "未启用" })} workspaceId="w1"
                         open={false} onOpenChange={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: /本机/ });
    expect(toggle.textContent).toContain("pluginConnStateOff");
    expect(toggle.textContent).not.toContain("pluginConnStateAction");
  });
});

describe("插件头部:默认状态、全部收起 / 展开、记在本机", () => {
  const two = { ...pkg, instances: [connection({ id: "a", name: "甲" }), connection({ id: "b", name: "乙" })] } as unknown as PluginPackage;

  it("只有一个连接默认展开;多个默认收起,头部有「全部展开 / 全部收起」", () => {
    const { unmount } = wrap(<PackageDetail pkg={{ ...pkg, instances: [connection({})] } as unknown as PluginPackage} workspaceId="w1" />);
    expect(screen.getByRole("button", { name: /本机/ }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.queryByRole("button", { name: /pluginExpandAll|pluginCollapseAll/ })).toBeNull();
    unmount();

    wrap(<PackageDetail pkg={two} workspaceId="w1" />);
    expect(screen.getByRole("button", { name: /甲/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("button", { name: /乙/ }).getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "pluginExpandAll" }));
    expect(screen.getByRole("button", { name: /甲/ }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: /乙/ }).getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "pluginCollapseAll" }));
    expect(screen.getByRole("button", { name: /甲/ }).getAttribute("aria-expanded")).toBe("false");
  });

  it("「全部展开」不抢焦点:定位到出问题那一项只在点开那一个连接时做", async () => {
    const broken = connection({ id: "b", name: "乙", config: { server_url: "" }, blocked_reason: "缺少配置: 服务器地址" });
    wrap(<PackageDetail pkg={{ ...two, instances: [connection({ id: "a", name: "甲" }), broken] } as unknown as PluginPackage}
                        workspaceId="w1" />);
    const expandAll = screen.getByRole("button", { name: "pluginExpandAll" });
    expandAll.focus();
    fireEvent.click(expandAll);
    await new Promise((resolve) => window.setTimeout(resolve, 50));
    expect(document.querySelector("[data-connection-section='config:server_url']")).toBeTruthy();
    expect(document.activeElement?.textContent).toContain("pluginCollapseAll");
  });

  it("展开 / 收起按连接记在本机,下次进来照旧", () => {
    const { unmount } = wrap(<PackageDetail pkg={two} workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button", { name: /乙/ }));
    expect(readOpenConnections()).toEqual({ b: true });
    unmount();
    wrap(<PackageDetail pkg={two} workspaceId="w1" />);
    expect(screen.getByRole("button", { name: /甲/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("button", { name: /乙/ }).getAttribute("aria-expanded")).toBe("true");
  });

  it("本机存储读写出错(隐私模式、被禁用):照默认摆,不崩", () => {
    window.localStorage.setItem(CONNECTIONS_OPEN_KEY, "{not json");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    wrap(<PackageDetail pkg={two} workspaceId="w1" />);
    expect(readOpenConnections()).toEqual({});
    fireEvent.click(screen.getByRole("button", { name: /甲/ }));
    expect(screen.getByRole("button", { name: /甲/ }).getAttribute("aria-expanded")).toBe("true");
    expect(within(document.body).getAllByRole("button", { name: /乙/ })[0].getAttribute("aria-expanded")).toBe("false");
  });
});
