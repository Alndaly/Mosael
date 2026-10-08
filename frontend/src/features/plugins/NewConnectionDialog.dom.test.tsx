/** @vitest-environment jsdom */

/**
 * 「新建连接」弹窗里一开始就选在哪跑(ADR 0041)。维护者:「ComfyUI 插件的新建连接这里表单就有问题了 —— 因为支持多种方式,
 * 但这个新建连接的表单仅支持服务器地址。」钉的是:
 *
 * - 「在哪跑」只给声明了本机服务的插件,缺省「连一台服务器」,那一种和以前一样只填配置;
 * - 用我自己装的:装在哪 + 解释器,服务器地址那一格不摆(端口由宿主分);新建之前确认一次「会运行这个目录里的代码」,
 *   建好马上认一遍、不再问;让 Mosael 装:没有路径,不确认、建好也不替人开始装;
 * - 本机的两种:插件要的权限列出来、建好时一起授予;别的配置项照样在;
 * - 不是部署管理员:本机的两种是灰的、说为什么;
 * - 建好之后:新连接展开,卡片上就是认目录的结果 / 安装计划(「开始安装」等人点)。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createPluginInstance: vi.fn(),
  detectLocalService: vi.fn(),
  getLocalService: vi.fn(),
  getLocalServicePlan: vi.fn(),
  getLocalServiceModelFolders: vi.fn(),
  getLocalServiceVersions: vi.fn(),
  installLocalService: vi.fn(),
  discoverLocalServices: vi.fn(),
  listPluginMarket: vi.fn(),
  listPluginPermissions: vi.fn(),
  listPluginInvocations: vi.fn(),
  listPluginCredentials: vi.fn(),
  isCustomServer: vi.fn(),
}));
vi.mock("@/api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/api/client")>()), ...api }));
const admin = vi.hoisted(() => ({ value: true }));
vi.mock("@/app/auth", () => ({ useIsDeploymentAdmin: () => admin.value }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));
vi.mock("@/features/plugins/ModelLibrary", () => ({ ModelLibraryDialog: () => null }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
//: CodeMirror 在 jsdom 里量不了排版:JSON 那一格换成一个文本框(和 CodeConfigField 的测试一样)。
vi.mock("@/components/app/code-editor", () => ({
  CodeEditor: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
    <textarea data-testid="code-editor" value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}));

import type { LocalService, PluginInstance, PluginPackage } from "@/api/client";
import { NewConnectionDialog, PackageDetail } from "./PluginsView";

const field = (key: string, label: string, extra: Record<string, unknown> = {}) => ({
  key, label, type: "string", required: false, default: "", help: "", secret: false, options: [], multiline: false, ...extra,
});

const COMFY = {
  id: "dev.mosael.comfyui", name: "ComfyUI", version: "1.16.0", kind: "process", multiple: true, bundled: true,
  summary: "", description: "", tools: [], docs: "", homepage: "", author_name: "", author_url: "", oauth: null,
  provides: [], summary_field: "server_url",
  services: [{ key: "comfyui", title: "ComfyUI", tool: "comfyui_generation" }],
  permissions: ["network:comfyui", "filesystem:write"],
  config_fields: [
    field("server_url", "服务器地址", { required: true, default: "http://127.0.0.1:8188" }),
    //: 一项别的配置(一段 JSON):本机的两种模式里也照样列出来、建连接时一起交上去
    field("extra_options", "额外参数(可选)", { type: "json", language: "json" }),
  ],
  credential_fields: [field("access_token", "访问凭据(可选)", { secret: true })],
  instances: [],
} as unknown as PluginPackage;

const CREATED = {
  id: "new1", package_id: COMFY.id, name: "ComfyUI · http://127.0.0.1:8189", enabled: false,
  config: { server_url: "http://127.0.0.1:8189", extra_options: "" }, blocked_reason: "", pending_permissions: [],
  permissions_added: false, authorization: "", tools: [], capability_status: {}, network: { mode: "follow", proxy_url: "" },
} as unknown as PluginInstance;

const FOUND = { ok: true, facts: [{ label: "ComfyUI 版本", value: "0.39.0" }], problems: [], add_nodes: null };

const PLAN = {
  ok: true, supported: true, platform: "Apple 芯片 Mac", verdict: "PyPI 上的 PyTorch 直接带 MPS", flavour: "mps",
  torch: "PyTorch 2.14.1(MPS)", version: "0.39.0", disk_bytes: 5e9, free_bytes: 200e9, directory: "/data/local-services/new1",
  steps: [{ key: "disk", title: "查剩余空间", done: false }, { key: "trial", title: "试起一次", done: false }],
  downloads: [], route: { kind: "system", proxy: "" }, problems: [],
};

function service(overrides: Partial<LocalService> = {}): LocalService {
  return {
    instance_id: "new1", service: "comfyui", title: "ComfyUI", mode: "directory", directory: "/Users/me/ComfyUI", python: "",
    port: 8189, url: "http://127.0.0.1:8189", listen_lan: false, keep_running: false, extra_args: [], state: "stopped",
    pid: null, started_at: null, ready_seconds: null, adopted: false, restarts: 0, error: "", failure_lines: [],
    can_manage: true, installed: true, python_minor: "", base_python_minor: "", needs_rebuild: false, install: null,
    shared_models: [], issue: null, idle_stop_minutes: 30, idle_stopped: false,
    ...overrides,
  } as LocalService;
}

function mount(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  return { ...view, rerender: (next: React.ReactElement) => view.rerender(next) };
}

function dialog(pkg: PluginPackage = COMFY) {
  const onOpenChange = vi.fn();
  const onCreated = vi.fn();
  mount(<NewConnectionDialog pkg={pkg} open onOpenChange={onOpenChange} onCreated={onCreated} />);
  return { onOpenChange, onCreated };
}

const addButton = () => screen.getByRole("button", { name: "pluginAddConnection" }) as HTMLButtonElement;
const radio = (name: string) => screen.getByRole("radio", { name }) as HTMLButtonElement;

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  admin.value = true;
  api.createPluginInstance.mockResolvedValue(CREATED);
  api.detectLocalService.mockResolvedValue(FOUND);
  api.getLocalService.mockResolvedValue(null);
  api.getLocalServicePlan.mockResolvedValue(PLAN);
  api.getLocalServiceModelFolders.mockResolvedValue({ folders: [], running: false, suggestions: [] });
  api.getLocalServiceVersions.mockResolvedValue({ current: "0.39.0", latest: "0.39.0", update: "", previous: "", unfinished: "" });
  api.discoverLocalServices.mockResolvedValue({ servers: [] });
  api.listPluginMarket.mockResolvedValue({ plugins: [], index_error: "" });
  api.listPluginPermissions.mockResolvedValue([]);
  api.listPluginInvocations.mockResolvedValue([]);
  api.listPluginCredentials.mockResolvedValue([]);
  api.isCustomServer.mockReturnValue(false);
});

afterEach(() => {
  window.localStorage.clear();
});

describe("在哪跑", () => {
  it("没声明本机服务的插件:没有「在哪跑」,和以前一样只填配置", async () => {
    dialog({ ...COMFY, services: [] } as unknown as PluginPackage);
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.getByText("服务器地址")).toBeTruthy();
    fireEvent.click(addButton());
    await waitFor(() => expect(api.createPluginInstance).toHaveBeenCalledWith(COMFY.id, { config: {} }));
  });

  it("声明了本机服务:三种,缺省连一台服务器 —— 那一种和以前一样,不带本机服务、不授予权限", async () => {
    dialog();
    const group = screen.getByRole("radiogroup", { name: "localServiceWhere" });
    expect(within(group).getAllByRole("radio").map((one) => one.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
    expect(screen.getByText("服务器地址")).toBeTruthy();
    expect(screen.queryByLabelText("localServiceDirectory")).toBeNull();
    expect(document.querySelector("[data-new-connection-permissions]")).toBeNull();
    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: "http://192.168.1.5:8188" } });
    fireEvent.click(addButton());
    await waitFor(() => expect(api.createPluginInstance).toHaveBeenCalledWith(COMFY.id, {
      config: { server_url: "http://192.168.1.5:8188" },
    }));
  });
});

describe("按回车", () => {
  //: 此前是一组散的输入框 + 右下角一颗点击的按钮,在「服务器地址」里按回车什么也不做。
  it("在配置项里敲回车就是「新建」;点「在哪跑」这种表单里的普通按钮不新建", async () => {
    const user = userEvent.setup();
    dialog();
    await user.click(radio("localServiceModeServer"));
    expect(api.createPluginInstance).not.toHaveBeenCalled();
    const address = screen.getAllByRole("textbox")[0];
    await user.clear(address);
    await user.type(address, "http://192.168.1.6:8188{Enter}");
    await waitFor(() => expect(api.createPluginInstance).toHaveBeenCalledWith(COMFY.id, {
      config: { server_url: "http://192.168.1.6:8188" },
    }));
  });
});

describe("用我自己装的", () => {
  it("装在哪 + 解释器;服务器地址不摆(宿主分);别的配置项和要授予的权限照样列出来", () => {
    dialog();
    fireEvent.click(radio("localServiceModeDirectory"));
    expect(screen.getByLabelText("localServiceDirectory")).toBeTruthy();
    expect(screen.getByLabelText("localServicePython")).toBeTruthy();
    expect(screen.queryByText("服务器地址"), "地址由 Mosael 分端口").toBeNull();
    expect(screen.getByText("localServiceAddressOnCreate")).toBeTruthy();
    expect(screen.getByText("额外参数(可选)"), "别的配置项三种都有").toBeTruthy();
    const permissions = document.querySelector<HTMLElement>("[data-new-connection-permissions]")!;
    expect(permissions.textContent).toContain("network:comfyui");
    expect(permissions.textContent).toContain("filesystem:write");
    expect(addButton().disabled, "目录空着不让建").toBe(true);
  });

  it("新建之前确认一次会运行这个目录里的代码;建好马上认一遍目录,不再问", async () => {
    const { onOpenChange, onCreated } = dialog();
    fireEvent.click(radio("localServiceModeDirectory"));
    fireEvent.change(screen.getByLabelText("localServiceDirectory"), { target: { value: " /Users/me/ComfyUI " } });
    fireEvent.change(screen.getByTestId("code-editor"), { target: { value: '{"1": {}}' } });
    fireEvent.click(addButton());
    expect(api.createPluginInstance, "没确认之前什么都不建").not.toHaveBeenCalled();
    const confirm = await screen.findByRole("alertdialog");
    expect(within(confirm).getByText("localServiceConfirmTitle")).toBeTruthy();
    expect(within(confirm).getByText("localServiceConfirmBody")).toBeTruthy();
    fireEvent.click(within(confirm).getByRole("button", { name: "localServiceConfirmRun" }));
    await waitFor(() => expect(api.createPluginInstance).toHaveBeenCalledWith(COMFY.id, {
      config: { extra_options: '{"1": {}}' },
      grant_permissions: ["network:comfyui", "filesystem:write"],
      local_service: { mode: "directory", directory: "/Users/me/ComfyUI", python: "", confirm_run_code: true },
    }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("new1"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(api.detectLocalService).toHaveBeenCalledWith("new1", "/Users/me/ComfyUI", "");
    await waitFor(() => expect(screen.queryByRole("alertdialog"), "确认一次就够").toBeNull());
  });

  it("没建成:确认框收起,弹窗里填的还在", async () => {
    api.createPluginInstance.mockRejectedValue(new Error("从 8189 往上找不到空着的端口"));
    const { onCreated } = dialog();
    fireEvent.click(radio("localServiceModeDirectory"));
    fireEvent.change(screen.getByLabelText("localServiceDirectory"), { target: { value: "/Users/me/ComfyUI" } });
    fireEvent.click(addButton());
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceConfirmRun" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onCreated).not.toHaveBeenCalled();
    expect(api.detectLocalService).not.toHaveBeenCalled();
    expect((screen.getByLabelText("localServiceDirectory") as HTMLInputElement).value).toBe("/Users/me/ComfyUI");
  });
});

describe("草稿", () => {
  function Harness() {
    const [open, setOpen] = React.useState(true);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>reopen</button>
        <NewConnectionDialog pkg={COMFY} open={open} onOpenChange={setOpen} onCreated={() => {}} />
      </>
    );
  }

  it("取消了再打开:还是刚才填的;建好了再打开:一张新的(不在关窗的淡出里跳回缺省)", async () => {
    mount(<Harness />);
    fireEvent.click(radio("localServiceModeDirectory"));
    fireEvent.change(screen.getByLabelText("localServiceDirectory"), { target: { value: "/Users/me/ComfyUI" } });
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "reopen" }));
    expect(radio("localServiceModeDirectory").getAttribute("aria-checked")).toBe("true");
    expect((screen.getByLabelText("localServiceDirectory") as HTMLInputElement).value).toBe("/Users/me/ComfyUI");

    fireEvent.click(addButton());
    const confirm = await screen.findByRole("alertdialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "localServiceConfirmRun" }));
    await waitFor(() => expect(api.createPluginInstance).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "reopen" }));
    expect(radio("localServiceModeServer").getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByLabelText("localServiceDirectory")).toBeNull();
  });
});

describe("让 Mosael 装", () => {
  it("没有路径、不摆服务器地址;不确认就建,建好也不替人开始装", async () => {
    const { onCreated } = dialog();
    fireEvent.click(radio("localServiceModeManaged"));
    expect(screen.queryByLabelText("localServiceDirectory")).toBeNull();
    expect(screen.queryByLabelText("localServicePython")).toBeNull();
    expect(screen.queryByText("服务器地址")).toBeNull();
    expect(screen.getByText("localServiceNewManagedDesc")).toBeTruthy();
    fireEvent.click(addButton());
    await waitFor(() => expect(api.createPluginInstance).toHaveBeenCalledWith(COMFY.id, {
      config: {},
      grant_permissions: ["network:comfyui", "filesystem:write"],
      local_service: { mode: "managed", directory: "", python: "", confirm_run_code: false },
    }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("new1"));
    expect(api.detectLocalService).not.toHaveBeenCalled();
    expect(api.installLocalService).not.toHaveBeenCalled();
  });
});

describe("不是部署管理员", () => {
  it("本机的两种是灰的、说为什么;连一台服务器照常能建", async () => {
    admin.value = false;
    dialog();
    expect(radio("localServiceModeDirectory").disabled).toBe(true);
    expect(radio("localServiceModeManaged").disabled).toBe(true);
    expect(radio("localServiceModeServer").disabled).toBe(false);
    expect(screen.getByText("localServiceNewAdminOnly")).toBeTruthy();
    fireEvent.click(radio("localServiceModeDirectory"));
    expect(screen.queryByLabelText("localServiceDirectory")).toBeNull();
    fireEvent.click(addButton());
    await waitFor(() => expect(api.createPluginInstance).toHaveBeenCalledWith(COMFY.id, { config: {} }));
  });
});

describe("建好之后", () => {
  async function createFromPage(mode: "localServiceModeDirectory" | "localServiceModeManaged") {
    const view = mount(<PackageDetail pkg={COMFY} workspaceId="w1" />);
    fireEvent.click(within(document.querySelector<HTMLElement>("[data-plugin-hero]")!).getByRole("button", { name: "pluginNewConnection" }));
    fireEvent.click(await screen.findByRole("radio", { name: mode }));
    if (mode === "localServiceModeDirectory") {
      fireEvent.change(screen.getByLabelText("localServiceDirectory"), { target: { value: "/Users/me/ComfyUI" } });
      fireEvent.click(addButton());
      fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "localServiceConfirmRun" }));
    } else {
      fireEvent.click(addButton());
    }
    await waitFor(() => expect(api.createPluginInstance).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // 插件列表重读回来,新连接在里面
    view.rerender(<PackageDetail pkg={{ ...COMFY, instances: [CREATED] } as unknown as PluginPackage} workspaceId="w1" />);
    const card = document.querySelector<HTMLElement>("[data-connection='new1']")!;
    expect(card.querySelector("[aria-expanded]")?.getAttribute("aria-expanded"), "刚建的展开").toBe("true");
    const scrolled = vi.mocked(Element.prototype.scrollIntoView);
    await waitFor(() => expect(scrolled.mock.contexts, "滚到刚建的那个(几个连接时它在最下面)").toContain(card));
    return card;
  }

  it("用我自己装的:卡片上本机服务那一块摆着刚才认目录的结果", async () => {
    api.getLocalService.mockResolvedValue(service());
    const card = await createFromPage("localServiceModeDirectory");
    await waitFor(() => expect(within(card).getByText("0.39.0")).toBeTruthy());
    expect(within(card).getByText("ComfyUI 版本")).toBeTruthy();
    expect(api.detectLocalService, "认一遍就够,卡片不再自己跑").toHaveBeenCalledTimes(1);
  });

  it("用我自己装的、认不出:卡片上说这个目录现在起不来,问题标红", async () => {
    api.detectLocalService.mockResolvedValue({ ok: false, facts: [], add_nodes: null, problems: [{ level: "error", text: "这里没有 main.py" }] });
    api.getLocalService.mockResolvedValue(service());
    const card = await createFromPage("localServiceModeDirectory");
    await waitFor(() => expect(within(card).getByText("这里没有 main.py")).toBeTruthy());
    expect(within(card).getByText("localServiceNotUsable")).toBeTruthy();
    expect(within(card).getByRole("button", { name: "localServiceChangeFolder" })).toBeTruthy();
  });

  it("让 Mosael 装:卡片上就是安装计划,「开始安装」等人看过再点", async () => {
    api.getLocalService.mockResolvedValue(service({ mode: "managed", directory: "/data/local-services/new1", installed: false }));
    const card = await createFromPage("localServiceModeManaged");
    await waitFor(() => expect(within(card).getByText("PyTorch 2.14.1(MPS)")).toBeTruthy());
    expect(within(card).getByRole("button", { name: "localServiceInstallStart" })).toBeTruthy();
    expect(api.installLocalService).not.toHaveBeenCalled();
  });
});
