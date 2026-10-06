/** @vitest-environment jsdom */

/**
 * 删连接、卸载插件时,背后本机服务的安装目录怎么办(ADR 0041 §4)。钉的是这几条:
 *
 * - 让 Mosael 装的那一份:确认框里两个勾(一起删、保留模型),写明多大、在哪、挪到哪;缺省都勾着,不删就不能「保留模型」;
 * - 只有 Mosael 写的配置(选目录那一种):不问,跟着连接删;
 * - 不是部署管理员:不问、不删(安装目录留着);问不到:说清楚,这一次留着;
 * - 卸载插件:它的连接里还有几份就一起问一次;没有就照旧卸载。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getLocalServiceFootprint: vi.fn(),
  listLocalServiceInstalls: vi.fn(),
  removePluginInstance: vi.fn(),
  removePluginPackage: vi.fn(),
}));
const admin = vi.hoisted(() => ({ value: true }));
vi.mock("@/api/client", () => api);
vi.mock("@/app/auth", () => ({ useIsDeploymentAdmin: () => admin.value }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import type { LocalServiceFootprint } from "@/api/client";
import { DeleteConnectionDialog, UninstallPluginDialog } from "./LocalServiceRemoval";

function footprint(overrides: Partial<LocalServiceFootprint> = {}): LocalServiceFootprint {
  return {
    instance_id: "i1", name: "本机", directory: "/data/local-services/i1", installed: true, bytes: 2_100_000_000,
    models_bytes: 1_200_000_000, has_models: true, keep_to: "/data/local-services/kept-models/本机", ...overrides,
  };
}

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function deleteDialog(onDeleted = vi.fn()) {
  mount(<DeleteConnectionDialog packageId="p1" hasServices instance={{ id: "i1", name: "本机" }} open onCancel={vi.fn()} onDeleted={onDeleted} />);
  return onDeleted;
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.removePluginInstance.mockResolvedValue(undefined);
  api.removePluginPackage.mockResolvedValue(undefined);
  admin.value = true;
});

describe("删连接", () => {
  it("让 Mosael 装的那一份:两个勾写明多大、在哪、挪到哪;缺省一起删并保留模型", async () => {
    api.getLocalServiceFootprint.mockResolvedValue(footprint());
    const onDeleted = deleteDialog();
    const dialog = await screen.findByRole("alertdialog");
    expect(await within(dialog).findByText("localServiceRemoveInstall")).toBeTruthy();
    expect(within(dialog).getByText("localServiceKeepModels")).toBeTruthy();
    const boxes = within(dialog).getAllByRole("checkbox");
    expect(boxes.map((one) => one.getAttribute("aria-checked"))).toEqual(["true", "true"]);
    fireEvent.click(within(dialog).getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(api.removePluginInstance).toHaveBeenCalledWith("i1", { choice: "remove", keepModels: true }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
  });

  it("不保留模型、不删:照选的;不删时「保留模型」是灰的", async () => {
    api.getLocalServiceFootprint.mockResolvedValue(footprint());
    deleteDialog();
    const dialog = await screen.findByRole("alertdialog");
    await within(dialog).findByText("localServiceRemoveInstall");
    const [removeBox, keepBox] = within(dialog).getAllByRole("checkbox");
    fireEvent.click(keepBox);
    fireEvent.click(within(dialog).getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(api.removePluginInstance).toHaveBeenLastCalledWith("i1", { choice: "remove", keepModels: false }));
    fireEvent.click(removeBox);
    expect((within(dialog).getAllByRole("checkbox")[1] as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(api.removePluginInstance).toHaveBeenLastCalledWith("i1", { choice: "keep", keepModels: false }));
  });

  it("只有 Mosael 写的配置(选目录那一种):不问,跟着连接删", async () => {
    api.getLocalServiceFootprint.mockResolvedValue(footprint({ installed: false, has_models: false, models_bytes: 0, bytes: 120 }));
    deleteDialog();
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() => expect(api.getLocalServiceFootprint).toHaveBeenCalledWith("i1"));
    await waitFor(() => expect((within(dialog).getByRole("button", { name: "confirm" }) as HTMLButtonElement).disabled).toBe(false));
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(api.removePluginInstance).toHaveBeenCalledWith("i1", { choice: "remove", keepModels: false }));
  });

  it("不是部署管理员:不问、不删安装目录", async () => {
    admin.value = false;
    deleteDialog();
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(api.removePluginInstance).toHaveBeenCalledWith("i1", undefined));
    expect(api.getLocalServiceFootprint).not.toHaveBeenCalled();
  });

  it("问不到:说清楚,这一次安装目录留着", async () => {
    api.getLocalServiceFootprint.mockRejectedValue(new Error("插件没授权"));
    deleteDialog();
    const dialog = await screen.findByRole("alertdialog");
    expect(await within(dialog).findByText("localServiceFootprintError")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(api.removePluginInstance).toHaveBeenCalledWith("i1", undefined));
  });
});

describe("卸载插件", () => {
  function uninstallDialog(onDone = vi.fn()) {
    mount(<UninstallPluginDialog packageId="p1" name="测试插件" open onCancel={vi.fn()} onDone={onDone} />);
    return onDone;
  }

  it("连接里还有让 Mosael 装的:一起问一次;缺省一起删并保留模型", async () => {
    api.listLocalServiceInstalls.mockResolvedValue([footprint(), footprint({ instance_id: "i2", name: "另一份" }),
                                                    footprint({ instance_id: "i3", installed: false, has_models: false })]);
    const onDone = uninstallDialog();
    const dialog = await screen.findByRole("alertdialog");
    expect(await within(dialog).findByText("pluginUninstallLocalServices")).toBeTruthy();
    expect(within(dialog).getAllByRole("checkbox")).toHaveLength(2);
    fireEvent.click(within(dialog).getByRole("button", { name: "pluginUninstall" }));
    await waitFor(() => expect(api.removePluginPackage).toHaveBeenCalledWith("p1", { choice: "remove", keepModels: true }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("选不删:安装目录留在磁盘上", async () => {
    api.listLocalServiceInstalls.mockResolvedValue([footprint()]);
    uninstallDialog();
    const dialog = await screen.findByRole("alertdialog");
    await within(dialog).findByText("pluginUninstallLocalServices");
    fireEvent.click(within(dialog).getAllByRole("checkbox")[0]);
    fireEvent.click(within(dialog).getByRole("button", { name: "pluginUninstall" }));
    await waitFor(() => expect(api.removePluginPackage).toHaveBeenCalledWith("p1", { choice: "keep", keepModels: false }));
  });

  it("没有安装目录:照旧卸载,不带选择;问不到:说清楚、留着", async () => {
    api.listLocalServiceInstalls.mockResolvedValue([]);
    const view = mount(<UninstallPluginDialog packageId="p1" name="测试插件" open onCancel={vi.fn()} onDone={vi.fn()} />);
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() => expect((within(dialog).getByRole("button", { name: "pluginUninstall" }) as HTMLButtonElement).disabled).toBe(false));
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "pluginUninstall" }));
    await waitFor(() => expect(api.removePluginPackage).toHaveBeenCalledWith("p1", undefined));
    view.unmount();
    api.listLocalServiceInstalls.mockRejectedValue(new Error("插件没授权"));
    uninstallDialog();
    const again = await screen.findByRole("alertdialog");
    expect(await within(again).findByText("localServiceFootprintError")).toBeTruthy();
    fireEvent.click(within(again).getByRole("button", { name: "pluginUninstall" }));
    await waitFor(() => expect(api.removePluginPackage).toHaveBeenLastCalledWith("p1", { choice: "keep", keepModels: false }));
  });
});
