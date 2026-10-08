/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 「一条连接都没有」和「没问出来」是两回事,这一屏必须分得清。
 *
 * 用户撞到的:AI 对话那一页只有一条空灰条 —— 没有列表、没有"还没有连接"、也没有任何错误。
 * 原因是空状态挂在 `profiles.data && ...` 后面:请求失败(401、后端没起、网络断)时 `data` 是
 * undefined,那一行被短路掉,而外层容器照画 —— 于是失败长得和"空"一模一样,而"空"又长得像
 * 什么都没发生。用户看到的是"明明实际是有的,为什么这里空的"。
 *
 * 三种状态三种样子:**在问**(骨架/一句话)、**没问出来**(说清楚,并给重试)、**问出来是空的**
 * (空状态 + 下一步)。
 */

const TEMPLATES: Record<string, string> = {
  providerNoProfiles: "还没有连接",
  providerNoCapabilityProfiles: "这项能力还没有连接",
  providerLoadFailed: "没能读取你的连接",
  retry: "重试",
  connecting: "连接中…",
};

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEMPLATES[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

let providersResult: unknown = [];
let vendorsResult: unknown = [];
const apiCalls: Array<{ path: string; init?: { method?: string; body?: string } }> = [];

//: 替身落在 transport 上:api/domains/providers 的函数和组件里残留的直接调用都经过它。
vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: async (path: string, init?: { method?: string; body?: string }) => {
    apiCalls.push({ path, init });
    if (path.includes("/members")) return { my_role: "owner", members: [] };
    if (path.includes("/models")) return [];
    if (path.startsWith("/api/settings/providers")) {
      if (providersResult instanceof Error) throw providersResult;
      return providersResult;
    }
    if (path.startsWith("/api/settings/provider-vendors")) return vendorsResult;
    return [];
  },
}));

import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";

function renderSection(capability = "chat") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProviderProfilesSection capability={capability} />
    </QueryClientProvider>,
  );
}

