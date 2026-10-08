/** @vitest-environment jsdom */
/**
 * 插件市场:卡片网格 → 点开一页详情。
 *
 * 钉住的是用户会碰到的几件事:卡片上的摘要不露 markdown 标记、点名字或按回车都能看详情、
 * 返回键和 Esc 都退回网格并把焦点还给那张卡、从卡片和从详情都能装(装之前先确认权限)、
 * 搜索和筛选收窄的是卡片。随应用内置的插件(ComfyUI)搜得到、标「内置」、不给装 / 更新 / 卸载;
 * 远端索引拉不到时照样列出内置的,并说清楚为什么只有这几个。
 *
 * 详情的版式(PluginProfile):页头一枚状态、一句话简介、版本和作者;概览里能做什么一项一块、介绍长了先折起来、
 * 工具一行一个(机器名悬停看)、权限按种类分组说人话(权限码悬停看)。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const OSS = {
  id: "dev.mosael.aliyun-oss", name: "阿里云 OSS", version: "0.1.2", download: "https://x/oss.zip", sha256: "abababababababababababababababababababababababababababababababab",
  summary: "把素材传到阿里云 OSS,换回一条公网直链。",
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
  listLocalServiceInstalls: vi.fn(async () => []),
}));
//: 能力的名字和「用在哪」由后端给(ADR 0032 §4),前端不写。
vi.mock("@/api/domains/capabilities", () => ({
  listCapabilityTerms: async () => [
    { name: "public_url", label: "素材外链", used_by: [{ kind: "app", label: "生成时自动换链接" }] },
    { name: "audio_denoise", label: "降噪", used_by: [] },
    { name: "generation", label: "生成", used_by: [] },
  ],
}));
//: 下拉在 jsdom 里点不开;按能力筛只关心「给了哪几项、选了哪一项」,平铺成按钮。
vi.mock("@/components/ui/option-picker", () => ({
  OptionPicker: ({ options, onChange, value }: { options: Array<{ value: string; label: string }>; onChange: (v: string) => void; value: string }) => (
    <div data-picker="" data-value={value}>
      {options.map((one) => <button key={one.value} type="button" onClick={() => onChange(one.value)}>{one.label}</button>)}
    </div>
  ),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

import { toast } from "sonner";
import { PluginMarketDialog } from "@/features/plugins/PluginMarket";

function renderMarket(capability?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onChanged = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <PluginMarketDialog open onOpenChange={vi.fn()} onChanged={onChanged} capability={capability} />
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
    await user.click(screen.getByRole("tab", { name: "pluginMarketFilterInstalled 2" }));
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
    //: 页头:没装的标「未安装」,一句话简介摆在名字下面,版本和作者是一行事实(作者能点就是链接)。
    const hero = dialog.querySelector<HTMLElement>("[data-plugin-hero]")!;
    expect(within(hero).getByText("pluginStatusAvailable")).toBeTruthy();
    expect(within(hero).getByText(OSS.summary)).toBeTruthy();
    expect(within(hero).getByRole("link", { name: "Mosael" }).getAttribute("href")).toBe("https://mosael.com");
    expect(within(hero).getByRole("button", { name: "pluginInstall" })).toBeTruthy();
    //: 权限按种类分组说人话:联网那一组里是它连的服务;权限码挂在那一条上(悬停看),不和人话抢一行。
    const network = dialog.querySelector<HTMLElement>("[data-permission-group='network']")!;
    expect(within(network).getByText("pluginPermGroupNetwork")).toBeTruthy();
    expect(network.querySelector("[data-permission='network:oss']")?.textContent).toBe("oss");
    expect(within(dialog).queryByText("network:oss")).toBeNull();
    //: 工具一行一个,显示名在前;机器名不占一行。
    const tool = dialog.querySelector<HTMLElement>("[data-tool='oss_upload']")!;
    expect(tool.textContent).toContain("oss_upload");
    //: 它能替 Mosael 做什么:后端词表里的名字,和装上之后出现在哪。
    const provides = dialog.querySelector<HTMLElement>("[data-provides='public_url']")!;
    expect(provides.textContent).toContain("素材外链");
    expect(provides.querySelector("[data-capability-use]")?.textContent).toBe("生成时自动换链接");
    //: 版本、作者在页头说过,信息里不再说第二遍。
    expect(within(dialog).queryByText("pluginMarketVersion")).toBeNull();
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
    expect(screen.getByText("pluginPermStartPrograms")).toBeTruthy();
    expect(screen.getByText("pluginPermGroupProcess")).toBeTruthy();
  });
});

describe("安装", () => {
  it("从卡片装:先弹确认(列出权限),点了才装", async () => {
    const user = userEvent.setup();
    const { onChanged } = renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("阿里云 OSS")).getByRole("button", { name: "pluginInstall" }));
    expect(mocks.preview, "索引给的 sha256 一路交给后端核对").toHaveBeenCalledWith("https://x/oss.zip", "0.1.2", "abababababababababababababababababababababababababababababababab");
    const confirm = await screen.findByRole("dialog", { name: "pluginInstallConfirmTitle" });
    expect(confirm.querySelector("[data-permission='network:oss']")?.textContent).toBe("oss");
    expect(within(confirm).getByText("oss_upload")).toBeTruthy();
    expect(mocks.install).not.toHaveBeenCalled();
    await user.click(within(confirm).getByRole("button", { name: "pluginInstall" }));
    await waitFor(() => expect(mocks.install).toHaveBeenCalledWith("https://x/oss.zip", false, "0.1.2", "abababababababababababababababababababababababababababababababab"));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("从详情更新:确认后覆盖装", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("百度网盘")).getByRole("button", { name: "百度网盘" }));
    await user.click(screen.getByRole("button", { name: "pluginUpdate" }));
    //: 装着的再装一遍是「更新」:标题、按钮都这么说,并点明会覆盖哪一版。
    const confirm = await screen.findByRole("dialog", { name: "pluginUpdateConfirmTitle" });
    expect(within(confirm).getByText("pluginInstallOverwrite")).toBeTruthy();
    await user.click(within(confirm).getByRole("button", { name: "pluginUpdate" }));
    await waitFor(() => expect(mocks.install).toHaveBeenCalledWith("https://x/pan.zip", true, "0.5.1", ""));
  });

  it("确认卡上的版本是包里实际那一版;和市场写的不同时点明", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("百度网盘")).getByRole("button", { name: "pluginUpdate" }));
    //: 预览回的是 0.1.2(包里的清单),市场写的是 0.5.1。
    const confirm = await screen.findByRole("dialog", { name: "pluginUpdateConfirmTitle" });
    expect(within(confirm).getByText("v0.1.2")).toBeTruthy();
    expect(within(confirm).getByText("pluginInstallVersionDiffers")).toBeTruthy();
  });

  it("详情里能卸载已装的插件,要先确认", async () => {
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("MCP Sample")).getByRole("button", { name: "MCP Sample" }));
    //: 卸载收在页头的 ⋯ 里,不和常用动作贴在一起。
    expect(screen.queryByRole("button", { name: "pluginUninstall" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "pluginMore" }));
    await user.click(await screen.findByRole("menuitem", { name: "pluginUninstall" }));
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
    await user.click(screen.getByRole("tab", { name: "pluginMarketFilterInstalled 3" }));
    expect(cards().map((one) => within(one).getByRole("heading").textContent)).toContain("ComfyUI");
    await user.click(screen.getByRole("tab", { name: "pluginMarketFilterUpdates 1" }));
    expect(cards().map((one) => within(one).getByRole("heading").textContent)).toEqual(["百度网盘"]);
  });

  it("详情:说它随应用安装和更新,没有安装 / 更新 / 卸载", async () => {
    withComfy();
    const user = userEvent.setup();
    renderMarket();
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("ComfyUI")).getByRole("button", { name: "ComfyUI" }));
    const dialog = screen.getByRole("dialog");
    //: 「随应用安装和更新、卸不掉」不再是一整块提示框:是状态旁边的一条事实,全句悬停看。
    const hero = dialog.querySelector<HTMLElement>("[data-plugin-hero]")!;
    expect(within(hero).getByText("pluginBundledFact")).toBeTruthy();
    expect(within(hero).getByText("pluginMarketBundledBadge")).toBeTruthy();
    expect(dialog.querySelector("[role='note']")).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /pluginInstall|pluginUpdate|pluginUninstall|pluginMore/ })).toBeNull();
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
    expect(mocks.preview).toHaveBeenCalledWith("https://x/remotion.zip", "0.2.0", "");
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

describe("按能力筛", () => {
  it("只列市场里真有插件能做的那几项,各带条数;选一项只剩能做它的", async () => {
    renderMarket();
    const list = await screen.findByRole("list", { name: "pluginMarket" });
    const picker = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-picker]");
      if (!found) throw new Error("no picker yet");
      return found;
    });
    //: 降噪、生成在词表里,但眼前这几条都不会做 —— 不列(OSS 会做素材外链)。
    expect([...picker.querySelectorAll("button")].map((one) => one.textContent)).toEqual(["pluginMarketCapabilityAny", "素材外链 · 1"]);
    fireEvent.click(within(picker).getByRole("button", { name: "素材外链 · 1" }));
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(1));
    expect(within(list).getByText(OSS.name)).toBeTruthy();
  });

  it("从设置「能力提供方」来(带着能力打开):一打开就只看能做这件事的", async () => {
    renderMarket("public_url");
    const list = await screen.findByRole("list", { name: "pluginMarket" });
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(1));
  });
});

describe("详情的版式", () => {
  const LONG = "把一台 ComfyUI 接进 Mosael:".repeat(12);
  const TOOLS = Array.from({ length: 8 }, (_, i) => ({ name: `tool_${i}`, label: `工具 ${i}`, description: "", effects: "none" }));

  function renderWith(plugins: object[], onManage = vi.fn()) {
    mocks.market.mockImplementation(async () => ({ plugins, index_error: "" }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <PluginMarketDialog open onOpenChange={vi.fn()} onChanged={vi.fn()} onManage={onManage} />
      </QueryClientProvider>,
    );
    return onManage;
  }

  it("返回键在页头最前面(图标左边),不再单独一行;页头固定,概览在下面自己滚;弹窗标题还是「插件市场」", async () => {
    const user = userEvent.setup();
    renderWith([COMFY, OSS]);
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("ComfyUI")).getByRole("button", { name: "ComfyUI" }));
    const dialog = screen.getByRole("dialog", { name: "pluginMarket" });
    const hero = dialog.querySelector<HTMLElement>("[data-plugin-hero]")!;
    const back = within(hero).getByRole("button", { name: "pluginMarketBack" });
    expect(hero.firstElementChild?.contains(back), "返回键是页头的第一格,在图标前面").toBe(true);
    expect(document.activeElement).toBe(back);
    const modalHeader = dialog.querySelector<HTMLElement>("[data-slot='modal-header']")!;
    expect(within(modalHeader).queryByRole("button", { name: "pluginMarketBack" })).toBeNull();
    //: 页头是固定头(下面一条分隔线),概览在它下面那一块里滚。
    expect(hero.className).toContain("border-b");
    const scroll = dialog.querySelector<HTMLElement>("[data-catalog-detail-scroll]")!;
    expect(scroll.contains(hero)).toBe(false);
    expect(scroll.querySelector("[data-provides='generation']")).toBeTruthy();
    expect(dialog.querySelector<HTMLElement>("[data-slot='modal-body']")!.className).toContain("overflow-hidden");
    //: 返回:回到网格,焦点回到那张卡。
    await user.click(back);
    expect(await screen.findByRole("list", { name: "pluginMarket" })).toBeTruthy();
    expect(document.activeElement).toBe(within(card("ComfyUI")).getByRole("button", { name: "ComfyUI" }));
  });

  it("安装确认和插件页上的页头没有返回键 —— 它们不在市场的详情里", async () => {
    const user = userEvent.setup();
    renderWith([OSS]);
    await user.click(within(await screen.findByRole("article")).getByRole("button", { name: "pluginInstall" }));
    const confirm = await screen.findByRole("dialog", { name: "pluginInstallConfirmTitle" });
    expect(within(confirm).queryByRole("button", { name: "pluginMarketBack" })).toBeNull();
  });

  it("介绍长了先摆开头一截,「展开」看全文(带格式)", async () => {
    const user = userEvent.setup();
    renderWith([{ ...COMFY, description: `**粗体**${LONG}` }]);
    await user.click(within(await screen.findByRole("article")).getByRole("button", { name: "ComfyUI" }));
    const about = () => document.querySelector<HTMLElement>("[data-plugin-about]")!;
    expect(about().dataset.pluginAbout).toBe("folded");
    expect(about().textContent?.endsWith("…")).toBe(true);
    expect(about().textContent).not.toContain("**");
    const toggle = screen.getByRole("button", { name: "pluginShowMore" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await user.click(toggle);
    expect(about().dataset.pluginAbout).toBe("full");
    expect(within(about()).getByText("粗体").tagName).toBe("STRONG");
    expect(screen.getByRole("button", { name: "pluginShowLess" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("介绍短的不折,也没有「展开」", async () => {
    const user = userEvent.setup();
    renderWith([COMFY]);
    await user.click(within(await screen.findByRole("article")).getByRole("button", { name: "ComfyUI" }));
    expect(document.querySelector<HTMLElement>("[data-plugin-about]")!.dataset.pluginAbout).toBe("full");
    expect(screen.queryByRole("button", { name: "pluginShowMore" })).toBeNull();
  });

  it("工具多于六个先摆六个,「全部 N 个」看全", async () => {
    const user = userEvent.setup();
    renderWith([{ ...OSS, tools: TOOLS }]);
    await user.click(within(await screen.findByRole("article")).getByRole("button", { name: "阿里云 OSS" }));
    expect(document.querySelectorAll("[data-tool]")).toHaveLength(6);
    await user.click(screen.getByRole("button", { name: "pluginToolsAll" }));
    expect(document.querySelectorAll("[data-tool]")).toHaveLength(8);
  });

  it("装着的(含内置)给「管理」:交给插件页打开它", async () => {
    const user = userEvent.setup();
    const onManage = renderWith([COMFY, MCP]);
    await screen.findByRole("list", { name: "pluginMarket" });
    await user.click(within(card("ComfyUI")).getByRole("button", { name: "ComfyUI" }));
    await user.click(screen.getByRole("button", { name: "pluginManage" }));
    expect(onManage).toHaveBeenCalledWith(COMFY.id);
  });

  it("没装的不给「管理」,给「安装」", async () => {
    const user = userEvent.setup();
    renderWith([OSS]);
    await user.click(within(await screen.findByRole("article")).getByRole("button", { name: "阿里云 OSS" }));
    expect(screen.queryByRole("button", { name: "pluginManage" })).toBeNull();
    expect(screen.getByRole("button", { name: "pluginInstall" })).toBeTruthy();
  });

  it("有新版的:页头标「可更新」,写着装着的是哪一版", async () => {
    const user = userEvent.setup();
    renderWith([PAN]);
    await user.click(within(await screen.findByRole("article")).getByRole("button", { name: "百度网盘" }));
    const hero = document.querySelector<HTMLElement>("[data-plugin-hero]")!;
    expect(within(hero).getByText("pluginMarketHasUpdate")).toBeTruthy();
    expect(within(hero).getByText("pluginInstalled")).toBeTruthy();
    expect(within(hero).getByRole("button", { name: "pluginUpdate" })).toBeTruthy();
  });

  it("老索引没有一句话简介:卡片摆介绍(摊平),详情页头不硬凑一句", async () => {
    const user = userEvent.setup();
    renderWith([PAN]);
    const pan = await screen.findByRole("article");
    expect(pan.textContent).toContain(PAN.description);
    await user.click(within(pan).getByRole("button", { name: "百度网盘" }));
    const hero = document.querySelector<HTMLElement>("[data-plugin-hero]")!;
    expect(hero.textContent).not.toContain(PAN.description);
  });
});
