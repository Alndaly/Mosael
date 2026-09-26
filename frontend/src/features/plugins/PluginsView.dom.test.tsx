/** @vitest-environment jsdom */

/**
 * 插件连接页上两处靠截图才发现的毛病。两处都是**结构**问题,所以钉在这里 ——
 * 靠肉眼发现的东西,如果不留下测试,下一次还是只能靠肉眼。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

//: 路径在 api/domains/plugins 里,界面调的是**有名字的函数** —— 所以这里打桩的也是它们,
//: 断言的是"带着哪个连接、哪个工具、哪些参数",而不是一串拼出来的 URL。
const { listPluginCredentials, savePluginCredentials, invokePluginTool, listAssets } = vi.hoisted(() => ({
  listPluginCredentials: vi.fn(),
  savePluginCredentials: vi.fn(),
  invokePluginTool: vi.fn(),
  listAssets: vi.fn(),
}));
vi.mock("@/api/client", () => ({
  listPluginCredentials,
  savePluginCredentials,
  invokePluginTool,
  listAssets,
  fetchWorkflowFieldOptions: vi.fn().mockResolvedValue([]),
  startPluginOauth: vi.fn(),
  finishPluginOauth: vi.fn(),
  listPluginInvocations: vi.fn().mockResolvedValue([]),
  listPluginPermissions: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      pluginCredentialsSave: "保存",
      pluginOauthStart: "去授权",
      pluginAuthUnauthorized: "未授权",
      pluginConnectionName: "名称",
      pluginOauthTokens: "授权令牌",
      pluginOauthManual: "手动填写",
      pluginOauthManualHide: "收起",
      pluginCredentialFilled: "已填",
      pluginCredentialEmpty: "未填",
      runTool: "运行",
      pluginToolNotExposed: "这个工具没有开放",
      pluginToolMissingRequired: "还有必填参数没填",
    })[key] ?? key,
}));

import { ConnectionCard, CredentialRows, FieldInput, ToolRow } from "./PluginsView";
import type { PluginInstance, PluginPackage } from "@/api/client";
import { composeWithIme, watchValueWrites } from "@/test/ime";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    ...render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> }),
    client,
  };
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.assign(Element.prototype, { hasPointerCapture: () => false, setPointerCapture: () => {}, releasePointerCapture: () => {} });
  listPluginCredentials.mockReset();
  listAssets.mockReset();
  listAssets.mockResolvedValue([
    { id: "img-1", name: "海边.png", original_filename: "a.png", kind: "image" },
    { id: "img-2", name: "山.png", original_filename: "b.png", kind: "image" },
    { id: "vid-1", name: "成片.mp4", original_filename: "c.mp4", kind: "video" },
  ]);
  savePluginCredentials.mockReset();
  invokePluginTool.mockReset();
  listPluginCredentials.mockResolvedValue([
    { key: "APP_KEY", label: "AppKey", help: "", secret: true, filled: true, value: "" },
  ]);
});

describe("授权是连接级别的", () => {
  //: 此前「去授权」是凭据组最后一行里的一颗按钮,排在 Access Token 下面:读起来像那一格的附属操作,
  //: 也看不出这个连接到底授权过没有。它写的是**这个连接**的令牌,所以归连接,摆在卡片抬头正下方。
  const pkg = {
    id: "dev.mosael.baidu-pan",
    name: "百度网盘",
    version: "0.7.0",
    kind: "process",
    multiple: true,
    permissions: [],
    provides: [],
    config_fields: [],
    credential_fields: [
      { key: "APP_KEY", label: "AppKey", required: true, secret: true },
      { key: "REFRESH_TOKEN", label: "Refresh Token", required: true, secret: true },
    ],
    oauth: { fills: ["REFRESH_TOKEN"] },
    instances: [],
  } as unknown as PluginPackage;
  const instance = {
    id: "i1",
    package_id: pkg.id,
    name: "百度网盘",
    enabled: true,
    config: {},
    blocked_reason: "",
    authorization: "unauthorized",
    tools: [],
    capability_status: {},
  } as PluginInstance;

  it("授权那一条紧跟卡片抬头,排在名称和凭据之前", async () => {
    const { container } = wrap(<ConnectionCard pkg={pkg} instance={instance} workspaceId="w1" />);
    const content = container.querySelector('[data-slot="settings-group-content"]') as HTMLElement;
    const strip = content.querySelector('[data-slot="plugin-authorization"]') as HTMLElement;
    // 组正文的**第一项**就是它:名称、AppKey 都在它下面。
    expect(content.firstElementChild).toBe(strip);
    expect(within(strip).getByText("未授权")).toBeTruthy();
    expect(within(strip).getByRole("button", { name: "去授权" })).toBeTruthy();
    // 全卡片只有这一颗「去授权」—— 凭据组末尾不再另长一颗。
    await screen.findByPlaceholderText("APP_KEY");
    expect(screen.getAllByRole("button", { name: "去授权" })).toHaveLength(1);
  });

  it("没声明授权的插件不长这一条", () => {
    const plain = { ...pkg, oauth: null } as unknown as PluginPackage;
    const { container } = wrap(<ConnectionCard pkg={plain} instance={{ ...instance, authorization: "" }} workspaceId="w1" />);
    expect(container.querySelector('[data-slot="plugin-authorization"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "去授权" })).toBeNull();
  });
});

describe("授权会填的令牌不当主输入", () => {
  beforeEach(() => {
    listPluginCredentials.mockResolvedValue([
      { key: "APP_KEY", label: "AppKey", help: "", secret: true, filled: true, value: "" },
      { key: "REFRESH_TOKEN", label: "Refresh Token", help: "", secret: true, filled: true, value: "" },
      { key: "ACCESS_TOKEN", label: "Access Token", help: "", secret: true, filled: false, value: "" },
    ]);
  });

  it("平时收起,只说填没填;展开之后照样能手动改、能保存", async () => {
    wrap(<CredentialRows instanceId="i1" oauthFields={["REFRESH_TOKEN", "ACCESS_TOKEN"]} />);
    // AppKey 是注册应用拿的,授权替代不了 —— 它仍是主输入。
    await screen.findByPlaceholderText("APP_KEY");
    expect(screen.queryByPlaceholderText("REFRESH_TOKEN")).toBeNull();
    expect(screen.queryByPlaceholderText("ACCESS_TOKEN")).toBeNull();
    expect(screen.getByText("授权令牌")).toBeTruthy();
    expect(screen.getByText("Refresh Token · 已填")).toBeTruthy();
    expect(screen.getByText("Access Token · 未填")).toBeTruthy();

    const toggle = screen.getByRole("button", { name: "手动填写" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "收起" }).getAttribute("aria-expanded")).toBe("true");

    fireEvent.change(screen.getByPlaceholderText("REFRESH_TOKEN"), { target: { value: "r-by-hand" } });
    savePluginCredentials.mockResolvedValue([]);
    fireEvent.click(await screen.findByRole("button", { name: "保存" }));
    await waitFor(() => expect(savePluginCredentials).toHaveBeenCalledWith("i1", { REFRESH_TOKEN: "r-by-hand" }));
  });

  it("展开的令牌行直接排在组里,不包一层(组的分隔线只认这一层)", async () => {
    const { container } = wrap(
      <div data-testid="group">
        <CredentialRows instanceId="i1" oauthFields={["REFRESH_TOKEN", "ACCESS_TOKEN"]} />
      </div>,
    );
    await screen.findByPlaceholderText("APP_KEY");
    fireEvent.click(screen.getByRole("button", { name: "手动填写" }));
    const group = container.querySelector('[data-testid="group"]') as HTMLElement;
    const rows = Array.from(group.children).map((child) => child.getAttribute("data-slot"));
    // AppKey、「授权令牌」、Refresh Token、Access Token:四行并排,都是组的直接子项。
    expect(rows).toEqual(["settings-row", "settings-row", "settings-row", "settings-row"]);
  });
});

describe("凭据组末尾的动作", () => {
  it("保存按钮自己占一行，用同一套内距", async () => {
    wrap(<CredentialRows instanceId="i2" oauthFields={[]} />);
    const input = await screen.findByPlaceholderText("APP_KEY");
    fireEvent.change(input, { target: { value: "abc" } });

    const save = await screen.findByRole("button", { name: "保存" });
    const row = save.closest("div.flex.flex-wrap") as HTMLElement;
    // 和行一样的 px-0.5 py-3。**上下对称**是这条测试的重点:此前是 pt-2 / pb-1,
    // 上 8 下 4,于是"下面那道缝比上面窄"。
    expect(row.className).toContain("px-0.5");
    expect(row.className).toContain("py-3");
    expect(row.className).not.toMatch(/\bpt-\d/);
    expect(row.className).not.toMatch(/\bpb-\d/);
  });
});

describe("灰着的运行按钮要说明自己为什么灰", () => {
  const tool = {
    name: "pan_list",
    label: "Pan list",
    description: "列目录",
    read_only: true,
    effects: "none",
    exposed: true,
    input_schema: { type: "object", properties: {} },
  };

  it("整个连接没启用时，理由摆在按钮旁边", async () => {
    // 「未启用」这句话原本只写在整组的标题下,而工具行可能在它下面好几百像素处 ——
    // 用户看到的就只是一个灰按钮,试不出所以然。
    wrap(<ToolRow workspaceId="workspace-a" instanceId="i1" tool={tool} blockedReason="未启用" onToggle={() => undefined} />);
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByText("Pan list"));

    const run = await screen.findByRole("button", { name: /运行/ });
    expect(run).toBeDisabled();
    expect(screen.getByText("未启用")).toBeTruthy();
  });

  it("能跑的时候不摆任何理由", async () => {
    wrap(<ToolRow workspaceId="workspace-a" instanceId="i1" tool={tool} blockedReason="" onToggle={() => undefined} />);
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByText("Pan list"));

    const run = await screen.findByRole("button", { name: /运行/ });
    expect(run).not.toBeDisabled();
    expect(screen.queryByText("未启用")).toBeNull();
  });
});

describe("智能体调用前要确认的工具标「需确认」", () => {
  const base = { name: "manim_still", label: "Manim 静帧", description: "", read_only: false, exposed: true, input_schema: {} };

  it("有后果的标出来,悬停说清是哪一种", () => {
    wrap(<ToolRow workspaceId="w" instanceId="i1" tool={{ ...base, effects: "local-code" }} blockedReason="" onToggle={() => undefined} />);
    const badge = screen.getByText("pluginToolNeedsConfirm");
    expect(badge.getAttribute("title")).toBe("pluginToolEffectLocalCode");
  });

  it("none 的不标 —— 不问人就不说要问", () => {
    wrap(<ToolRow workspaceId="w" instanceId="i1" tool={{ ...base, effects: "none" }} blockedReason="" onToggle={() => undefined} />);
    expect(screen.queryByText("pluginToolNeedsConfirm")).toBeNull();
  });
});

describe("素材工具的工作区归属", () => {
  it.each([
    { name: "pan_import", input: { fs_id: "230120330866997" }, output: { asset_id: "imported-asset" } },
    { name: "pan_upload", input: { asset_id: "source-asset", path: "/成片.mp4" }, output: { fs_id: "uploaded-file" } },
  ])("$name 将当前工作区与工具参数分开传递", async ({ name, input, output }) => {
    const tool = {
      name, label: name, description: "", read_only: false, effects: name === "pan_upload" ? "external" : "none", exposed: true,
      input_schema: { properties: Object.fromEntries(Object.keys(input).map((key) => [key, { type: "string" }])) },
      form: Object.fromEntries(Object.keys(input).map((key) => [key, { type: "string", label: key }])),
    };
    invokePluginTool.mockResolvedValue({ id: "invocation", status: "succeeded", output });
    const props = { instanceId: "i1", tool, blockedReason: "", onToggle: () => undefined };
    const { client, rerender } = wrap(<ToolRow {...props} workspaceId="workspace-a" />);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    fireEvent.click(screen.getByText(name));
    for (const [key, value] of Object.entries(input)) {
      fireEvent.change(fieldInput(key), { target: { value } });
    }
    fireEvent.click(screen.getByRole("button", { name: "运行" }));
    await waitFor(() => expect(invokePluginTool).toHaveBeenCalledWith("i1", name, { input, workspace_id: "workspace-a" }));
    if (name === "pan_import") {
      await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["assets", "workspace-a"] }));
    }
    await waitFor(() => expect(screen.getByRole("button", { name: "运行" })).not.toBeDisabled());

    rerender(<ToolRow {...props} workspaceId="workspace-b" />);
    fireEvent.click(screen.getByRole("button", { name: "运行" }));
    await waitFor(() => expect(invokePluginTool).toHaveBeenLastCalledWith("i1", name, { input, workspace_id: "workspace-b" }));
  });
});

/** 表单里某一格的输入框。表单是节点表单(NodeConfigForm),每一格带着 data-field-key。 */
function fieldInput(key: string): HTMLInputElement {
  return document.querySelector<HTMLInputElement>(`[data-field-key="${key}"] input`)!;
}

