/** @vitest-environment jsdom */

/**
 * 背后的本机服务用不了的时候,连接页、生成模型那一行、模型库 / 工作流库读不出来、打开工作台没成,**都按它的状态说**
 * (localServiceStatus 一处定说法):停着(不算错,给「启动」)、正在起(不算错)、起不来(带最后一行日志,给「日志」)、
 * 还没装好 / 要重建(给「去本机服务那里」)、进程在却不应答(给「日志」)。插件那句「确认它在运行、地址填对」只适合
 * 「连一台服务器」—— 那一种照旧。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getLocalService: vi.fn(),
  getLocalServiceLogs: vi.fn(),
  startLocalService: vi.fn(),
  listPluginInstanceModels: vi.fn(),
}));
vi.mock("@/api/client", () => api);
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));

import type { LocalService, PluginInstance, PluginPackage } from "@/api/client";
import { ConnectionFailureActions, explainOpenFailure, serviceIssue } from "./localServiceStatus";
import { GenerationModelsRow } from "./ProvidedModels";
import { connectionIssue } from "./PluginsView";

const UNREACHABLE = "连不上这台 ComfyUI,确认它在运行、地址填对\nhttp://127.0.0.1:8189:[Errno 61]";
type Kind = NonNullable<LocalService["issue"]>["kind"];

function service(kind: Kind | null, overrides: Partial<LocalService> = {}): LocalService {
  return {
    service: "comfyui", title: "ComfyUI", mode: "directory", directory: "/x", python: "", port: 8189, url: "http://127.0.0.1:8189",
    listen_lan: false, keep_running: false, extra_args: [], state: kind === "starting" ? "starting" : kind === "failed" ? "failed" : "stopped",
    pid: null, started_at: null, ready_seconds: null, adopted: false, restarts: 0, error: "", failure_lines: [], can_manage: true,
    installed: true, python_minor: "", base_python_minor: "", needs_rebuild: false, install: null,
    issue: kind ? { kind, text: `本机的 ComfyUI:${kind}` } : null,
    ...overrides,
  };
}

const PKG = { id: "dev.mosael.comfyui", name: "ComfyUI", config_fields: [], services: [{ key: "comfyui", title: "ComfyUI" }] } as unknown as PluginPackage;

function instance(error = ""): PluginInstance {
  return {
    id: "c1", name: "本机", enabled: true, config: {}, blocked_reason: "", pending_permissions: [], authorization: null,
    capability_status: { generation: { models: 3, refreshed_at: "2026-10-06T00:00:00+00:00", error } },
  } as unknown as PluginInstance;
}

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.getLocalServiceLogs.mockResolvedValue({ lines: ["Traceback …", "ModuleNotFoundError: alembic"], path: "/logs/service-c1.log" });
});

describe("连接卡片标题行", () => {
  it("连一台服务器:照插件说的(检查地址那句就是对的)", () => {
    const issue = connectionIssue(PKG, instance(UNREACHABLE), null);
    expect(issue.label).toBe("pluginConnStateError");
    expect(issue.detail).toBe(UNREACHABLE);
  });

  it.each([
    ["stopped", "muted", "localServiceStateStopped"],
    ["starting", "primary", "localServiceStateStarting"],
    ["failed", "warning", "localServiceStateFailed"],
    ["unresponsive", "warning", "localServiceIssueUnresponsive"],
    ["not_installed", "warning", "localServiceIssueNotInstalled"],
    ["rebuild", "warning", "localServiceRebuildTitle"],
  ] as const)("目录没刷出来、背后的本机服务 %s:按它的状态说,不说检查地址", (kind, tone, label) => {
    const issue = connectionIssue(PKG, instance(UNREACHABLE), service(kind));
    expect([issue.tone, issue.label, issue.target]).toEqual([tone, label, "local-service"]);
    expect(issue.detail).toBe(`本机的 ComfyUI:${kind}`);
    expect(issue.detail).not.toContain("地址");
  });

  it("没出过错:停着、正在起是常态,照「可用」说;起不来、不应答、没装好、要重建不等出错也说", () => {
    expect(connectionIssue(PKG, instance(), service("stopped")).label).toBe("pluginConnStateOk");
    expect(connectionIssue(PKG, instance(), service("starting")).label).toBe("pluginConnStateOk");
    expect(connectionIssue(PKG, instance(), service("failed")).label).toBe("localServiceStateFailed");
    expect(connectionIssue(PKG, instance(), service("unresponsive")).label).toBe("localServiceIssueUnresponsive");
    expect(connectionIssue(PKG, instance(), service(null)).label).toBe("pluginConnStateOk");
    expect(serviceIssue(service("stopped"), false)).toBeNull();
  });
});

describe("生成模型那一行", () => {
  function row(local: LocalService | null, error = UNREACHABLE) {
    const target = instance(error);
    return mount(<GenerationModelsRow instance={target} status={target.capability_status?.generation} service={local}
                                      refreshing={false} onRefresh={vi.fn()} />);
  }

  it("连一台服务器:没刷出来照插件说的", () => {
    row(null);
    expect(screen.getByText("pluginGenerationError")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /localServiceStart/ })).toBeNull();
  });

  it("停着:说没在运行、不当错误摆,给「启动」(管理员),点了就起", async () => {
    api.startLocalService.mockResolvedValue(service(null, { state: "running" }));
    row(service("stopped"));
    expect(screen.getByRole("status").textContent).toBe("本机的 ComfyUI:stopped");
    expect(screen.queryByText("pluginGenerationError"), "不说插件那句「检查地址」").toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /localServiceStart/ }));
    await waitFor(() => expect(api.startLocalService).toHaveBeenCalledWith("c1"));
  });

  it("停着、不是管理员:没有「启动」(用到时会自动起)", () => {
    row(service("stopped", { can_manage: false }));
    expect(screen.queryByRole("button", { name: /localServiceStart/ })).toBeNull();
  });

  it("正在起:不当错误摆", () => {
    row(service("starting"));
    expect(screen.getByRole("status").textContent).toBe("本机的 ComfyUI:starting");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("起不来:原因、最后一行日志,「日志」打开日志窗口", async () => {
    row(service("failed", { failure_lines: ["Traceback …", "ModuleNotFoundError: alembic"] }));
    expect(screen.getByRole("alert").textContent).toBe("本机的 ComfyUI:failed");
    expect(screen.getByText("ModuleNotFoundError: alembic")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /localServiceLogs/ }));
    expect(await screen.findByText(/Traceback …/)).toBeTruthy();
    expect(api.getLocalServiceLogs).toHaveBeenCalledWith("c1", 2000, "service");
  });

  it("进程在却不应答:给「日志」,不说检查地址", () => {
    row(service("unresponsive", { state: "running" }));
    expect(screen.getByRole("alert").textContent).toBe("本机的 ComfyUI:unresponsive");
    expect(screen.getByRole("button", { name: /localServiceLogs/ })).toBeTruthy();
  });

  it.each(["not_installed", "rebuild"] as const)("%s:给「去本机服务那里」", (kind) => {
    row(service(kind, { mode: "managed" }));
    expect(screen.getByRole("button", { name: /localServiceIssueGoInstall/ })).toBeTruthy();
  });
});

describe("模型库、工作流库读不出来时的那几下", () => {
  it("连一台服务器:照旧「检查连接设置」", async () => {
    api.getLocalService.mockResolvedValue(null);
    const check = vi.fn();
    mount(<ConnectionFailureActions instanceId="c1" onCheckSettings={check} />);
    fireEvent.click(await screen.findByRole("button", { name: /modelLibraryCheckSettings/ }));
    expect(check).toHaveBeenCalled();
  });

  it("本机服务停着:给「启动」,不给「检查连接设置」", async () => {
    api.getLocalService.mockResolvedValue(service("stopped"));
    mount(<ConnectionFailureActions instanceId="c1" onCheckSettings={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /localServiceStart/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /modelLibraryCheckSettings/ })).toBeNull();
  });

  it("起不来:给「日志」;还没装好:「去本机服务那里」走的是检查设置那条路(定位到本机服务那一块)", async () => {
    api.getLocalService.mockResolvedValue(service("failed"));
    const view = mount(<ConnectionFailureActions instanceId="c1" />);
    expect(await screen.findByRole("button", { name: /localServiceLogs/ })).toBeTruthy();
    view.unmount();
    api.getLocalService.mockResolvedValue(service("not_installed", { mode: "managed" }));
    const check = vi.fn();
    mount(<ConnectionFailureActions instanceId="c1" onCheckSettings={check} />);
    fireEvent.click(await screen.findByRole("button", { name: /localServiceIssueGoInstall/ }));
    expect(check).toHaveBeenCalled();
  });
});

describe("打开工作台、内嵌编辑器没成", () => {
  it("背后的本机服务用不了:说它那一句;好好的、没有本机服务、问不到:照原来那句", async () => {
    api.getLocalService.mockResolvedValueOnce(service("unresponsive", { state: "running" }));
    expect(await explainOpenFailure("c1", "页面没就绪")).toBe("本机的 ComfyUI:unresponsive");
    api.getLocalService.mockResolvedValueOnce(service(null, { state: "running" }));
    expect(await explainOpenFailure("c1", "页面没就绪")).toBe("页面没就绪");
    api.getLocalService.mockResolvedValueOnce(null);
    expect(await explainOpenFailure("c1", "页面没就绪")).toBe("页面没就绪");
    api.getLocalService.mockRejectedValueOnce(new Error("offline"));
    expect(await explainOpenFailure("c1", "页面没就绪")).toBe("页面没就绪");
  });
});
