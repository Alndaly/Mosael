/** @vitest-environment jsdom */

/**
 * 连接页上的「本机服务」(ADR 0041),和插件页上的「本机发现」。钉的是这几条规矩:
 *
 * - 「在哪跑」三种:连一台服务器 / 用我自己装的 / 让 Mosael 装;
 * - 选目录之后要**先确认**「会在这台机器上运行这个目录里的代码」,确认了才认目录;认出来、能起才存,认不出就把问题摆出来、不存;
 * - 存好之后:状态、启动 / 停止 / 重启、日志;起不来时摆原因和最后几行日志;打开局域网要再确认一次;
 * - 不是部署管理员:状态看得到,控件是灰的;
 * - 本机发现:已经连着的、点过「不用了」的不再提;「连上」建的是「连一台服务器」那一种。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  getLocalServicePlan: vi.fn(),
  installLocalService: vi.fn(),
  cancelLocalServiceInstall: vi.fn(),
  isCustomServer: vi.fn(),
}));
vi.mock("@/api/client", () => api);
vi.mock("@/features/plugins/ModelLibrary", () => ({
  ModelLibraryDialog: ({ instance }: { instance: { id: string } }) => <div role="dialog" aria-label={`model-library:${instance.id}`} />,
}));
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
    installed: true, python_minor: "", base_python_minor: "", needs_rebuild: false, install: null,
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
  it("没用本机服务:连一台服务器;三种都能选", async () => {
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    const group = await screen.findByRole("radiogroup", { name: "localServiceWhere" });
    expect(within(group).getByRole("radio", { name: "localServiceModeServer" }).getAttribute("aria-checked")).toBe("true");
    const managed = within(group).getByRole("radio", { name: "localServiceModeManaged" });
    expect((managed as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByLabelText("localServiceDirectory")).toBeNull();
    expect(api.getLocalServicePlan, "没选「让 Mosael 装」不去看这台机器").not.toHaveBeenCalled();
  });

  it("选目录:先确认会运行这个目录里的代码,认出来能起才存", async () => {
    api.detectLocalService.mockResolvedValue({
      ok: true, facts: [{ label: "ComfyUI 版本", value: "0.39.0" }], problems: [], add_nodes: null,
    });
    api.putLocalService.mockResolvedValue(service());
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
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
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    fireEvent.click(await screen.findByRole("radio", { name: "localServiceModeDirectory" }));
    fireEvent.change(screen.getByLabelText("localServiceDirectory"), { target: { value: "/x" } });
    fireEvent.click(screen.getByRole("button", { name: "localServiceCheck" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceConfirmRun" }));
    expect(await screen.findByText("这个 Python 导入不了 torch")).toBeTruthy();
    expect(screen.getByText("localServiceNotUsable")).toBeTruthy();
    expect(api.putLocalService).not.toHaveBeenCalled();
  });
});

describe("路径格旁边的「选择…」", () => {
  const desktop = window as unknown as { mosaelDesktop?: { platform: string; pickPath?: ReturnType<typeof vi.fn> } };
  afterEach(() => {
    delete desktop.mosaelDesktop;
  });

  async function chooseDirectoryMode() {
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    fireEvent.click(await screen.findByRole("radio", { name: "localServiceModeDirectory" }));
    await screen.findByLabelText("localServiceDirectory");
  }

  it("只在桌面版、连着本机后端时有:网页版、桌面版连着别处的服务器都只给输入框", async () => {
    await chooseDirectoryMode();
    expect(screen.queryAllByRole("button", { name: "pathFieldChooseLabel" }), "网页版:没有系统对话框").toHaveLength(0);
    cleanup();

    desktop.mosaelDesktop = { platform: "darwin", pickPath: vi.fn() };
    api.isCustomServer.mockReturnValue(true);
    await chooseDirectoryMode();
    expect(screen.queryAllByRole("button", { name: "pathFieldChooseLabel" }), "选出来的路径在那台服务器上不存在").toHaveLength(0);
    cleanup();

    api.isCustomServer.mockReturnValue(false);
    await chooseDirectoryMode();
    expect(screen.getAllByRole("button", { name: "pathFieldChooseLabel" }), "装在哪、解释器各一个").toHaveLength(2);
  });

  it("从格子里现在的值开始;选好的路径填进格子,和敲进去的一样:确认之后才拿去检查", async () => {
    const pickPath = vi.fn()
      .mockResolvedValueOnce("/Users/me/Apps/ComfyUI")
      .mockResolvedValueOnce("/Users/me/Apps/ComfyUI/.venv/bin/python")
      .mockResolvedValueOnce(null);
    desktop.mosaelDesktop = { platform: "darwin", pickPath };
    api.detectLocalService.mockResolvedValue({ ok: false, facts: [], problems: [], add_nodes: null });
    await chooseDirectoryMode();
    fireEvent.change(screen.getByLabelText("localServiceDirectory"), { target: { value: " /Users/me " } });
    const [folder, interpreter] = screen.getAllByRole("button", { name: "pathFieldChooseLabel" });

    fireEvent.click(folder);
    await waitFor(() => expect((screen.getByLabelText("localServiceDirectory") as HTMLInputElement).value).toBe("/Users/me/Apps/ComfyUI"));
    expect(pickPath).toHaveBeenLastCalledWith({ kind: "directory", title: "localServiceDirectory", defaultPath: "/Users/me" });
    fireEvent.click(interpreter);
    await waitFor(() => expect((screen.getByLabelText("localServicePython") as HTMLInputElement).value)
      .toBe("/Users/me/Apps/ComfyUI/.venv/bin/python"));
    expect(pickPath.mock.calls[1][0], "解释器格是空的:由系统决定从哪儿开始").toMatchObject({ kind: "file", defaultPath: undefined });
    fireEvent.click(interpreter);
    await waitFor(() => expect(pickPath).toHaveBeenCalledTimes(3));
    expect((screen.getByLabelText("localServicePython") as HTMLInputElement).value, "取消了:格子不动")
      .toBe("/Users/me/Apps/ComfyUI/.venv/bin/python");

    expect(api.detectLocalService, "选好了也不自己跑:检查会运行那个目录里的代码").not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "localServiceCheck" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceConfirmRun" }));
    await waitFor(() => expect(api.detectLocalService)
      .toHaveBeenCalledWith("i1", "/Users/me/Apps/ComfyUI", "/Users/me/Apps/ComfyUI/.venv/bin/python"));
  });
});

describe("存好之后", () => {
  it("运行中:状态、端口、停止;日志在弹窗里", async () => {
    api.getLocalService.mockResolvedValue(service({
      state: "running", pid: 4321, ready_seconds: 18.4, started_at: "2026-10-06T06:00:00+00:00", restarts: 1,
    }));
    api.stopLocalService.mockResolvedValue(service());
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    expect(await screen.findByText("localServiceStateRunning")).toBeTruthy();
    expect(screen.getByText(/localServicePort/)).toBeTruthy();
    expect(screen.getByRole("radio", { name: "localServiceModeDirectory" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /localServiceStop/ }));
    await waitFor(() => expect(api.stopLocalService).toHaveBeenCalledWith("i1"));
    fireEvent.click(screen.getByRole("button", { name: /localServiceLogs/ }));
    expect(await screen.findByText(/To see the GUI go to/)).toBeTruthy();
    expect(api.getLocalServiceLogs).toHaveBeenCalledWith("i1", 2000, "service");
  });

  it("起不来:摆原因和最后几行日志,可以再启动", async () => {
    api.getLocalService.mockResolvedValue(service({
      state: "failed", error: "还没就绪就退出了(退出码 1)", failure_lines: ["ModuleNotFoundError: No module named 'torch'"],
    }));
    api.startLocalService.mockResolvedValue(service({ state: "starting" }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("还没就绪就退出了(退出码 1)")).toBeTruthy();
    expect(screen.getByText(/No module named 'torch'/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /localServiceStart/ }));
    await waitFor(() => expect(api.startLocalService).toHaveBeenCalledWith("i1"));
  });

  it("打开局域网要再确认一次;关掉不用", async () => {
    api.getLocalService.mockResolvedValue(service());
    api.putLocalService.mockResolvedValue(service({ listen_lan: true }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    fireEvent.click(await screen.findByRole("switch", { name: "localServiceLan" }));
    expect(api.putLocalService).not.toHaveBeenCalled();
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceLanConfirmRun" }));
    await waitFor(() => expect(api.putLocalService).toHaveBeenCalledWith("i1", { listen_lan: true }));
  });

  it("改回连一台服务器:先确认,停掉并删掉本机服务", async () => {
    api.getLocalService.mockResolvedValue(service());
    api.removeLocalService.mockResolvedValue(undefined);
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
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
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    fireEvent.click(await screen.findByRole("button", { name: "localServiceRecheck" }));
    fireEvent.click(await screen.findByRole("button", { name: "localServiceAddNodesRun" }));
    expect(api.addLocalServiceNodes).not.toHaveBeenCalled();
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceAddNodesRun" }));
    await waitFor(() => expect(api.addLocalServiceNodes).toHaveBeenCalledWith("i1"));
  });

  it("不是部署管理员:状态看得到,启动、换目录、开关都是灰的", async () => {
    api.getLocalService.mockResolvedValue(service({ can_manage: false }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
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

const PLAN = {
  ok: true, supported: true, platform: "Apple 芯片 Mac", verdict: "PyPI 上的 PyTorch 直接带 MPS", flavour: "mps",
  torch: "PyTorch 2.14.1(MPS)",
  version: "0.39.0", disk_bytes: 5 * 1024 ** 3, free_bytes: 200 * 1024 ** 3, directory: "/data/local-services/i1",
  steps: [
    { key: "disk", title: "查剩余空间", done: false },
    { key: "download", title: "下载 ComfyUI 0.39.0 源码", done: false },
    { key: "torch", title: "装 PyTorch", done: false },
    { key: "trial", title: "试起一次", done: false },
  ],
  downloads: [{ label: "ComfyUI 0.39.0 源码", url: "https://codeload.github.com/comfyanonymous/ComfyUI/tar.gz/refs/tags/v0.39.0" }],
  route: { kind: "system", proxy: "" },
  problems: [],
} as const;

function managedService(overrides: Partial<LocalService> = {}): LocalService {
  return service({ mode: "managed", directory: "/data/local-services/i1", installed: false, ...overrides });
}

function run(overrides: Partial<NonNullable<LocalService["install"]>> = {}): NonNullable<LocalService["install"]> {
  return {
    state: "installing", step: "torch", started_at: "2026-10-06T06:00:00+00:00", finished_at: null, error: "", item: "",
    done_bytes: null, total_bytes: null, speed: null,
    steps: [
      { key: "disk", title: "查剩余空间", done: true },
      { key: "download", title: "下载源码", done: true },
      { key: "torch", title: "装 PyTorch", done: false },
      { key: "trial", title: "试起一次", done: false },
    ],
    ...overrides,
  };
}

describe("让 Mosael 装", () => {
  it("选它:先看安装计划(这台机器、PyTorch、空间、装在哪、几步、从哪儿下),确认写明在哪台机器上装", async () => {
    api.getLocalServicePlan.mockResolvedValue(PLAN);
    api.installLocalService.mockResolvedValue(managedService({ install: run({ step: "disk", steps: [] }) }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    fireEvent.click(await screen.findByRole("radio", { name: "localServiceModeManaged" }));
    expect(await screen.findByText("PyTorch 2.14.1(MPS)")).toBeTruthy();
    expect(screen.getByText("Apple 芯片 Mac")).toBeTruthy();
    expect(screen.getByText(/PyPI 上的 PyTorch 直接带 MPS/)).toBeTruthy();
    expect(screen.getByText("/data/local-services/i1")).toBeTruthy();
    expect(screen.getByText("localServicePlanDiskValue")).toBeTruthy();
    expect(screen.getByText("试起一次")).toBeTruthy();
    expect(screen.getByText(/codeload\.github\.com/)).toBeTruthy();
    expect(screen.getByText("localServicePlanNoModels"), "不下模型(拍板 7)").toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "localServiceInstallStart" }));
    expect(api.installLocalService, "没确认之前不装").not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("localServiceInstallConfirmTitle")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "localServiceInstallStart" }));
    await waitFor(() => expect(api.installLocalService).toHaveBeenCalledWith("i1", "mps"));
  });

  it.each([
    ["global", "http://***@127.0.0.1:7897", "localServicePlanRouteGlobal"],
    ["own", "socks5://10.0.0.2:1080", "localServicePlanRouteOwn"],
    ["direct", "", "localServicePlanRouteDirect"],
    ["system", "", "localServicePlanRouteSystem"],
  ] as const)("安装计划写明下载怎么走:%s", async (kind, proxy, text) => {
    api.getLocalServicePlan.mockResolvedValue({ ...PLAN, route: { kind, proxy } });
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    fireEvent.click(await screen.findByRole("radio", { name: "localServiceModeManaged" }));
    const line = (await screen.findByText(text)).closest("[data-plan-route]") as HTMLElement;
    expect(line.getAttribute("data-plan-route")).toBe(kind);
    expect(line.querySelector("[data-plan-proxy]")?.textContent ?? "", "走代理就写出是哪个(密码由后端换成 ***)").toBe(proxy);
    expect(screen.getByRole("button", { name: "localServicePlanChangeNetwork" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "localServicePlanChangeGlobalNetwork" })).toBeTruthy();
  });

  it("每个地址旁边写明被下载源里的哪一项改写;绕过列表里的那个标出来直连", async () => {
    api.getLocalServicePlan.mockResolvedValue({
      ...PLAN,
      route: { kind: "global", proxy: "http://127.0.0.1:7897" },
      downloads: [
        { label: "源码", url: "https://gh.example/https://codeload.github.com/x", source: "github", setting: "https://gh.example/", bypass: false },
        { label: "PyTorch", url: "https://mirror.nju.edu.cn/pytorch/whl/cu130", source: "pytorch", setting: "南京大学", bypass: false },
        { label: "依赖", url: "https://pypi.internal.example/simple", source: "pip", setting: "https://pypi.internal.example/simple", bypass: true },
        { label: "pysssss", url: "https://codeload.github.com/y", source: "github", setting: "", bypass: false },
      ],
    });
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    fireEvent.click(await screen.findByRole("radio", { name: "localServiceModeManaged" }));
    const item = (label: string) => (screen.getByText(label, { selector: "li > :not(code), li" }).closest("li") as HTMLElement);
    await screen.findByText("源码");
    expect(within(item("源码")).getByText("localServicePlanSettingGithub")).toBeTruthy();
    expect(item("源码").querySelector("[data-setting-value]")?.textContent).toBe("https://gh.example/");
    expect(item("PyTorch").querySelector("[data-setting-value]")?.textContent).toBe("南京大学");
    expect(within(item("pysssss")).getByText("localServicePlanSettingGithubNone"), "没设前缀:直连 GitHub").toBeTruthy();
    expect(item("依赖").querySelector("[data-bypass]"), "pip 源的主机在 no_proxy 里").toBeTruthy();
    expect(item("源码").querySelector("[data-bypass]")).toBeNull();
    expect(item("PyTorch").querySelector("[data-bypass]")).toBeNull();
  });

  it("这台机器装不了:摆出原因,按钮是灰的;取消回到原来那种", async () => {
    api.getLocalServicePlan.mockResolvedValue({
      ...PLAN, ok: false, supported: false, flavour: "", torch: "", platform: "Linux", verdict: "Linux 这一版不装。可以「用我自己装的」", steps: [],
      downloads: [],
    });
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    fireEvent.click(await screen.findByRole("radio", { name: "localServiceModeManaged" }));
    expect(await screen.findByText(/Linux 这一版不装/)).toBeTruthy();
    expect(screen.getByText("localServicePlanUnsupported")).toBeTruthy();
    expect((screen.getByRole("button", { name: "localServiceInstallStart" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(screen.getByRole("radio", { name: "localServiceModeServer" }).getAttribute("aria-checked")).toBe("true");
  });

  it("空间不够:那一条 error 摆出来(不再说「这台机器装不了」),不让装", async () => {
    // 后端的约定:有一条 error 就是 ok = false
    api.getLocalServicePlan.mockResolvedValue({ ...PLAN, ok: false, problems: [{ level: "error", text: "这块盘只剩 3.0 GB" }] });
    api.getLocalService.mockResolvedValue(managedService());
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    expect(await screen.findByText("这块盘只剩 3.0 GB")).toBeTruthy();
    expect(screen.queryByText("localServicePlanUnsupported")).toBeNull();
    expect((screen.getByRole("button", { name: "localServiceInstallStart" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("在装:第几步、手上那个文件下了多少多快;能取消;这时换不了「在哪跑」", async () => {
    api.getLocalService.mockResolvedValue(managedService({
      install: run({ item: "torch-2.14.1-cp313-cp313-macosx_14_0_arm64.whl", done_bytes: 1_500_000, total_bytes: 3_000_000, speed: 2_000_000 }),
    }));
    api.cancelLocalServiceInstall.mockResolvedValue(managedService({ install: run({ state: "cancelled" }) }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    expect(await screen.findByText("localServiceInstalling")).toBeTruthy();
    expect(screen.getByText("localServiceInstallStepOf")).toBeTruthy();
    expect(screen.getByText("装 PyTorch").closest("li")?.getAttribute("aria-current")).toBe("step");
    expect(screen.getByText(/torch-2\.14\.1-cp313.*1\.5 MB \/ 3\.0 MB · 2\.0 MB\/s/)).toBeTruthy();
    expect(api.getLocalServicePlan, "在装时不再去看计划").not.toHaveBeenCalled();
    for (const radio of screen.getAllByRole("radio")) expect((radio as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /localServiceInstallCancel/ }));
    await waitFor(() => expect(api.cancelLocalServiceInstall).toHaveBeenCalledWith("i1"));
  });

  it("没装成:说停在哪一步、原因;安装日志;按钮变成「接着装」", async () => {
    api.getLocalService.mockResolvedValue(managedService({
      install: run({ state: "failed", step: "torch", error: "装 PyTorch 失败:下载超时或断流。换一个「PyTorch 源」再「接着装」" }),
    }));
    api.getLocalServicePlan.mockResolvedValue({ ...PLAN, steps: PLAN.steps.map((one, index) => ({ ...one, done: index < 2 })) });
    api.getLocalServiceLogs.mockResolvedValue({ lines: ["$ python -m pip install torch==2.14.1"], path: "/data/logs/service-install-i1.log" });
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    expect(await screen.findByText("localServiceInstallFailed")).toBeTruthy();
    expect(screen.getByText(/下载超时或断流/)).toBeTruthy();
    expect(await screen.findByRole("button", { name: "localServiceInstallResume" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /localServiceInstallLog/ }));
    expect(await screen.findByText(/pip install torch/)).toBeTruthy();
    expect(api.getLocalServiceLogs).toHaveBeenCalledWith("i1", 2000, "install");
  });

  it("装好了:链到模型库(不替你下模型);安装位置不给换", async () => {
    api.getLocalService.mockResolvedValue(managedService({
      installed: true, python_minor: "3.13", base_python_minor: "3.13", state: "running",
      install: run({ state: "succeeded", step: "", finished_at: "2026-10-06T06:10:00+00:00" }),
    }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    expect(await screen.findByText("localServiceInstalledTitle")).toBeTruthy();
    expect(screen.getByText("localServiceStateRunning")).toBeTruthy();
    expect(screen.getByText("localServiceInstallLocation")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "localServiceChangeFolder" })).toBeNull();
    expect(screen.getByRole("radio", { name: "localServiceModeManaged" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /localServiceOpenModelLibrary/ }));
    expect(await screen.findByRole("dialog", { name: "model-library:i1" })).toBeTruthy();
  });

  it("运行环境要重建:说清楚哪个 Python 装的,启动是灰的;一键重建先确认", async () => {
    api.getLocalService.mockResolvedValue(managedService({
      installed: true, python_minor: "3.13", base_python_minor: "3.14", needs_rebuild: true,
    }));
    api.getLocalServicePlan.mockResolvedValue({ ...PLAN, steps: PLAN.steps.map((one) => ({ ...one, done: one.key === "download" })) });
    api.installLocalService.mockResolvedValue(managedService({ install: run() }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    expect(await screen.findByText("localServiceRebuildTitle")).toBeTruthy();
    expect((screen.getByRole("button", { name: /localServiceStart/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /localServiceInstallRebuild/ }));
    const button = await screen.findByRole("button", { name: "localServiceInstallRebuild" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("localServiceRebuildConfirmTitle")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "localServiceInstallRebuild" }));
    await waitFor(() => expect(api.installLocalService).toHaveBeenCalledWith("i1", "mps"));
  });

  it("不是部署管理员:不去看计划,装不了", async () => {
    api.getLocalService.mockResolvedValue(managedService({ can_manage: false }));
    mount(<ConnectionLocalService pkg={PKG} instance={INSTANCE} workspaceId="w1" />);
    expect(await screen.findByText("localServiceAdminOnly")).toBeTruthy();
    expect(api.getLocalServicePlan).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "localServiceInstallStart" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
