/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

/**
 * 管只认主人(后端 sharing.ensure_manageable):共享给我的登录身份,卡片上不摆改名 / 代理 / 退出 /
 * 删除、复检和启用开关 —— 摆出来点了也是 403。我自己的照旧全有。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t, usePreferences: () => ({ locale: "en-US" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/features/publish/AddAccountDialog", () => ({ AddAccountDialog: () => null }));

const base = {
  workspace_id: "ws", partition: "persist:mosael-a", proxy: null, enabled: true, last_used_at: null,
  start_url: null, created_at: "2026-09-20T00:00:00Z", platform: "bilibili", binding_status: "bound",
  last_checked_at: null, last_error: null, shared: true,
};
let profiles: Array<Record<string, unknown>> = [];
vi.mock("@/api/client", () => ({
  listBrowserProfiles: () => Promise.resolve(profiles),
  listPublishPlatforms: () => Promise.resolve([{ platform: "bilibili", label: "Bilibili" }]),
  createBrowserProfile: vi.fn(), deleteBrowserProfile: vi.fn(), deletePublishAccount: vi.fn(),
  patchPublishAccount: vi.fn(), recheckPublishAccount: vi.fn(), recordBrowserProfileOpened: vi.fn(),
  setResourceShared: vi.fn(), updateBrowserProfile: vi.fn(),
}));

const { BrowserPoolView } = await import("./BrowserPoolView");

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BrowserPoolView workspace={{ id: "ws" } as never} />
    </QueryClientProvider>,
  );
}

it("共享给我的账号:能打开,管理动作一个都不摆", async () => {
  profiles = [{ ...base, id: "p1", name: "同事的 B 站", bound_account_id: "a1", is_mine: false }];
  show();
  expect(await screen.findByText("同事的 B 站")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /studioActions/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "publishRecheck" })).toBeNull();
  expect(screen.queryByRole("button", { name: "poolRelogin" })).toBeNull();
  expect(screen.getByRole("switch", { name: "publishAccountEnabled" })).toBeDisabled();
});

it("我自己的账号:菜单、复检、重新登录、开关都在", async () => {
  profiles = [{ ...base, id: "p2", name: "我的 B 站", bound_account_id: "a2", is_mine: true }];
  show();
  expect(await screen.findByText("我的 B 站")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /studioActions/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "publishRecheck" })).toBeInTheDocument();
  expect(screen.getByRole("switch", { name: "publishAccountEnabled" })).toBeEnabled();
});
