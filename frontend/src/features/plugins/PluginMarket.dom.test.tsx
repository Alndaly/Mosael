/** @vitest-environment jsdom */
/**
 * 插件市场:卡片网格 → 点开一页详情。
 *
 * 钉住的是用户会碰到的几件事:卡片上的摘要不露 markdown 标记、点名字或按回车都能看详情、
 * 返回键和 Esc 都退回网格并把焦点还给那张卡、从卡片和从详情都能装(装之前先确认权限)、
 * 搜索和筛选收窄的是卡片。随应用内置的插件(ComfyUI)搜得到、标「内置」、不给装 / 更新 / 卸载;
 * 远端索引拉不到时照样列出内置的,并说清楚为什么只有这几个。
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
  installed: true, installed_version: "0.5.0", update_available: true, update_unreleased: false,
  author: "Mosael", author_url: "", docs: "", homepage: "",
  runtime: "process", provides: [], tools: [{ name: "pan_list", label: "", description: "" }],
};
const MCP = {
  id: "dev.example.mcp-sample", name: "MCP Sample", version: "0.1.0", download: "https://x/mcp.zip",
  description: "把一个现成的 MCP server 接成插件。", permissions: ["process:spawn"],
  installed: true, installed_version: "0.1.0", update_available: false, update_unreleased: false,
  author: "Mosael", author_url: "", docs: "", homepage: "",
  runtime: "mcp", provides: [], tools: [],
};

const COMFY = {
  id: "dev.mosael.comfyui", name: "ComfyUI", version: "1.0.0", download: "",
  description: "把一台 ComfyUI 接成图像 / 视频生成供应商。", permissions: ["network:comfyui"],
  installed: true, installed_version: "1.0.0", author: "Mosael", author_url: "https://mosael.com",
  docs: "https://mosael.com/zh/docs/guides/comfyui", homepage: "https://github.com/comfyanonymous/ComfyUI",
  runtime: "process", provides: ["generation"], tools: [{ name: "comfyui_run", label: "", description: "" }], bundled: true,
};

const mocks = vi.hoisted(() => ({
  market: vi.fn(),
  preview: vi.fn(),
  install: vi.fn(async () => []),
  remove: vi.fn(async (_id: string) => ({})),
}));

vi.mock("@/api/client", () => ({
  listPluginMarket: mocks.market,
  previewPluginInstall: mocks.preview,
  installPlugin: mocks.install,
  removePluginPackage: mocks.remove,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

import { toast } from "sonner";
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
  mocks.market.mockReset();
  mocks.market.mockImplementation(async () => ({ plugins: [OSS, PAN, MCP], index_error: "" }));
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
    const current = card("MCP Sample");
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
    expect(cards().map((one) => within(one).getByRole("heading").textContent)).toEqual(["百度网盘", "MCP Sample"]);
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
    await user.click(within(card("MCP Sample")).getByRole("button", { name: "MCP Sample" }));
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
    expect(mocks.preview).toHaveBeenCalledWith("https://x/oss.zip", "0.1.2");
    const confirm = await screen.findByRole("dialog", { name: "pluginInstallConfirmTitle" });
    expect(within(confirm).getByText("network:oss")).toBeTruthy();
    expect(mocks.install).not.toHaveBeenCalled();
    await user.click(within(confirm).getByRole("button", { name: "pluginInstall" }));
    await waitFor(() => expect(mocks.install).toHaveBeenCalledWith("https://x/oss.zip", false, "0.1.2"));
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
    await waitFor(() => expect(mocks.install).toHaveBeenCalledWith("https://x/pan.zip", true, "0.5.1"));
  });

  it("确认卡上的版本是包里实际那一版;和市场写的不同时点明", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("百度网盘")).getByRole("button", { name: "pluginUpdate" }));
    //: 预览回的是 0.1.2(包里的清单),市场写的是 0.5.1。
    const confirm = await screen.findByRole("dialog", { name: "pluginInstallConfirmTitle" });
    expect(within(confirm).getByText("v0.1.2")).toBeTruthy();
    expect(within(confirm).getByText("pluginInstallVersionDiffers")).toBeTruthy();
  });

  it("详情里能卸载已装的插件,要先确认", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("MCP Sample")).getByRole("button", { name: "MCP Sample" }));
    await user.click(screen.getByRole("button", { name: "pluginUninstall" }));
    expect(mocks.remove).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("alertdialog");
    await user.click(within(confirm).getByRole("button", { name: "pluginUninstall" }));
    await waitFor(() => expect(mocks.remove).toHaveBeenCalled());
    expect(mocks.remove.mock.calls[0][0]).toBe("dev.example.mcp-sample");
  });
});

describe("随应用内置的插件", () => {
  const withComfy = () => mocks.market.mockImplementation(async () => ({ plugins: [COMFY, OSS, PAN, MCP], index_error: "" }));

  it("搜「comfy」找得到它:标「内置」,不给安装 / 更新", async () => {
    withComfy();
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.type(screen.getByRole("textbox", { name: "pluginMarketSearch" }), "comfy");
    expect(cards().map((one) => within(one).getByRole("heading").textContent)).toEqual(["ComfyUI"]);
    const comfy = card("ComfyUI");
    expect(within(comfy).getByText("pluginMarketBundledBadge")).toBeTruthy();
    expect(within(comfy).queryByRole("button", { name: /pluginInstall|pluginUpdate/ })).toBeNull();
  });

  it("「已安装」筛选里有它,「有新版」里没有", async () => {
    withComfy();
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(screen.getByRole("button", { name: "pluginMarketFilterInstalled 3" }));
    expect(cards().map((one) => within(one).getByRole("heading").textContent)).toContain("ComfyUI");
    await user.click(screen.getByRole("button", { name: "pluginMarketFilterUpdates 1" }));
    expect(cards().map((one) => within(one).getByRole("heading").textContent)).toEqual(["百度网盘"]);
  });

  it("详情:说它随应用安装和更新,没有安装 / 更新 / 卸载", async () => {
    withComfy();
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("ComfyUI")).getByRole("button", { name: "ComfyUI" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("pluginMarketBundledNote")).toBeTruthy();
    expect(within(dialog).getByText("pluginMarketBundledBadge")).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: /pluginInstall|pluginUpdate|pluginUninstall/ })).toBeNull();
  });

  it("远端索引拉不到:照样列出内置的,并说清楚为什么只有这一个", async () => {
    mocks.market.mockImplementation(async () => ({ plugins: [COMFY], index_error: "连不上 mosael.com:timeout" }));
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    expect(cards()).toHaveLength(1);
    expect(screen.getByText("pluginMarketIndexPartial")).toBeTruthy();
    expect(screen.getByText("连不上 mosael.com:timeout")).toBeTruthy();
  });

  it("拉不到而且一个内置的都没有:还是「打不开插件市场」,原因照说", async () => {
    mocks.market.mockImplementation(async () => ({ plugins: [], index_error: "连不上 mosael.com:timeout" }));
    renderMarket();
    expect(await screen.findByText("pluginMarketFailed")).toBeTruthy();
    expect(screen.getByText("连不上 mosael.com:timeout")).toBeTruthy();
  });
});

// 「明明装好了,还显示更新」:市场许了新版,下载地址给的还是装着的那一版。
describe("新版本还没发布", () => {
  const REMOTION = {
    id: "dev.mosael.remotion", name: "Remotion 动画", version: "0.2.0", download: "https://x/remotion.zip",
    description: "用代码做动画", permissions: ["process:spawn"], installed: true, installed_version: "0.1.0",
    update_available: true, update_unreleased: false, author: "Mosael", author_url: "", docs: "", homepage: "",
    runtime: "process", provides: [], tools: [],
  };

  it("点「更新」下下来的包并不更新:不弹「更新」确认卡,说清还没发布,市场刷新后不再说有新版", async () => {
    const user = userEvent.setup();
    let unreleased = false;
    mocks.market.mockImplementation(async () => ({
      plugins: [unreleased ? { ...REMOTION, update_available: false, update_unreleased: true } : REMOTION],
      index_error: "",
    }));
    mocks.preview.mockImplementation(async () => {
      unreleased = true; // 后端在预览时记下了这一条
      return {
        id: REMOTION.id, name: REMOTION.name, version: "0.1.0", description: "", permissions: [], tools: [],
        installed: true, installed_version: "0.1.0", update_unreleased: true,
        author_name: "Mosael", author_url: "", docs: "", homepage: "",
      };
    });
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    expect(within(card("Remotion 动画")).getByText("pluginMarketHasUpdate")).toBeTruthy();

    await user.click(within(card("Remotion 动画")).getByRole("button", { name: "pluginUpdate" }));
    expect(mocks.preview).toHaveBeenCalledWith("https://x/remotion.zip", "0.2.0");
    await waitFor(() => expect(toast.info).toHaveBeenCalledWith("pluginUpdateNotReleased"));
    expect(screen.queryByRole("dialog", { name: "pluginInstallConfirmTitle" })).toBeNull();
    expect(mocks.install).not.toHaveBeenCalled();

    //: 市场刷新:不再说「有新版」、不再给「更新」,标成已安装。
    await waitFor(() => expect(within(card("Remotion 动画")).queryByText("pluginMarketHasUpdate")).toBeNull());
    expect(within(card("Remotion 动画")).queryByRole("button", { name: "pluginUpdate" })).toBeNull();
    expect(within(card("Remotion 动画")).getByText("pluginMarketInstalledBadge")).toBeTruthy();
  });

  it("详情里说清楚为什么没有「更新」", async () => {
    const user = userEvent.setup();
    mocks.market.mockImplementation(async () => ({
      plugins: [{ ...REMOTION, update_available: false, update_unreleased: true }],
      index_error: "",
    }));
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("Remotion 动画")).getByRole("button", { name: "Remotion 动画" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("pluginUpdateNotReleased")).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "pluginUpdate" })).toBeNull();
  });

  it("有没有新版听后端的,不拿版本字符串比不相等", async () => {
    //: 装着 0.10.0、索引写 0.9.0:字符串不相等,但装着的更新 —— 后端说没有新版,就没有「更新」。
    mocks.market.mockImplementation(async () => ({
      plugins: [{ ...REMOTION, version: "0.9.0", installed_version: "0.10.0", update_available: false }],
      index_error: "",
    }));
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    expect(within(card("Remotion 动画")).queryByRole("button", { name: "pluginUpdate" })).toBeNull();
    expect(within(card("Remotion 动画")).getByText("pluginMarketInstalledBadge")).toBeTruthy();
  });
});
