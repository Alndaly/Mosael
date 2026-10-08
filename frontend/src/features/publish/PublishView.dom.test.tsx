/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { Workspace } from "@/api/client";

vi.mock("@/api/client", async importOriginal => ({
  ...await importOriginal<typeof import("@/api/client")>(),
  listPublishTasks: vi.fn().mockResolvedValue([
    { id: "done", title: "Published film", status: "succeeded", created_at: "2026-09-06T10:00:00Z", tags: [], result: {} },
    { id: "failed", title: "Needs a retry", status: "failed", created_at: "2026-09-06T10:00:00Z", tags: [], result: {} },
  ]),
  listPublishAccounts: vi.fn().mockResolvedValue([
    { id: "live", name: "Live account", platform: "short", enabled: true, binding_status: "bound", config: {} },
    { id: "off", name: "Paused account", platform: "short", enabled: false, binding_status: "bound", config: {} },
  ]),
  listPublishPlatforms: vi.fn().mockResolvedValue([
    { platform: "short", label: "Short", description: "", config: {}, title_max: 5, short_title: false, options: [] },
  ]),
  listAssetPage: vi.fn().mockResolvedValue({
    items: [{ id: "film", name: "Final cut", kind: "video", media_info: {}, tags: [] }],
    next_cursor: null,
    total: 1,
  }),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key === "mediaSelectedCount" ? "Selected {n}" : key,
  usePreferences: () => ({ locale: "en-US" }),
}));

import { listAssetPage } from "@/api/client";
import { gotoSection } from "@/lib/deepLink";
import { PublishView } from "./PublishView";

it("selects only visible publish records and drops selections hidden by a status filter", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><PublishView workspace={{ id: "qa" } as Workspace} /></QueryClientProvider>);
  await screen.findByRole("button", { name: /Published film/ });
  fireEvent.click(screen.getByRole("tab", { name: "studioNeedsAttention" }));
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode" }));
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectAll" }));
  expect(screen.getByText("Selected 1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "batchStatus_succeeded" }));
  await waitFor(() => expect(screen.getByText("Selected 0")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "delete" })).toBeDisabled();
  client.clear();
});

// 统计页「近 N 天发布」点进来:发布记录筛到已成功 —— 那个数数的就是成功的发布。
it("enters at the succeeded records when the statistics tile sends it there", async () => {
  gotoSection("publish", "succeeded");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><PublishView workspace={{ id: "qa" } as Workspace} /></QueryClientProvider>);
  await screen.findByRole("button", { name: /Published film/ });
  await waitFor(() => expect(screen.queryByRole("button", { name: /Needs a retry/ })).toBeNull());
  client.clear();
});

// 新建发布:停用的账号后端会拒(publishErr_accountDisabled),标题超长后端也会拒(publishErr_titleTooLong)——
// 两样都在提交前拦下,不让用户点了才知道。
it("新建发布:不列停用账号并说明;标题超长时不能提交", async () => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = () => {};
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  render(<QueryClientProvider client={client}><PublishView workspace={{ id: "qa" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click((await screen.findAllByRole("button", { name: /publishCreate/ }))[0]);
  const dialog = await screen.findByRole("dialog", { name: "publishCreate" });

  const [assetPicker, accountPicker] = within(dialog).getAllByRole("combobox");
  await user.click(assetPicker);
  await user.click(await screen.findByRole("option", { name: "Final cut" }));
  //: 只问视频,而且是在服务端筛的 —— 不把整个素材库拉回来再挑。
  expect(vi.mocked(listAssetPage).mock.calls[0][0]).toMatchObject({ workspace_id: "qa", kind: ["video"] });
  expect(assetPicker).toHaveTextContent("Final cut");
  await user.click(accountPicker);
  expect(screen.queryByRole("option", { name: "Paused account" })).toBeNull();
  await user.click(await screen.findByRole("option", { name: "Live account" }));
  expect(within(dialog).getByText(/publishAccountsDisabledHidden/)).toBeInTheDocument();

  const submit = within(dialog).getByRole("button", { name: /publishStart/ });
  const title = within(dialog).getByRole("textbox", { name: /publishTitle/ });
  await user.type(title, "12345");
  expect(submit).toBeEnabled();
  await user.type(title, "6");
  expect(submit).toBeDisabled();
  // 按码点数(后端 len() 的尺):五个 emoji 是 5 个字,不是 10 个 UTF-16 单元。
  await user.clear(title);
  await user.type(title, "🎬🎬🎬🎬🎬");
  expect(submit).toBeEnabled();
  client.clear();
});

//: 体检 UM-22:主密钥丢了之后账号列表此前整个 500,下拉里只写「没有匹配的结果」。
it("新建发布:账号取不回来说取不回来、能重试;存着的设置解不开的账号说要重新登录", async () => {
  const { listPublishAccounts } = await import("@/api/client");
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = () => {};
  vi.mocked(listPublishAccounts).mockRejectedValueOnce(new Error("boom"));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  const { container } = render(<QueryClientProvider client={client}><PublishView workspace={{ id: "qa" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click((await screen.findAllByRole("button", { name: /publishCreate/ }))[0]);
  await waitFor(() => expect(container.ownerDocument.querySelector("[data-publish-accounts-error]")).not.toBeNull());

  vi.mocked(listPublishAccounts).mockResolvedValueOnce([
    { id: "live", name: "Live account", platform: "short", enabled: true, binding_status: "bound", config: {}, config_unreadable: true },
  ] as never);
  await user.click(within(container.ownerDocument.querySelector("[data-publish-accounts-error]") as HTMLElement).getByRole("button", { name: "retry" }));
  await waitFor(() =>
    expect(container.ownerDocument.querySelector("[data-publish-accounts-unreadable]")?.textContent).toContain("publishAccountConfigUnreadable"),
  );
  expect(container.ownerDocument.querySelector("[data-publish-accounts-error]")).toBeNull();
  client.clear();
});
