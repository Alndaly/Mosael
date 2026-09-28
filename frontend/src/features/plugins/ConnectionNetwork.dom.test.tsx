/** @vitest-environment jsdom */

/**
 * 连接上的「网络」那一行:默认跟随 Mosael,单个连接可以改成直连或走它自己的代理。
 *
 * 钉的是交互的两条规矩:选直连 / 跟随当场就存;选「走指定代理」先长出地址框,**填好离开时才存** ——
 * 没有地址的代理后端存不进去,一选就发一次注定失败的请求只会弹一句错。后端拒了(地址没写全)原话转出来。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { updatePluginInstance, toastError } = vi.hoisted(() => ({
  updatePluginInstance: vi.fn(),
  toastError: vi.fn(),
}));
vi.mock("@/api/client", () => ({ updatePluginInstance }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: toastError } }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      pluginNetwork: "网络",
      pluginNetworkFollow: "跟随 Mosael",
      pluginNetworkDirect: "直连(不走代理)",
      pluginNetworkProxy: "走指定代理",
      pluginNetworkProxyUrl: "代理地址",
    })[key] ?? key,
}));

import { ConnectionNetwork } from "./ConnectionNetwork";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

function pick(label: string) {
  fireEvent.click(screen.getByRole("button", { name: /跟随 Mosael|直连|走指定代理/ }));
  fireEvent.click(screen.getByRole("option", { name: label }));
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  updatePluginInstance.mockReset();
  updatePluginInstance.mockResolvedValue({});
  toastError.mockReset();
});

describe("连接的网络", () => {
  it("默认跟随 Mosael,没有地址框", () => {
    wrap(<ConnectionNetwork instanceId="i1" network={{ mode: "follow", proxy_url: "" }} />);
    expect(screen.getByText("跟随 Mosael")).toBeTruthy();
    expect(screen.queryByLabelText("代理地址")).toBeNull();
  });

  it("选直连当场就存", async () => {
    wrap(<ConnectionNetwork instanceId="i1" network={{ mode: "follow", proxy_url: "" }} />);
    pick("直连(不走代理)");
    await waitFor(() =>
      expect(updatePluginInstance).toHaveBeenCalledWith("i1", { network: { mode: "direct", proxy_url: "" } }),
    );
  });

  it("选走指定代理:先长出地址框,填好离开时才存", async () => {
    wrap(<ConnectionNetwork instanceId="i1" network={{ mode: "follow", proxy_url: "" }} />);
    pick("走指定代理");
    expect(updatePluginInstance).not.toHaveBeenCalled();
    const address = screen.getByLabelText("代理地址");
    fireEvent.focus(address);
    fireEvent.change(address, { target: { value: " http://127.0.0.1:7890 " } });
    expect(updatePluginInstance).not.toHaveBeenCalled();
    fireEvent.blur(address);
    await waitFor(() =>
      expect(updatePluginInstance).toHaveBeenCalledWith("i1", {
        network: { mode: "proxy", proxy_url: "http://127.0.0.1:7890" },
      }),
    );
  });

  it("已经走代理的连接:地址框里是它的地址,清空离开不存一个没有地址的代理", () => {
    wrap(<ConnectionNetwork instanceId="i1" network={{ mode: "proxy", proxy_url: "http://mainland:8080" }} />);
    const address = screen.getByLabelText("代理地址") as HTMLInputElement;
    expect(address.value).toBe("http://mainland:8080");
    fireEvent.focus(address);
    fireEvent.change(address, { target: { value: "" } });
    fireEvent.blur(address);
    expect(updatePluginInstance).not.toHaveBeenCalled();
  });

  it("后端拒了,原话说出来", async () => {
    updatePluginInstance.mockRejectedValue(new Error("代理地址「127.0.0.1:7890」不对:要写全"));
    wrap(<ConnectionNetwork instanceId="i1" network={{ mode: "follow", proxy_url: "" }} />);
    pick("走指定代理");
    const address = screen.getByLabelText("代理地址");
    fireEvent.focus(address);
    fireEvent.change(address, { target: { value: "127.0.0.1:7890" } });
    fireEvent.blur(address);
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("代理地址「127.0.0.1:7890」不对:要写全"));
    // 地址框还在,人能接着改。
    expect(screen.getByLabelText("代理地址")).toBeTruthy();
  });
});
