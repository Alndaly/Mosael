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
const { listPluginCredentials, savePluginCredentials, invokePluginTool, listAssets, parseDocument } = vi.hoisted(() => ({
  listPluginCredentials: vi.fn(),
  savePluginCredentials: vi.fn(),
  invokePluginTool: vi.fn(),
  listAssets: vi.fn(),
  parseDocument: vi.fn(),
}));
vi.mock("@/api/client", () => ({
  listPluginCredentials,
  savePluginCredentials,
  invokePluginTool,
  listAssets,
  parseDocument,
  denoiseAsset: vi.fn(),
  separateAssetAudio: vi.fn(),
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
      pluginToolsFetchFailed: "没拿到工具清单:{error}",
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
    { id: "doc-1", name: "协议.pdf", original_filename: "d.pdf", kind: "document" },
  ]);
  parseDocument.mockReset();
  parseDocument.mockResolvedValue({ status: "parsing" });
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

  it("授权那一行是正文第一行,排在名称和凭据之前", async () => {
    const { container } = wrap(<ConnectionCard pkg={pkg} instance={instance} workspaceId="w1" />);
    const content = container.querySelector('[data-slot="settings-group-content"]') as HTMLElement;
    // 组正文的**第一项**就是它(一行设置行):名称、AppKey 都在它下面。
    const strip = content.firstElementChild as HTMLElement;
    expect(strip.getAttribute("data-slot")).toBe("settings-row");
    expect(strip.querySelector('[data-slot="plugin-authorization"]')).toBeTruthy();
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

describe("网络是宿主给每个连接的一行", () => {
  //: 走哪个代理不是插件的业务配置:清单里不写,每个连接都有,排在插件自己声明的配置与凭据之后。
  it("没声明任何网络字段的插件也有这一行,排在凭据后面,默认跟随 Mosael", async () => {
    const pkg = {
      id: "dev.mosael.mineru",
      name: "MinerU",
      version: "1.2.0",
      kind: "process",
      multiple: false,
      permissions: [],
      provides: [],
      config_fields: [],
      credential_fields: [{ key: "APP_KEY", label: "AppKey", required: true, secret: true }],
      oauth: null,
      instances: [],
    } as unknown as PluginPackage;
    const instance = {
      id: "i1",
      package_id: pkg.id,
      name: "MinerU",
      enabled: true,
      config: {},
      blocked_reason: "",
      authorization: "",
      tools: [],
      capability_status: {},
      network: { mode: "follow", proxy_url: "" },
    } as PluginInstance;
    const { container } = wrap(<ConnectionCard pkg={pkg} instance={instance} workspaceId="w1" />);
    await screen.findByPlaceholderText("APP_KEY");
    const rows = [...container.querySelectorAll('[data-slot="settings-row"]')].map((row) => row.textContent ?? "");
    const network = rows.findIndex((text) => text.includes("pluginNetwork"));
    expect(network).toBeGreaterThan(rows.findIndex((text) => text.includes("AppKey")));
    expect(rows[network]).toContain("pluginNetworkFollow");
  });
});

describe("授权会填的令牌不在凭据里", () => {
  it("凭据只列 AppKey 这类注册应用拿的;令牌归授权那一行", async () => {
    listPluginCredentials.mockResolvedValue([
      { key: "APP_KEY", label: "AppKey", help: "", secret: true, filled: true, value: "" },
      { key: "REFRESH_TOKEN", label: "Refresh Token", help: "", secret: true, filled: true, value: "" },
      { key: "ACCESS_TOKEN", label: "Access Token", help: "", secret: true, filled: false, value: "" },
    ]);
    wrap(<CredentialRows instanceId="i1" oauthFields={["REFRESH_TOKEN", "ACCESS_TOKEN"]} />);
    await screen.findByPlaceholderText("APP_KEY");
    expect(screen.queryByPlaceholderText("REFRESH_TOKEN")).toBeNull();
    expect(screen.queryByPlaceholderText("ACCESS_TOKEN")).toBeNull();
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
    // 「试一下」的值是字面量(没有 `{{…}}` 引用):素材只能从清单里挑,是标准下拉 —— Radix 的
    // Select 在 jsdom 里靠键盘开。清单到之前它是灰的(没得挑的下拉不给点开)。
    await waitFor(() => expect(within(image).getByRole("combobox")).not.toBeDisabled());
    fireEvent.keyDown(within(image).getByRole("combobox"), { key: "Enter" });
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

  it("布尔配置是开关,不是一个写着 false 的文本框;拨一下存成 true / false", () => {
    //: 用户截图:Manim 的「不限制自定义代码」清单里声明的是 boolean,界面却给了一个框、里面写着 false。
    const onChange = vi.fn();
    render(<FieldInput field={field({ type: "boolean", label: "不限制自定义代码" })} value="false" onChange={onChange} />);
    const toggle = screen.getByRole("switch", { name: "不限制自定义代码" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith("true");
  });

  it("布尔的各种写法都认:True、1 算开,空串(没填)算关", () => {
    const { rerender } = render(<FieldInput field={field({ type: "boolean", label: "开关" })} value="True" onChange={vi.fn()} />);
    expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("true");
    rerender(<FieldInput field={field({ type: "boolean", label: "开关" })} value="" onChange={vi.fn()} />);
    expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false");
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

describe("只替宿主做事的插件", () => {
  //: MinerU 这类插件认领「文档解析」,那个工具只给宿主在解析任务里调,不进工具表。此前卡片上写着
  //: 「已开启 0 / 0 个工具」「启用并授权插件后会显示可调用工具」—— 插件明明启用、授权了,读起来像坏了。
  const pkg = {
    id: "dev.mosael.mineru",
    name: "MinerU 文档解析",
    version: "1.1.0",
    kind: "process",
    multiple: false,
    permissions: [],
    provides: ["document_parse"],
    config_fields: [],
    credential_fields: [],
    oauth: null,
    instances: [],
  } as unknown as PluginPackage;
  const instance = {
    id: "m1",
    package_id: pkg.id,
    name: "MinerU 文档解析",
    enabled: true,
    config: {},
    blocked_reason: "",
    authorization: "",
    tools: [],
    host_tools: [{
      name: "mineru_parse", label: "用 MinerU 解析文档", description: "把一份文档交给 MinerU 解析成 Markdown", provides: ["document_parse"],
      //: 「用在哪」是后端从能力表现算的(ADR 0032 §4),界面照着列,不自己写一句。
      used_by: [
        { capability: "document_parse", kind: "app", label: "文档详情 → 重新解析" },
        { capability: "document_parse", kind: "workflow", label: "工作流节点「文档转 Markdown」的「解析方式」" },
        { capability: "document_parse", kind: "agent", label: "智能体工具「重新解析文档」" },
      ],
    }],
    capability_status: {},
  } as PluginInstance;

  it("说它替宿主做什么,不摆一张空的勾选表;只给 Mosael 调的工具照样列出来、写着在哪用", () => {
    wrap(<ConnectionCard pkg={pkg} instance={instance} workspaceId="w1" />);
    expect(screen.getByText("pluginHostCapabilityDesc")).toBeTruthy();
    expect(screen.queryByText("pluginExposedCount")).toBeNull();
    expect(screen.queryByText("pluginToolsNotFetched")).toBeNull();
    //: 用户截图:「mineru 这里为何还是没有工具列表」—— 它唯一的工具只给宿主调,此前整块不显示。
    const row = expandHostTool("mineru_parse");
    expect(row.textContent).toContain("用 MinerU 解析文档");
    //: 用户问「为何这个列表不是动态的」:用在哪按接口给的逐条列,页面、工作流、智能体各一条。
    const uses = [...row.querySelectorAll<HTMLElement>("[data-capability-use]")];
    expect(uses.map((one) => one.dataset.capabilityUse)).toEqual(["app", "workflow", "agent"]);
    expect(uses[1].textContent).toContain("文档转 Markdown");
    expect(row.querySelector("[data-host-tool-unused]")).toBeNull();
  });

  it("接口说没有地方用到时直说,不留一块空白", () => {
    const unused = { ...instance, host_tools: [{ ...instance.host_tools![0], used_by: [] }] };
    wrap(<ConnectionCard pkg={pkg} instance={unused as PluginInstance} workspaceId="w1" />);
    expect(expandHostTool("mineru_parse").querySelector("[data-host-tool-unused]")?.textContent).toBe("pluginHostToolUnused");
  });

  it("插件页就能试一下:只列文档,走的是文档重新解析那一条路、点名这个连接", async () => {
    wrap(<ConnectionCard pkg={pkg} instance={instance} workspaceId="w1" />);
    const trial = expandHostTool("mineru_parse").querySelector<HTMLElement>("[data-host-tool-try='document_parse']")!;
    fireEvent.click(within(trial).getByRole("button", { name: /pluginHostTryPick/ }));
    expect(await screen.findByRole("option", { name: "协议.pdf" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "海边.png" })).toBeNull();
    fireEvent.click(screen.getByRole("option", { name: "协议.pdf" }));
    fireEvent.click(within(trial).getByRole("button", { name: /pluginHostTry$/ }));
    await waitFor(() => expect(parseDocument).toHaveBeenCalledWith("doc-1", "m1"));
    expect(await within(trial).findByText("pluginHostTryParsing")).toBeTruthy();
    expect(within(trial).getByRole("button", { name: "pluginHostTryOpen" })).toBeTruthy();
  });

  it("连接还用不了时不给「试一下」—— 原因卡片抬头已经说了", () => {
    const blocked = { ...instance, blocked_reason: "还没填 MinerU 的 Token" };
    wrap(<ConnectionCard pkg={pkg} instance={blocked as PluginInstance} workspaceId="w1" />);
    //: 展开了再看:收着的行里本来就没有「试一下」,不展开这条断言什么也没验。
    const row = expandHostTool("mineru_parse");
    expect(row.querySelector("[data-capability-use]")).toBeTruthy();
    expect(row.querySelector("[data-host-tool-try]")).toBeNull();
  });

  it("和开放的工具同一种行:收着时一行名字 + 说明,左边一把锁代替勾,点开才是用在哪和试一下", () => {
    //: 用户截图:「mineru 插件的这个工具的样式为何和别的插件的工具不一样」—— 此前是一张常开的卡片,
    //: 还露着裸的工具键名。
    wrap(<ConnectionCard pkg={pkg} instance={instance} workspaceId="w1" />);
    const row = document.querySelector<HTMLElement>("[data-host-tool='mineru_parse']")!;
    const toggle = within(row).getByRole("button", { expanded: false });
    expect(toggle.textContent).toContain("用 MinerU 解析文档");
    expect(toggle.textContent).toContain("pluginHostToolBadge");
    expect(row.textContent).not.toContain("mineru_parse");
    expect(within(row).queryByRole("checkbox")).toBeNull();
    expect(row.querySelector("[data-capability-use]")).toBeNull();
    fireEvent.click(toggle);
    expect(row.querySelector("[data-capability-use]")).toBeTruthy();
  });

  function expandHostTool(name: string): HTMLElement {
    const row = document.querySelector<HTMLElement>(`[data-host-tool='${name}']`)!;
    fireEvent.click(within(row).getByRole("button", { expanded: false }));
    return row;
  }
});

describe("MCP 连接的工具表是空的", () => {
  //: 启用、授权都好了、blocked_reason 为空,工具表却是空的:此前照样写「已开启 0 / 0 个工具」
  //: 「启用并授权插件后会显示可调用工具」—— 要他去做一件已经做完的事。空的原因按连接的状态说。
  const pkg = {
    id: "dev.mcp.demo",
    name: "MCP 演示",
    version: "1.0.0",
    kind: "mcp",
    multiple: false,
    permissions: [],
    provides: [],
    config_fields: [],
    credential_fields: [],
    oauth: null,
    instances: [],
  } as unknown as PluginPackage;
  const instance = {
    id: "p1",
    package_id: pkg.id,
    name: "MCP 演示",
    enabled: true,
    config: {},
    blocked_reason: "",
    authorization: "",
    tools: [],
    capability_status: {},
  } as PluginInstance;

  it("能用但还没拿到清单:让他点「刷新工具」,不说 0 / 0", () => {
    wrap(<ConnectionCard pkg={pkg} instance={instance} workspaceId="w1" />);
    expect(screen.getAllByText("pluginToolsNotFetched").length).toBeGreaterThan(0);
    expect(screen.queryByText("pluginExposedCount")).toBeNull();
    expect(screen.getByRole("button", { name: /pluginRefreshTools/ })).toBeTruthy();
  });

  it("拉过但失败:带上原因", () => {
    const failed = { ...instance, capability_status: { tools: { error: "连接超时", tools: null, models: null, refreshed_at: null } } };
    wrap(<ConnectionCard pkg={pkg} instance={failed as PluginInstance} workspaceId="w1" />);
    expect(screen.getAllByText("没拿到工具清单:连接超时").length).toBeGreaterThan(0);
    expect(screen.queryByText("pluginToolsNotFetched")).toBeNull();
  });

  it("还不能用:说为什么不能用", () => {
    wrap(<ConnectionCard pkg={pkg} instance={{ ...instance, blocked_reason: "权限未授予" }} workspaceId="w1" />);
    expect(screen.getAllByText("权限未授予").length).toBeGreaterThan(0);
    expect(screen.queryByText("pluginToolsNotFetched")).toBeNull();
  });
});
