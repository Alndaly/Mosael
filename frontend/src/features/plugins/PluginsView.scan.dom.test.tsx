/** @vitest-environment jsdom */
/**
 * 体检 UM-32:「扫描插件」此前转一下就结束,扫没扫到东西看不出来;插件市场写着「有新版 5」,插件页左边的列表一个标记都没有,
 * 只有点进详情才看得到「可更新」。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  packages: [] as Array<Record<string, unknown>>,
  scanned: [] as Array<Record<string, unknown>>,
  market: [] as Array<Record<string, unknown>>,
  toast: { success: vi.fn(), error: vi.fn() },
}));
//: 详情那一栏要的接口很多,这里只关心列表和扫描:认得的几个给真数据,其余一律回空。
vi.mock("@/api/client", () => {
  const known: Record<string, unknown> = {
    listPluginPackages: async () => h.packages,
    rescanPlugins: async () => h.scanned,
    listPluginMarket: async () => ({ plugins: h.market }),
    pluginDir: async () => ({ path: "/plugins" }),
  };
  const fallback = new Map<string, unknown>();
  return new Proxy(known, {
    get: (target, key) => {
      if (typeof key !== "string" || key === "then" || key in target) return target[key as string];
      if (!fallback.has(key)) fallback.set(key, vi.fn().mockResolvedValue([]));
      return fallback.get(key);
    },
    has: (target, key) => key !== "then" && (typeof key === "string" || key in target),
  });
});
vi.mock("sonner", () => ({ toast: h.toast }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh-CN" }) }));

import { PluginsView } from "./PluginsView";

const PKG = { id: "dev.a", name: "甲", version: "1.0.0", kind: "process", multiple: false, permissions: [], provides: [], instances: [] };

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PluginsView workspaceId="w1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = vi.fn();
  h.packages = [];
  h.scanned = [];
  h.market = [];
  h.toast.success.mockReset();
});

it("扫描之后说出扫到了哪几个新插件;没有就说没有", async () => {
  show();
  h.scanned = [{ ...PKG }];
  fireEvent.click(await screen.findByRole("button", { name: /scanPlugins/ }));
  await waitFor(() => expect(h.toast.success).toHaveBeenCalledWith("pluginScanAdded"));

  h.toast.success.mockReset();
  h.packages = [{ ...PKG }];
  h.scanned = [{ ...PKG }];
  const view = show();
  await screen.findAllByText("甲");
  fireEvent.click(view.getAllByRole("button", { name: /scanPlugins/ }).at(-1)!);
  await waitFor(() => expect(h.toast.success).toHaveBeenCalledWith("pluginScanNothingNew"));
});

it("左边列表上标出有新版的插件", async () => {
  h.packages = [{ ...PKG }, { ...PKG, id: "dev.b", name: "乙" }];
  h.market = [{ id: "dev.b", version: "2.0.0", update_available: true }];
  const { container } = show();
  await waitFor(() => expect(container.querySelectorAll("[data-plugin-updatable]")).toHaveLength(1));
  expect(container.querySelector("[data-plugin-updatable]")?.closest("button")?.textContent).toContain("乙");
});