describe("试跑表单就是工作流节点的那张表单", () => {
  //: 形状和后端 `_tool_form` 发下来的一样(节点目录的字段声明,已按语言翻好)
  const tool = {
    name: "wf_portrait", label: "工作流 · portrait", description: "", read_only: false, effects: "paid", exposed: true,
    input_schema: { properties: {} },
    form: {
      steps_3: { type: "number", label: "步数", default: "20", description: "采样 · steps" },
      image_10: { type: "template", label: "图", data_type: "asset", media: "image", required: true },
      images: { type: "asset_list", label: "更多的图", data_type: "asset", media: "image" },
      include_previews: { type: "template", label: "也取回预览", advanced: true, options: ["true", "false"],
                          option_labels: { true: "是", false: "否" } },
    },
  };

  it("人话标签、默认值当占位、素材选择器只列那一种素材、一串素材不是 JSON 框、高级项收起来", async () => {
    invokePluginTool.mockResolvedValue({ id: "invocation", status: "succeeded", output: {} });
    wrap(<ToolRow workspaceId="workspace-a" instanceId="i1" tool={tool} blockedReason="" onToggle={() => undefined} />);
    fireEvent.click(screen.getByText("工作流 · portrait"));

    const steps = document.querySelector<HTMLElement>('[data-field-key="steps_3"]')!;
    expect(within(steps).getByText("步数")).toBeTruthy();
    expect(fieldInput("steps_3").placeholder).toBe("20");
    expect(document.body.textContent).not.toContain("string");
    expect(document.querySelector("textarea")).toBeNull();
    expect(document.querySelector('[data-field-key="include_previews"]')).toBeNull();
    // 必填的图没挑:按钮灰着,旁边说为什么
    expect(screen.getByRole("button", { name: /运行/ })).toBeDisabled();
    expect(screen.getByText("还有必填参数没填")).toBeTruthy();

    const image = document.querySelector<HTMLElement>('[data-field-key="image_10"]')!;
    fireEvent.click(within(image).getByRole("combobox"));
    expect(await screen.findByRole("option", { name: "海边.png" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "成片.mp4" })).toBeNull();
    fireEvent.click(screen.getByRole("option", { name: "海边.png" }));

    const images = document.querySelector<HTMLElement>('[data-field-key="images"]')!;
    for (const name of ["山.png", "海边.png"]) {
      fireEvent.click(within(images).getByRole("combobox"));
      fireEvent.click(await screen.findByRole("option", { name }));
    }
    expect(within(images).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["山.png", "海边.png"]);
    fireEvent.change(fieldInput("steps_3"), { target: { value: "30" } });

    fireEvent.click(screen.getByRole("button", { name: /wfAdvanced/ }));
    expect(document.querySelector('[data-field-key="include_previews"]')).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /运行/ }));
    await waitFor(() => expect(invokePluginTool).toHaveBeenCalledWith("i1", "wf_portrait", {
      input: { image_10: "img-1", images: ["img-2", "img-1"], steps_3: "30" },
      workspace_id: "workspace-a",
    }));
  });
});

