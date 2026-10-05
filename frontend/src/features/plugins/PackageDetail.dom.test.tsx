/** @vitest-environment jsdom */

/**
 * 插件页上装好的那一个:页头和市场详情是同一个(PluginProfile),下面分「连接」和「关于」两页。
 *
 * 钉住的是用户截图里那一行的毛病:名字、版本、作者、文档挤在一行小字里,读不出哪个能点。现在
 * - 名字是标题,旁边一枚状态(内置 / 已安装 / 可更新);一句话简介;版本 · 作者(能点的是链接);
 * - 能做的事是按钮:新建连接(还没有连接时是主按钮)、有新版时「更新」、文档;卸载收在 ⋯ 里,内置的没有;
 * - 插件 ID、运行方式不再单占一行,在「关于」里;连接是默认那一页。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ market: vi.fn() }));

vi.mock("@/api/client", () => ({
  listPluginCredentials: vi.fn().mockResolvedValue([]),
  savePluginCredentials: vi.fn(),
  listPluginInvocations: vi.fn().mockResolvedValue([]),
  listPluginPermissions: vi.fn().mockResolvedValue([]),
  listPluginMarket: mocks.market,
  fetchWorkflowFieldOptions: vi.fn().mockResolvedValue([]),
  setPluginPermissions: vi.fn().mockResolvedValue([]),
  updatePluginInstance: vi.fn().mockResolvedValue({}),
  createPluginInstance: vi.fn(),
  removePluginPackage: vi.fn(),
}));
vi.mock("@/api/domains/capabilities", () => ({
  listCapabilityTerms: async () => [
    { name: "generation", label: "生成图片、视频和音频", used_by: [{ kind: "app", label: "各处生成的模型下拉" }] },
  ],
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { PluginInstance, PluginPackage } from "@/api/client";
import { PackageDetail } from "./PluginsView";

const comfy = {
  id: "dev.mosael.comfyui",
  name: "ComfyUI",
  version: "1.12.4",
  summary: "接一台 ComfyUI:存着的工作流变成生成模型和工具。",
  description: "把一台 ComfyUI(本机或局域网)接进 Mosael。",
  tools: [{ name: "comfyui_status", label: "看显卡和队列", description: "显卡、队列", effects: "none" }],
  kind: "process",
  multiple: true,
  permissions: ["network:comfyui", "filesystem:write"],
  provides: ["generation"],
  homepage: "https://github.com/comfyanonymous/ComfyUI",
  author_name: "Mosael",
  author_url: "https://mosael.com",
  docs: "https://mosael.com/zh/docs/guides/comfyui",
  summary_field: "",
  config_fields: [],
  credential_fields: [],
  oauth: null,
  bundled: true,
  instances: [],
} as unknown as PluginPackage;

const pan = {
  ...comfy,
  id: "dev.mosael.baidu-pan",
  name: "百度网盘",
  version: "0.7.3",
  summary: "在百度网盘和素材库之间搬文件。",
  permissions: ["network:baidu-pan"],
  provides: [],
  multiple: false,
  bundled: false,
  docs: "",
  homepage: "https://pan.baidu.com/union/doc/",
} as unknown as PluginPackage;

function connection(id: string): PluginInstance {
  return {
    id,
    package_id: pan.id,
    name: "百度网盘",
    enabled: false,
    config: {},
    blocked_reason: "",
    pending_permissions: [],
    permissions_added: false,
    authorization: "",
    tools: [],
    capability_status: {},
  } as unknown as PluginInstance;
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

const hero = () => document.querySelector<HTMLElement>("[data-plugin-hero]")!;

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  window.localStorage.clear();
  mocks.market.mockReset();
});

describe("页头", () => {
  it("名字是标题、旁边一枚状态;下面一句话简介、版本 · 作者(链接)", () => {
    mocks.market.mockResolvedValue({ plugins: [], index_error: "" });
    wrap(<PackageDetail pkg={comfy} workspaceId="w1" />);
    expect(within(hero()).getByRole("heading", { level: 2, name: "ComfyUI" })).toBeTruthy();
    expect(within(hero()).getByText("pluginMarketBundledBadge")).toBeTruthy();
    expect(within(hero()).getByText(comfy.summary!)).toBeTruthy();
    const facts = hero().querySelector<HTMLElement>("[data-plugin-facts]")!;
    expect(facts.textContent).toContain("v1.12.4");
    expect(within(facts).getByRole("link", { name: "Mosael" }).getAttribute("href")).toBe("https://mosael.com");
    //: 内置的那条事实替代了「随 Mosael 一起安装……」那一大块提示。
    expect(within(facts).getByText("pluginBundledFact")).toBeTruthy();
    //: 插件 ID、运行方式不在页头。
    expect(hero().textContent).not.toContain("dev.mosael.comfyui");
  });

  it("能做的事都是按钮:还没有连接时「新建连接」是主按钮;文档是链接;内置的没有 ⋯(卸不掉)", () => {
    mocks.market.mockResolvedValue({ plugins: [], index_error: "" });
    wrap(<PackageDetail pkg={comfy} workspaceId="w1" />);
    const add = within(hero()).getByRole("button", { name: "pluginNewConnection" });
    expect(add.className).toContain("bg-action");
    expect(within(hero()).getByRole("link", { name: "pluginDocs" }).getAttribute("href")).toBe(comfy.docs);
    expect(within(hero()).queryByRole("button", { name: "pluginMore" })).toBeNull();
  });

  it("不是内置的:卸载收在 ⋯ 里;装着的那一版没写 docs 时「文档」退到主页", async () => {
    mocks.market.mockResolvedValue({ plugins: [], index_error: "" });
    const user = userEvent.setup();
    wrap(<PackageDetail pkg={{ ...pan, instances: [connection("c1")] } as PluginPackage} workspaceId="w1" />);
    expect(within(hero()).getByText("pluginMarketInstalledBadge")).toBeTruthy();
    expect(within(hero()).getByRole("link", { name: "pluginDocs" }).getAttribute("href")).toBe(pan.homepage);
    //: 一个连接都建好了、又只许一个:不再给「新建连接」。
    expect(within(hero()).queryByRole("button", { name: "pluginNewConnection" })).toBeNull();
    expect(within(hero()).queryByRole("button", { name: "pluginUninstall" })).toBeNull();
    await user.click(within(hero()).getByRole("button", { name: "pluginMore" }));
    await user.click(await screen.findByRole("menuitem", { name: "pluginUninstall" }));
    expect(await screen.findByRole("alertdialog")).toBeTruthy();
  });

  it("市场说有新版:标「可更新」,写着新版是哪一版,「更新」打开市场里它那一页", async () => {
    mocks.market.mockResolvedValue({
      plugins: [{ id: pan.id, name: pan.name, version: "0.7.4", update_available: true, installed: true, installed_version: "0.7.3", docs: "" }],
      index_error: "",
    });
    const onUpdate = vi.fn();
    const user = userEvent.setup();
    wrap(<PackageDetail pkg={pan} workspaceId="w1" onUpdate={onUpdate} />);
    await waitFor(() => expect(within(hero()).getByText("pluginMarketHasUpdate")).toBeTruthy());
    expect(within(hero()).getByText("pluginLatestVersion")).toBeTruthy();
    //: 有新版时「更新」是主按钮,「新建连接」退成描边的。
    expect(within(hero()).getByRole("button", { name: "pluginNewConnection" }).className).not.toContain("bg-action");
    await user.click(within(hero()).getByRole("button", { name: "pluginUpdate" }));
    expect(onUpdate).toHaveBeenCalled();
  });
});

describe("连接 / 关于", () => {
  it("默认停在「连接」,页签上写着几个", () => {
    mocks.market.mockResolvedValue({ plugins: [], index_error: "" });
    wrap(<PackageDetail pkg={comfy} workspaceId="w1" />);
    const tab = screen.getByRole("tab", { name: "pluginTabConnections 0" });
    expect(tab.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("pluginNoConnections")).toBeTruthy();
  });

  it("「关于」是和市场详情同一份概览:能做什么、介绍、工具、按种类分组的权限、插件 ID", async () => {
    mocks.market.mockResolvedValue({ plugins: [], index_error: "" });
    const user = userEvent.setup();
    wrap(<PackageDetail pkg={comfy} workspaceId="w1" />);
    await user.click(screen.getByRole("tab", { name: "pluginTabAbout" }));
    const provides = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-provides='generation']");
      if (!found?.textContent?.includes("生成图片")) throw new Error("terms not loaded");
      return found;
    });
    expect(provides.querySelector("[data-capability-use]")?.textContent).toBe("各处生成的模型下拉");
    expect(document.querySelector("[data-plugin-about]")?.textContent).toBe(comfy.description);
    expect(document.querySelector("[data-tool='comfyui_status']")?.textContent).toContain("看显卡和队列");
    expect(document.querySelector("[data-permission-group='network'] [data-permission='network:comfyui']")?.textContent).toBe("comfyui");
    expect(document.querySelector("[data-permission-group='filesystem'] [data-permission='filesystem:write']")?.textContent).toBe(
      "pluginPermWriteFiles",
    );
    expect(screen.getByText("dev.mosael.comfyui")).toBeTruthy();
    //: 主页和「文档」不是一处时,主页在信息里。
    expect(screen.getByRole("link", { name: "github.com" }).getAttribute("href")).toBe(comfy.homepage);
  });
});
