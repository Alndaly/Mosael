/** @vitest-environment jsdom */
/**
 * 插件市场:卡片网格 → 点开一页详情。
 *
 * 钉住的是用户会碰到的几件事:卡片上的摘要不露 markdown 标记、点名字或按回车都能看详情、
 * 返回键和 Esc 都退回网格并把焦点还给那张卡、从卡片和从详情都能装(装之前先确认权限)、
 * 搜索和筛选收窄的是卡片。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const OSS = {
  id: "dev.mosael.aliyun-oss", name: "阿里云 OSS", version: "0.1.2", download: "https://x/oss.zip",
  description: "把素材传到阿里云 OSS,换回一条**公网直链** —— 有些供应商只收链接。",
  permissions: ["network:oss"], installed: false, installed_version: "", author: "Mosael", author_url: "https://mosael.com",
  docs: "https://mosael.com/zh/plugins/aliyun-oss", homepage: "https://help.aliyun.com/zh/oss/",
  runtime: "process", provides: ["public_url"],
  tools: [{ name: "oss_upload", label: "", description: "传一份素材,交回一条**限时直链**" }],
};
const PAN = {
  id: "dev.mosael.baidu-pan", name: "百度网盘", version: "0.5.1", download: "https://x/pan.zip",
  description: "在百度网盘和素材库之间搬文件。", permissions: ["network:baidu-pan"],
  installed: true, installed_version: "0.5.0", author: "Mosael", author_url: "", docs: "", homepage: "",
  runtime: "process", provides: [], tools: [{ name: "pan_list", label: "", description: "" }],
};
const MCP = {
  id: "dev.mosael.mcp-everything", name: "MCP Everything", version: "0.1.0", download: "https://x/mcp.zip",
  description: "把一个现成的 MCP server 接成插件。", permissions: ["process:spawn"],
  installed: true, installed_version: "0.1.0", author: "Mosael", author_url: "", docs: "", homepage: "",
  runtime: "mcp", provides: [], tools: [],
};

const mocks = vi.hoisted(() => ({
  preview: vi.fn(),
  install: vi.fn(async () => []),
  remove: vi.fn(async (_id: string) => ({})),
}));

vi.mock("@/api/client", () => ({
  listPluginMarket: async () => [OSS, PAN, MCP],
  previewPluginInstall: mocks.preview,
  installPlugin: mocks.install,
  removePluginPackage: mocks.remove,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { PluginMarketDialog } from "@/features/plugins/PluginMarket";

function renderMarket() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onChanged = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <PluginMarketDialog open onOpenChange={vi.fn()} onChanged={onChanged} />
    </QueryClientProvider>,
  );
  return { onChanged };
}

const cards = () => screen.getAllByRole("article");
const card = (name: string) => cards().find((one) => within(one).queryByRole("button", { name }))!;

beforeEach(() => {
  mocks.preview.mockReset();
  mocks.preview.mockImplementation(async (url: string) => ({
    id: url.includes("oss") ? OSS.id : PAN.id, name: url.includes("oss") ? OSS.name : PAN.name, version: "0.1.2",
    description: "", permissions: ["network:oss"], tools: ["oss_upload"], installed: url.includes("pan"),
    installed_version: url.includes("pan") ? "0.5.0" : "", author_name: "Mosael", author_url: "", docs: "", homepage: "",
  }));
  mocks.install.mockClear();
  mocks.remove.mockClear();
});

describe("插件市场的卡片网格", () => {
  it("每个插件一张卡,放在一份列表里", async () => {
    renderMarket();
    const list = await screen.findByRole("list", { name: "pluginMarket" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(cards()).toHaveLength(3);
  });

  it("卡片摘要不露 markdown 标记", async () => {
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    const oss = card("阿里云 OSS");
    expect(oss.textContent).toContain("换回一条公网直链");
    expect(oss.textContent).not.toContain("**");
  });

  it("状态三态:没装的给「安装」,有新版的给「更新」,已是最新的不给按钮", async () => {
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    expect(within(card("阿里云 OSS")).getByRole("button", { name: "pluginInstall" })).toBeTruthy();
    expect(within(card("百度网盘")).getByRole("button", { name: "pluginUpdate" })).toBeTruthy();
    expect(within(card("百度网盘")).getByText("pluginMarketHasUpdate")).toBeTruthy();
    const current = card("MCP Everything");
    expect(within(current).queryByRole("button", { name: /pluginInstall|pluginUpdate/ })).toBeNull();
    expect(within(current).getByText("pluginMarketInstalledBadge")).toBeTruthy();
  });

  it("搜索也搜说明和工具名,筛选收窄到已安装", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.type(screen.getByRole("textbox", { name: "pluginMarketSearch" }), "pan_list");
    expect(cards().map((one) => within(one).getByRole("heading").textContent)).toEqual(["百度网盘"]);
    await user.clear(screen.getByRole("textbox", { name: "pluginMarketSearch" }));
    await user.click(screen.getByRole("button", { name: "pluginMarketFilterInstalled 2" }));
    expect(cards().map((one) => within(one).getByRole("heading").textContent)).toEqual(["百度网盘", "MCP Everything"]);
  });
});

describe("插件详情", () => {
  it("点卡片名字打开详情:markdown 渲染成粗体,权限说人话,工具列出来", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("阿里云 OSS")).getByRole("button", { name: "阿里云 OSS" }));

    expect(screen.getByRole("heading", { level: 3, name: "阿里云 OSS" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "pluginMarket" })).toBeNull();
    const dialog = screen.getByRole("dialog");
    const bold = await within(dialog).findByText("公网直链");
    expect(bold.tagName === "STRONG" || bold.getAttribute("data-streamdown") === "strong", bold.outerHTML).toBe(true);
    //: 说明和工具说明里的记号都按格式渲染,一个星号都不露。
    expect(dialog.textContent).not.toContain("**");
    expect(within(dialog).getByText("限时直链").tagName).toBe("STRONG");
    expect(within(dialog).getByText("pluginPermNetwork")).toBeTruthy();
    expect(within(dialog).getByText("network:oss")).toBeTruthy();
    expect(within(dialog).getByText("oss_upload")).toBeTruthy();
    expect(within(dialog).getByText("pluginProvidesPublicUrl")).toBeTruthy();
    // 进详情时焦点给返回键:读屏从这一页的开头读起。
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "pluginMarketBack" }));
  });

  it("键盘:Tab 到卡片名字、回车打开;返回键退回网格,焦点回到那张卡", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    const open = within(card("百度网盘")).getByRole("button", { name: "百度网盘" });
    open.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { level: 3, name: "百度网盘" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "pluginMarketBack" }));
    expect(await screen.findByRole("list", { name: "pluginMarket" })).toBeTruthy();
    expect(document.activeElement).toBe(within(card("百度网盘")).getByRole("button", { name: "百度网盘" }));
  });

  it("Esc 先退回网格,不关弹窗", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <PluginMarketDialog open onOpenChange={onOpenChange} onChanged={vi.fn()} />
      </QueryClientProvider>,
    );
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("阿里云 OSS")).getByRole("button", { name: "阿里云 OSS" }));
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(await screen.findByRole("list", { name: "pluginMarket" })).toBeTruthy();
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("MCP 插件没有声明工具:说清楚工具由服务提供,不留一块空白", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("MCP Everything")).getByRole("button", { name: "MCP Everything" }));
    expect(screen.getByText("pluginMarketMcpToolsBody")).toBeTruthy();
    expect(screen.getByText("pluginPermProcess")).toBeTruthy();
  });
});

describe("安装", () => {
  it("从卡片装:先弹确认(列出权限),点了才装", async () => {
    const user = userEvent.setup();
    const { onChanged } = renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("阿里云 OSS")).getByRole("button", { name: "pluginInstall" }));
    expect(mocks.preview).toHaveBeenCalledWith("https://x/oss.zip");
    const confirm = await screen.findByRole("dialog", { name: "pluginInstallConfirmTitle" });
    expect(within(confirm).getByText("network:oss")).toBeTruthy();
    expect(mocks.install).not.toHaveBeenCalled();
    await user.click(within(confirm).getByRole("button", { name: "pluginInstall" }));
    await waitFor(() => expect(mocks.install).toHaveBeenCalledWith("https://x/oss.zip", false));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("从详情更新:确认后覆盖装", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("百度网盘")).getByRole("button", { name: "百度网盘" }));
    await user.click(screen.getByRole("button", { name: "pluginUpdate" }));
    const confirm = await screen.findByRole("dialog", { name: "pluginInstallConfirmTitle" });
    await user.click(within(confirm).getByRole("button", { name: "pluginUpdate" }));
    await waitFor(() => expect(mocks.install).toHaveBeenCalledWith("https://x/pan.zip", true));
  });

  it("详情里能卸载已装的插件,要先确认", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("MCP Everything")).getByRole("button", { name: "MCP Everything" }));
    await user.click(screen.getByRole("button", { name: "pluginUninstall" }));
    expect(mocks.remove).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("alertdialog");
    await user.click(within(confirm).getByRole("button", { name: "pluginUninstall" }));
    await waitFor(() => expect(mocks.remove).toHaveBeenCalled());
    expect(mocks.remove.mock.calls[0][0]).toBe("dev.mosael.mcp-everything");
  });
});
