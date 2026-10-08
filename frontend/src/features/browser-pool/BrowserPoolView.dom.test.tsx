/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
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
let failure: Error | null = null;
const recheckPublishAccount = vi.fn();
vi.mock("@/api/client", () => ({
  listBrowserProfiles: () => (failure ? Promise.reject(failure) : Promise.resolve(profiles)),
  listPublishPlatforms: () => Promise.resolve([{ platform: "bilibili", label: "Bilibili" }]),
  createBrowserProfile: vi.fn(), deleteBrowserProfile: vi.fn(), deletePublishAccount: vi.fn(),
  patchPublishAccount: vi.fn(), recheckPublishAccount: (id: string) => recheckPublishAccount(id), recordBrowserProfileOpened: vi.fn(),
  setResourceShared: vi.fn(), updateBrowserProfile: vi.fn(),
}));

const { BrowserPoolView } = await import("./BrowserPoolView");
const { readHint } = await import("@/test/hint");

function show(role = "editor") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BrowserPoolView workspace={{ id: "ws", role } as never} />
    </QueryClientProvider>,
  );
}

//: 体检 UM-21:取不回来时此前只剩标题和一个「0」,让人以为账号都没了、去重建。
it("账号列表取不回来:说取不回来、能重试,不画成 0 个", async () => {
  failure = new Error("boom");
  const view = show();
  expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
  expect(view.container.querySelector("[data-pool-load-error]")).not.toBeNull();
  expect(screen.queryByText("poolEmptyTitle")).toBeNull();
  failure = null;
});

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

//: 复检是一张卡的事。此前按钮的 loading 只看 isPending,点一张,所有卡的复检键一起转圈。
it("复检一张卡:只有这张卡的复检键在转", async () => {
  recheckPublishAccount.mockReturnValue(new Promise(() => undefined));
  profiles = [
    { ...base, id: "p3", name: "甲", bound_account_id: "a3", is_mine: true },
    { ...base, id: "p4", name: "乙", bound_account_id: "a4", is_mine: true },
  ];
  show();
  await screen.findByText("甲");
  const [first, second] = screen.getAllByRole("button", { name: "publishRecheck" });
  fireEvent.click(first);
  await vi.waitFor(() => expect(first).toHaveAttribute("aria-busy", "true"));
  expect(recheckPublishAccount).toHaveBeenCalledWith("a3");
  expect(second).not.toHaveAttribute("aria-busy");
});

//: 只读成员(体检 UM-20 / D62):建登录身份、加账号要「编辑」,按钮是灰的、说清为什么;共享来的照常能打开。
it("只读成员:新建登录身份、添加账号是灰的并说为什么", async () => {
  profiles = [{ ...base, id: "p1", name: "同事的 B 站", bound_account_id: "a1", is_mine: false }];
  show("viewer");
  expect(await screen.findByText("同事的 B 站")).toBeInTheDocument();
  const create = screen.getByRole("button", { name: "poolCreate" });
  expect(create).toBeDisabled();
  expect(await readHint(create)).toBe("roleReadOnlyHint");
  expect(screen.getByRole("button", { name: "publishAccountAdd" })).toBeDisabled();
});