describe("供应商连接列表", () => {
  it("问出来是空的 → 说「还没有连接」", async () => {
    providersResult = [];
    const { container } = renderSection();

    await waitFor(() => expect(container.textContent).toContain(TEMPLATES.providerNoCapabilityProfiles));
  });

  it("没问出来 → 说清楚,并且给一条出路", async () => {
    // 这正是用户撞到的那一屏:此前它和"空"长得一模一样 —— 一条什么都没有的灰条。
    providersResult = new Error("401 未登录");
    const { container } = renderSection();

    await waitFor(() => expect(container.textContent).toContain(TEMPLATES.providerLoadFailed));
    expect(container.textContent).not.toContain(TEMPLATES.providerNoCapabilityProfiles);
    expect(screen.getByText(TEMPLATES.retry)).toBeTruthy();
  });

  it("失败时把后端说的话原样带上 —— 「没能读取」本身不足以让人知道下一步", async () => {
    providersResult = new Error("连接被拒绝:后端没有在 127.0.0.1:8800 上");
    const { container } = renderSection();

    await waitFor(() => expect(container.textContent).toContain("连接被拒绝"));
  });

  it("编辑连接时不再显示只用于创建的初始模型字段", async () => {
    const user = userEvent.setup();
    vendorsResult = [{
      vendor: "alibaba",
      label: "阿里云百炼",
      capability_ids: ["chat", "image", "video", "tts"],
      capabilities: "多能力供应商",
      auth: ["api_key"],
      fields: [
        { key: "base_url", label: "百炼 API Endpoint", storage: "base_url", required: false, secret: false },
        { key: "default_model", label: "初始模型(可选)", storage: "default_model", required: false, secret: false },
      ],
    }];
    providersResult = [{
      id: "p1",
      name: "百炼",
      vendor: "alibaba",
      enabled: true,
      auth_type: "api_key",
      oauth_linked: false,
      capability_ids: ["chat"],
      config: { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", default_model: "qwen-plus" },
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      quota_supported: false,
    }];
    renderSection();

    await user.click(await screen.findByRole("button", { name: "more" }));
    await user.click(await screen.findByText("providerEdit"));

    expect(await screen.findByText("百炼 API Endpoint")).toBeInTheDocument();
    expect(screen.queryByText("初始模型(可选)")).not.toBeInTheDocument();
  });

  it("在对话分区加 Google:说明 Gemini 的对话在哪能用;视频分区不说这句", async () => {
    /* Gemini(以及订阅授权那几家)的对话走 pi 的原生协议,字幕翻译这类直连调用不走它 —— 不说的话,配好之后在翻译里
       找不到它,人会以为配错了。在视频分区加 Google 的人是来配 Veo 的,这句话对他是噪音。 */
    const user = userEvent.setup();
    vendorsResult = [{
      vendor: "google",
      label: "Google AI Studio(Gemini / Veo / Lyria)",
      capability_ids: ["chat", "video", "audio"],
      capabilities: "对话(Gemini)、视频生成(Veo)与音乐生成。Gemini 订阅(Google AI Pro/Ultra)不能给第三方用,这里填 AI Studio 的 API Key。",
      auth: ["api_key"],
      native_chat: true,
      fields: [{ key: "api_key", label: "Gemini API Key", storage: "api_key", required: true, secret: true }],
    }];
    providersResult = [];

    const chat = renderSection("chat");
    await user.click(await screen.findByText("providerAdd"));
    expect(await screen.findByText("Gemini API Key")).toBeInTheDocument();
    expect(screen.getByText(/Google AI Pro\/Ultra/)).toBeInTheDocument();
    expect(screen.getByText("providerNativeChatHint")).toBeInTheDocument();
    chat.unmount();

    renderSection("video");
    await user.click(await screen.findByText("providerAdd"));
    expect(await screen.findByText("Gemini API Key")).toBeInTheDocument();
    expect(screen.queryByText("providerNativeChatHint")).not.toBeInTheDocument();
  });

  it("模型列表的动作收口在连接的溢出菜单里;参数组不在这 —— 它的入口在绑定的地方", async () => {
    /* 列表底下的常驻输入框和浮在右上角的「选择」都撤掉了 —— 入口统一在 ⋯ 菜单,
       同一样式。参数组的管理入口在「参数按什么来」选择器里(见 ModelSettingsDialog),
       挑参数来源时才发现缺一份的人,不该回这里翻菜单。 */
    const user = userEvent.setup();
    vendorsResult = [];
    providersResult = [{
      id: "p1",
      name: "中转",
      vendor: "openai-compatible",
      enabled: true,
      auth_type: "api_key",
      oauth_linked: false,
      capability_ids: ["chat", "image"],
      config: { base_url: "https://x.example/v1" },
      base_url: "https://x.example/v1",
      quota_supported: false,
    }];

    renderSection("image");
    await user.click(await screen.findByRole("button", { name: "more" }));
    /* 断言限定在弹出的菜单里:连接列表自己也有一个「选择」(批量删连接),同文案不同作用域。 */
    const menu = await screen.findByText("modelAddEntry");
    const menuScope = within(menu.closest("[data-radix-popper-content-wrapper]") as HTMLElement);
    expect(menuScope.getByText("bulkSelect")).toBeInTheDocument();
    expect(menuScope.queryByText("generationProfiles")).not.toBeInTheDocument();

    /* 点完任意一项,菜单自己要关上 —— 此前只有 onSelect,菜单一直挂着,
       「选择」这种不开对话框的动作,菜单就明晃晃地挡在列表前面。 */
    await user.click(menuScope.getByText("bulkSelect"));
    await waitFor(() =>
      expect(screen.queryByText("modelAddEntry")).not.toBeInTheDocument(),
    );
  });

  it("添加模型是「先挑后确认」:选择只是挑选,点「加入」才 POST,取消什么都不发生", async () => {
    /* 选中即提交那版,挑错一个目录项就多发一次请求,而撤销要再去删一行。
       cmdk 在挂载时要 ResizeObserver,jsdom 没有。 */
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
    const user = userEvent.setup();
    vendorsResult = [];
    providersResult = [{
      id: "p1",
      name: "中转",
      vendor: "openai-compatible",
      enabled: true,
      auth_type: "api_key",
      oauth_linked: false,
      capability_ids: ["chat", "image"],
      config: { base_url: "https://x.example/v1" },
      base_url: "https://x.example/v1",
      quota_supported: false,
    }];
    apiCalls.length = 0;
    const posts = () => apiCalls.filter((call) => call.init?.method === "POST");

    renderSection("image");
    await user.click(await screen.findByRole("button", { name: "more" }));
    await user.click(await screen.findByText("modelAddEntry"));

    /* 第一趟:挑了,但取消 —— 不该有任何 POST。 */
    await user.click(await screen.findByRole("combobox"));
    await user.type(document.querySelector("[cmdk-input]") as HTMLElement, "my-model-x");
    await user.click(await screen.findByText("modelAddCustom"));
    expect(posts()).toHaveLength(0);
    await user.click(screen.getByText("cancel"));
    expect(posts()).toHaveLength(0);

    /* 第二趟:挑了同一个,点「加入」才落。 */
    await user.click(await screen.findByRole("button", { name: "more" }));
    await user.click(await screen.findByText("modelAddEntry"));
    await user.click(await screen.findByRole("combobox"));
    await user.type(document.querySelector("[cmdk-input]") as HTMLElement, "my-model-x");
    await user.click(await screen.findByText("modelAddCustom"));
    expect(posts()).toHaveLength(0);
    await user.click(screen.getByText("modelAdd"));

    expect(posts()).toHaveLength(1);
    expect(posts()[0].path).toBe("/api/settings/providers/p1/models");
    expect(JSON.parse(posts()[0].init!.body!)).toEqual({ model_id: "my-model-x", enabled: true });
  });

  it("停用的那一行和启用的那一行,右端占的格子一样多", async () => {
    /* 用户看到的:停用之后右侧那几个图标整体错开了一格。「已停用」徽标自己占了一条网格轨道,
       而它只在停用时渲染 —— 启用的行末列是空的,宽度 0,gap 却照算。
       判据是**两种行的直接子元素数目相同**:条件出现的东西不能自己占一条轨道。
       (jsdom 量不到版面,而"错开一格"的成因正是这个数目差。) */
    vendorsResult = [];
    providersResult = [
      { id: "on", name: "开着的", vendor: "openai-compatible", enabled: true, auth_type: "api_key",
        oauth_linked: false, capability_ids: ["chat"], config: {}, base_url: "http://a" },
      { id: "off", name: "停用的", vendor: "openai-compatible", enabled: false, auth_type: "api_key",
        oauth_linked: false, capability_ids: ["chat"], config: {}, base_url: "http://b" },
    ];
    const { container } = renderSection();

    await waitFor(() => expect(container.textContent).toContain("停用的"));
    const rows = [...container.querySelectorAll("[data-slot='settings-list-item']")];
    expect(rows).toHaveLength(2);
    expect(rows[1].children.length).toBe(rows[0].children.length);
    //: 徽标确实还在,只是和那几个按钮同处一格。
    expect(rows[1].textContent).toContain("providerDisabled");
  });
});

//: 体检 UM-23:「未授权」「未配置你的密钥」此前是纯文字,授权登录要点「更多」才找得到;缺密钥的连接旁边亮着绿色的延迟。
describe("连接用不了时直接点状态去修", () => {
  it("「未配置你的密钥」点了就是编辑这条连接(填密钥);地址通也不亮成功色", async () => {
    const user = userEvent.setup();
    vendorsResult = [{ vendor: "alibaba", label: "阿里云百炼", capability_ids: ["chat"], capabilities: "", auth: ["api_key"],
      fields: [{ key: "base_url", label: "百炼 API Endpoint", storage: "base_url", required: false, secret: false }] }];
    providersResult = [{ id: "p1", name: "百炼", vendor: "alibaba", enabled: true, auth_type: "api_key", oauth_linked: false, key_hint: "",
      capability_ids: ["chat"], config: { base_url: "https://x" }, base_url: "https://x", quota_supported: false }];
    renderSection();
    await user.click(await screen.findByRole("button", { name: "providerNoKeyOfMine" }));
    expect(await screen.findByText("百炼 API Endpoint")).toBeInTheDocument();
  });

  it("「未授权」点了就是去授权", async () => {
    const user = userEvent.setup();
    vendorsResult = [{ vendor: "kimi", label: "Kimi", capability_ids: ["chat"], capabilities: "", auth: ["oauth"], fields: [] }];
    providersResult = [{ id: "p2", name: "Kimi", vendor: "kimi", enabled: true, auth_type: "oauth", oauth_linked: false, key_hint: "",
      capability_ids: ["chat"], config: {}, base_url: "", quota_supported: false }];
    renderSection();
    await user.click(await screen.findByRole("button", { name: "providerOauthUnlinked" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
