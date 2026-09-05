/** @vitest-environment jsdom */

/**
 * 插件连接页上两处靠截图才发现的毛病。两处都是**结构**问题,所以钉在这里 ——
 * 靠肉眼发现的东西,如果不留下测试,下一次还是只能靠肉眼。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/api/client", () => ({ api, invalidatePlugins: () => undefined }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      pluginCredentialsSave: "保存",
      pluginOauthStart: "去授权",
      pluginOauthHint: "点一下去登录,把授权码贴回来。",
      pluginCredentialFilled: "已填",
      pluginCredentialEmpty: "未填",
      runTool: "运行",
      pluginToolNotExposed: "这个工具没有开放",
      pluginToolMissingRequired: "还有必填参数没填",
    })[key] ?? key,
}));

import { CredentialRows, ToolRow } from "./PluginsView";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  api.mockReset();
  api.mockResolvedValue([
    { key: "APP_KEY", label: "AppKey", help: "", secret: true, filled: true, value: "" },
  ]);
});

describe("凭据组末尾的动作", () => {
  it("保存和去授权排在同一行里", async () => {
    // 此前它们是两块各自手写的 div 上下叠着:两颗按钮贴得极近、一颗带说明文字一颗没有,
    // 看着像两件互不相干的事。它们是**同一组凭据上的两个动作**。
    wrap(<CredentialRows instanceId="i1" oauth />);
    const authorize = await screen.findByRole("button", { name: "去授权" });

    // 制造"改过一格"的状态,保存按钮才会出现。凭据行是查询结果渲染的,要等它到。
    const input = await screen.findByPlaceholderText("APP_KEY");
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(input, { target: { value: "abc" } });

    const save = await screen.findByRole("button", { name: "保存" });
    // 同一个动作行:找它们最近的共同祖先,它必须只包着这两颗按钮那一组。
    const row = authorize.closest("div.flex.flex-wrap") as HTMLElement;
    expect(row).not.toBeNull();
    expect(within(row).getByRole("button", { name: "保存" })).toBe(save);
    // 主动作在最右:两颗按钮在 DOM 里的先后就是视觉上的左右。
    const buttons = within(row).getAllByRole("button");
    expect(buttons.at(-1)).toBe(save);
  });

  it("没有授权能力时保存按钮自己占一行，用同一套内距", async () => {
    wrap(<CredentialRows instanceId="i2" oauth={false} />);
    const input = await screen.findByPlaceholderText("APP_KEY");
    const { fireEvent } = await import("@testing-library/react");
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
    exposed: true,
    input_schema: { type: "object", properties: {} },
  };

  it("整个连接没启用时，理由摆在按钮旁边", async () => {
    // 「未启用」这句话原本只写在整组的标题下,而工具行可能在它下面好几百像素处 ——
    // 用户看到的就只是一个灰按钮,试不出所以然。
    wrap(<ToolRow instanceId="i1" tool={tool} blockedReason="未启用" onToggle={() => undefined} />);
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByText("Pan list"));

    const run = await screen.findByRole("button", { name: /运行/ });
    expect(run).toBeDisabled();
    expect(screen.getByText("未启用")).toBeTruthy();
  });

  it("能跑的时候不摆任何理由", async () => {
    wrap(<ToolRow instanceId="i1" tool={tool} blockedReason="" onToggle={() => undefined} />);
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByText("Pan list"));

    const run = await screen.findByRole("button", { name: /运行/ });
    expect(run).not.toBeDisabled();
    expect(screen.queryByText("未启用")).toBeNull();
  });
});
