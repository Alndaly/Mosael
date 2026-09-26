/** @vitest-environment jsdom */

/**
 * 连接上的授权那一条:看得出授权到哪一步,按钮跟着状态说话,贴授权码就在同一条里。
 *
 * 状态由后端算(授权会写的那几格填没填、插件上一次有没有说对方不认了),这里钉的是「每种状态
 * 长什么样」以及那段贴码的流程 —— 此前界面上只有一颗永远写着「去授权」的按钮,授权过没有看不出来。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { startPluginOauth, finishPluginOauth } = vi.hoisted(() => ({
  startPluginOauth: vi.fn(),
  finishPluginOauth: vi.fn(),
}));
vi.mock("@/api/client", () => ({ startPluginOauth, finishPluginOauth }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      pluginAuthTitle: "授权",
      pluginAuthUnauthorized: "未授权",
      pluginAuthAuthorized: "已授权",
      pluginAuthRejected: "需要重新授权",
      pluginAuthHintUnauthorized: "填好应用凭据后点「去授权」。",
      pluginAuthHintAuthorized: "令牌已存好。",
      pluginAuthHintRejected: "对方不再接受已存的令牌。",
      pluginOauthStart: "去授权",
      pluginOauthRestart: "重新授权",
      pluginOauthOpenLink: "打开授权页面",
      pluginOauthCodePlaceholder: "把授权码贴在这里",
      pluginOauthExchange: "换取令牌",
    })[key] ?? key,
}));

import { ConnectionAuthorization } from "./ConnectionAuthorization";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

beforeEach(() => {
  startPluginOauth.mockReset();
  finishPluginOauth.mockReset();
  vi.stubGlobal("open", vi.fn());
});

describe("每种授权状态", () => {
  it.each([
    ["unauthorized", "未授权", "去授权", "填好应用凭据后点「去授权」。"],
    ["authorized", "已授权", "重新授权", "令牌已存好。"],
    ["rejected", "需要重新授权", "重新授权", "对方不再接受已存的令牌。"],
  ] as const)("%s:状态、说明和按钮文案对得上", (state, label, action, hint) => {
    const { container } = wrap(<ConnectionAuthorization instanceId="i1" state={state} />);
    const pill = container.querySelector('[data-slot="plugin-authorization-state"]') as HTMLElement;
    expect(pill.textContent).toBe(label);
    expect(pill.getAttribute("data-state")).toBe(state);
    expect(screen.getByText(hint)).toBeTruthy();
    expect(screen.getByRole("button", { name: action })).toBeTruthy();
  });

  it("已授权时重新授权是次要动作,没授权 / 被拒时是主动作", () => {
    const { unmount } = wrap(<ConnectionAuthorization instanceId="i1" state="authorized" />);
    expect(screen.getByRole("button", { name: "重新授权" }).className).toContain("border-field-border");
    unmount();
    wrap(<ConnectionAuthorization instanceId="i1" state="rejected" />);
    expect(screen.getByRole("button", { name: "重新授权" }).className).toContain("bg-action");
  });
});

describe("贴授权码", () => {
  it("点了之后在同一条里贴码、换令牌", async () => {
    startPluginOauth.mockResolvedValue({ authorize_url: "https://openapi.example.test/authorize?x=1", redirect_uri: "oob" });
    finishPluginOauth.mockResolvedValue([]);
    const { container } = wrap(<ConnectionAuthorization instanceId="i1" state="unauthorized" />);
    const strip = container.querySelector('[data-slot="plugin-authorization"]') as HTMLElement;

    fireEvent.click(screen.getByRole("button", { name: "去授权" }));
    const code = await within(strip).findByPlaceholderText("把授权码贴在这里");
    expect(window.open).toHaveBeenCalledWith("https://openapi.example.test/authorize?x=1", "_blank", "noreferrer");
    // 弹窗被拦时还有个能点的链接。
    expect(within(strip).getByRole("link", { name: /打开授权页面/ }).getAttribute("href")).toBe(
      "https://openapi.example.test/authorize?x=1",
    );

    const exchange = within(strip).getByRole("button", { name: "换取令牌" }) as HTMLButtonElement;
    expect(exchange.disabled).toBe(true);
    fireEvent.change(code, { target: { value: " the-code " } });
    fireEvent.click(exchange);
    await waitFor(() => expect(finishPluginOauth).toHaveBeenCalledWith("i1", " the-code "));
    // 换完收起:贴码那一行不留着。
    await waitFor(() => expect(within(strip).queryByPlaceholderText("把授权码贴在这里")).toBeNull());
  });
});
