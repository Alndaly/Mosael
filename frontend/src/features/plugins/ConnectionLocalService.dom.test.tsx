/** @vitest-environment jsdom */

/**
 * 连接页上的「本机服务」(ADR 0041),和插件页上的「本机发现」。钉的是这几条规矩:
 *
 * - 「在哪跑」三种:连一台服务器 / 用我自己装的 / 让 Mosael 装(看得见、点不了,写明下一步提供);
 * - 选目录之后要**先确认**「会在这台机器上运行这个目录里的代码」,确认了才认目录;认出来、能起才存,认不出就把问题摆出来、不存;
 * - 存好之后:状态、启动 / 停止 / 重启、日志;起不来时摆原因和最后几行日志;打开局域网要再确认一次;
 * - 不是部署管理员:状态看得到,控件是灰的;
 * - 本机发现:已经连着的、点过「不用了」的不再提;「连上」建的是「连一台服务器」那一种。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getLocalService: vi.fn(),
  putLocalService: vi.fn(),
  removeLocalService: vi.fn(),
  detectLocalService: vi.fn(),
  startLocalService: vi.fn(),
  stopLocalService: vi.fn(),
  restartLocalService: vi.fn(),
  getLocalServiceLogs: vi.fn(),
  addLocalServiceNodes: vi.fn(),
  discoverLocalServices: vi.fn(),
  createPluginInstance: vi.fn(),
}));
vi.mock("@/api/client", () => api);
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import type { LocalService, PluginInstance, PluginPackage } from "@/api/client";
import { ConnectionLocalService, LocalServiceDiscovery, joinArgs } from "./ConnectionLocalService";

const PKG = {
  id: "dev.mosael.comfyui", name: "ComfyUI", version: "1.14.0", services: [{ key: "comfyui", title: "ComfyUI" }],
  instances: [],
} as unknown as PluginPackage;
const INSTANCE = { id: "i1", name: "ComfyUI · 本机", config: { server_url: "http://127.0.0.1:8188" } } as unknown as PluginInstance;

function service(overrides: Partial<LocalService> = {}): LocalService {
  return {
    service: "comfyui", title: "ComfyUI", mode: "directory", directory: "/Users/me/ComfyUI", python: "", port: 8189,
    url: "http://127.0.0.1:8189", listen_lan: false, keep_running: false, extra_args: [], state: "stopped", pid: null,
    started_at: null, ready_seconds: null, adopted: false, restarts: 0, error: "", failure_lines: [], can_manage: true,
    ...overrides,
  };
}

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.getLocalService.mockResolvedValue(null);
  api.getLocalServiceLogs.mockResolvedValue({ lines: ["Starting server", "To see the GUI go to: http://127.0.0.1:8189"], path: "/data/logs/service-i1.log" });
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("在哪跑", () => {
  it("没用本机服务:连一台服务器;让 Mosael 装看得见、点不了", async () => {
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} />);
    const group = await screen.findByRole("radiogroup", { name: "localServiceWhere" });
    expect(within(group).getByRole("radio", { name: "localServiceModeServer" }).getAttribute("aria-checked")).toBe("true");
    const managed = within(group).getByText("localServiceModeManaged");
    expect(managed.getAttribute("aria-disabled")).toBe("true");
    expect(screen.queryByLabelText("localServiceDirectory")).toBeNull();
  });

  it("选目录:先确认会运行这个目录里的代码,认出来能起才存", async () => {
    api.detectLocalService.mockResolvedValue({
      ok: true, facts: [{ label: "ComfyUI 版本", value: "0.39.0" }], problems: [], add_nodes: null,
    });
    api.putLocalService.mockResolvedValue(service());
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} />);
    fireEvent.click(await screen.findByRole("radio", { name: "localServiceModeDirectory" }));
    fireEvent.change(screen.getByLabelText("localServiceDirectory"), { target: { value: " /Users/me/ComfyUI " } });
    fireEvent.click(screen.getByRole("button", { name: "localServiceCheck" }));
    expect(api.detectLocalService, "没确认之前什么都不跑").not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("localServiceConfirmTitle")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "localServiceConfirmRun" }));
    await waitFor(() => expect(api.putLocalService).toHaveBeenCalledWith("i1", {
      mode: "directory", directory: "/Users/me/ComfyUI", python: "", confirm_run_code: true,
    }));
    expect(api.detectLocalService).toHaveBeenCalledWith("i1", "/Users/me/ComfyUI", "");
    expect(await screen.findByText("localServiceStateStopped")).toBeTruthy();
  });

  it("认不出、起不来:把问题摆出来,不存", async () => {
    api.detectLocalService.mockResolvedValue({
      ok: false, facts: [], add_nodes: null,
      problems: [{ level: "error", text: "这个 Python 导入不了 torch" }, { level: "warning", text: "没装 ComfyUI-Manager" }],
    });
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} />);
    fireEvent.click(await screen.findByRole("radio", { name: "localServiceModeDirectory" }));
    fireEvent.change(screen.getByLabelText("localServiceDirectory"), { target: { value: "/x" } });
    fireEvent.click(screen.getByRole("button", { name: "localServiceCheck" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceConfirmRun" }));
    expect(await screen.findByText("这个 Python 导入不了 torch")).toBeTruthy();
    expect(screen.getByText("localServiceNotUsable")).toBeTruthy();
    expect(api.putLocalService).not.toHaveBeenCalled();
  });
});

describe("存好之后", () => {
  it("运行中:状态、端口、停止;日志在弹窗里", async () => {
    api.getLocalService.mockResolvedValue(service({
      state: "running", pid: 4321, ready_seconds: 18.4, started_at: "2026-10-06T06:00:00+00:00", restarts: 1,
    }));
    api.stopLocalService.mockResolvedValue(service());
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} />);
    expect(await screen.findByText("localServiceStateRunning")).toBeTruthy();
    expect(screen.getByText(/localServicePort/)).toBeTruthy();
    expect(screen.getByRole("radio", { name: "localServiceModeDirectory" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /localServiceStop/ }));
    await waitFor(() => expect(api.stopLocalService).toHaveBeenCalledWith("i1"));
    fireEvent.click(screen.getByRole("button", { name: /localServiceLogs/ }));
    expect(await screen.findByText(/To see the GUI go to/)).toBeTruthy();
    expect(api.getLocalServiceLogs).toHaveBeenCalledWith("i1", 2000);
  });

  it("起不来:摆原因和最后几行日志,可以再启动", async () => {
    api.getLocalService.mockResolvedValue(service({
      state: "failed", error: "还没就绪就退出了(退出码 1)", failure_lines: ["ModuleNotFoundError: No module named 'torch'"],
    }));
    api.startLocalService.mockResolvedValue(service({ state: "starting" }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("还没就绪就退出了(退出码 1)")).toBeTruthy();
    expect(screen.getByText(/No module named 'torch'/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /localServiceStart/ }));
    await waitFor(() => expect(api.startLocalService).toHaveBeenCalledWith("i1"));
  });

  it("打开局域网要再确认一次;关掉不用", async () => {
    api.getLocalService.mockResolvedValue(service());
    api.putLocalService.mockResolvedValue(service({ listen_lan: true }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} />);
    fireEvent.click(await screen.findByRole("switch", { name: "localServiceLan" }));
    expect(api.putLocalService).not.toHaveBeenCalled();
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceLanConfirmRun" }));
    await waitFor(() => expect(api.putLocalService).toHaveBeenCalledWith("i1", { listen_lan: true }));
  });

  it("改回连一台服务器:先确认,停掉并删掉本机服务", async () => {
    api.getLocalService.mockResolvedValue(service());
    api.removeLocalService.mockResolvedValue(undefined);
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} />);
    fireEvent.click(await screen.findByRole("radio", { name: "localServiceModeServer" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceBackToServerRun" }));
    await waitFor(() => expect(api.removeLocalService).toHaveBeenCalledWith("i1"));
  });

  it("补装:插件说缺的那一样,确认之后才装", async () => {
    api.getLocalService.mockResolvedValue(service());
    api.detectLocalService.mockResolvedValue({
      ok: true, facts: [], problems: [],
      add_nodes: { title: "补装 pysssss", description: "从 GitHub 下载固定版本,解到 /Users/me/ComfyUI/custom_nodes/ComfyUI-Custom-Scripts" },
    });
    api.addLocalServiceNodes.mockResolvedValue({ installed: ["ComfyUI-Custom-Scripts"], path: "/x", message: "装好了" });
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} />);
    fireEvent.click(await screen.findByRole("button", { name: "localServiceRecheck" }));
    fireEvent.click(await screen.findByRole("button", { name: "localServiceAddNodesRun" }));
    expect(api.addLocalServiceNodes).not.toHaveBeenCalled();
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceAddNodesRun" }));
    await waitFor(() => expect(api.addLocalServiceNodes).toHaveBeenCalledWith("i1"));
  });

  it("不是部署管理员:状态看得到,启动、换目录、开关都是灰的", async () => {
    api.getLocalService.mockResolvedValue(service({ can_manage: false }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} />);
    expect(await screen.findByText("localServiceStateStopped")).toBeTruthy();
    expect((screen.getByRole("button", { name: /localServiceStart/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "localServiceChangeFolder" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("switch", { name: "localServiceKeepRunning" }).hasAttribute("disabled")).toBe(true);
    expect((screen.getByRole("radio", { name: "localServiceModeServer" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("附加参数一项一个 ↔ 一行字:带空格的一项用双引号括起来", () => {
    expect(joinArgs(["--lowvram", "--output-directory=D:\\out put"])).toBe('--lowvram "--output-directory=D:\\out put"');
  });
});

describe("本机发现", () => {
  it("已经连着的、点过不用了的不再提;连上建的是连一台服务器", async () => {
    api.discoverLocalServices.mockResolvedValue({ servers: [
      { url: "http://127.0.0.1:8188", label: "本机的 ComfyUI 0.39.0(端口 8188)" },
      { url: "http://127.0.0.1:8000", label: "本机的 ComfyUI 0.38.0(端口 8000)" },
    ] });
    api.createPluginInstance.mockResolvedValue({ id: "new" });
    const onConnected = vi.fn();
    const pkg = { ...PKG, instances: [{ id: "old", config: { server_url: "http://127.0.0.1:8188/" } }] } as unknown as PluginPackage;
    mount(<LocalServiceDiscovery pkg={pkg} onConnected={onConnected} />);
    expect(await screen.findByText("localServiceDiscovered")).toBeTruthy();
    expect(screen.getAllByRole("status")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "localServiceConnect" }));
    await waitFor(() => expect(api.createPluginInstance).toHaveBeenCalledWith("dev.mosael.comfyui", {
      config: { server_url: "http://127.0.0.1:8000" },
    }));
    await waitFor(() => expect(onConnected).toHaveBeenCalledWith("new"));
  });

  it("点过不用了:记在本机,下次不提", async () => {
    api.discoverLocalServices.mockResolvedValue({ servers: [{ url: "http://127.0.0.1:8000", label: "Desktop" }] });
    const first = mount(<LocalServiceDiscovery pkg={PKG} onConnected={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "localServiceDismiss" }));
    expect(screen.queryByRole("status")).toBeNull();
    first.unmount();
    mount(<LocalServiceDiscovery pkg={PKG} onConnected={vi.fn()} />);
    await waitFor(() => expect(api.discoverLocalServices).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("不是管理员(问到 403):这一条不出现", async () => {
    api.discoverLocalServices.mockRejectedValue(new Error("403"));
    mount(<LocalServiceDiscovery pkg={PKG} onConnected={vi.fn()} />);
    await waitFor(() => expect(api.discoverLocalServices).toHaveBeenCalled());
    expect(screen.queryByRole("status")).toBeNull();
  });
});