describe("配置字段的控件", () => {
  const field = (over: Partial<Record<string, unknown>> = {}) =>
    ({ key: "K", label: "标签", type: "string", help: "", required: true, secret: false, options: [], default: "", ...over }) as never;

  it("只有一个选项的枚举不给下拉 —— 它是钉死的值", () => {
    // Blender 插件的「关闭上游遥测」就是这样:清单里只声明了一个选项。渲染成下拉等于摆一个
    // 点开只有一项的控件,看起来能操作、实际不能。
    render(
      <FieldInput
        field={field({ type: "enum", label: "关闭上游遥测", options: [{ value: "true", label: "已关闭" }] })}
        value="true"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("已关闭")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("两个及以上选项才给下拉", () => {
    render(
      <FieldInput
        field={field({
          type: "enum",
          label: "Blender 主机",
          options: [{ value: "127.0.0.1", label: "127.0.0.1" }, { value: "localhost", label: "localhost" }],
        })}
        value="127.0.0.1"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button")).toBeTruthy();
  });

  it("改动能传出去", () => {
    const onChange = vi.fn();
    render(<FieldInput field={field({ label: "连接端口" })} value="9876" onChange={onChange} />);
    fireEvent.change(screen.getByDisplayValue("9876"), { target: { value: "9877" } });
    expect(onChange).toHaveBeenCalledWith("9877");
  });

  //: 连接上的配置住在服务端:value 要等请求回来才变。此前每敲一个字就发一次 PATCH,
  //: 回来之前框里的字还被 React 写回旧值 —— 英文丢字,中文组词当场断掉。
  it("改的是服务端那份时:框里的字不被写回旧值,离开时只交一次", () => {
    const onChange = vi.fn();
    render(<FieldInput field={field({ label: "连接名" })} value="旧的" commit="blur" onChange={onChange} />);
    const box = screen.getByDisplayValue("旧的") as HTMLInputElement;
    box.focus();
    fireEvent.change(box, { target: { value: "旧的1" } });
    fireEvent.change(box, { target: { value: "旧的12" } });
    expect(box.value).toBe("旧的12");
    expect(onChange).not.toHaveBeenCalled();
    const writes = watchValueWrites(box);
    composeWithIme(box, ["旧的12x", "旧的12xi", "旧的12xin"], "旧的12新");
    expect(writes).toEqual([]);
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("旧的12新");
  });
});

describe("清单里的说明带 markdown", () => {
  // 对象存储插件的工具说明写着「交回一条**限时直链**」—— 此前工具行上原样露着两对星号。
  it("工具说明和参数说明渲染成格式,不露记号", () => {
    const tool = {
      name: "oss_upload",
      label: "上传",
      description: "交回一条**限时直链**",
      read_only: false,
      effects: "external",
      exposed: true,
      input_schema: { properties: { key: { type: "string", description: "对象键,如 `videos/a.mp4`" } } },
      form: { key: { type: "template", label: "对象键", description: "对象键,如 `videos/a.mp4`" } },
    };
    const { container } = wrap(<ToolRow workspaceId="w1" instanceId="i1" tool={tool} blockedReason="" onToggle={() => undefined} />);
    expect(screen.getByText("限时直链").tagName).toBe("STRONG");
    // 说明在展开按钮里:不能再套一个链接进去。
    expect(container.querySelector("button a")).toBeNull();
    fireEvent.click(screen.getByText("上传"));
    expect(screen.getByText("videos/a.mp4").tagName).toBe("CODE");
    expect(container.textContent).not.toMatch(/\*\*|`/);
  });

  it("凭据的帮助文字同样", async () => {
    listPluginCredentials.mockResolvedValue([
      { key: "AK", label: "AccessKey", help: "在**控制台**的 `AccessKey 管理` 里创建", secret: true, filled: false, value: "" },
    ]);
    const { container } = wrap(<CredentialRows instanceId="i1" oauthFields={[]} />);
    expect((await screen.findByText("控制台")).tagName).toBe("STRONG");
    expect(screen.getByText("AccessKey 管理").tagName).toBe("CODE");
    expect(container.textContent).not.toMatch(/\*\*|`/);
  });
});
