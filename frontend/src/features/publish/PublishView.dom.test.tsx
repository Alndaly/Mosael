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
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key === "mediaSelectedCount" ? "Selected {n}" : key,
  usePreferences: () => ({ locale: "en-US" }),
}));

import { assetKeys } from "@/api/queryKeys";
import { gotoSection } from "@/lib/deepLink";
import { PublishView } from "./PublishView";

it("selects only visible publish records and drops selections hidden by a status filter", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><PublishView workspace={{ id: "qa" } as Workspace} /></QueryClientProvider>);
  await screen.findByRole("button", { name: /Published film/ });
  fireEvent.click(screen.getByRole("button", { name: "studioNeedsAttention" }));
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode" }));
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectAll" }));
  expect(screen.getByText("Selected 1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "batchStatus_succeeded" }));
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
  client.setQueryData(assetKeys.list("qa"), [{ id: "film", name: "Final cut", kind: "video", media_info: {}, tags: [] }]);
  render(<QueryClientProvider client={client}><PublishView workspace={{ id: "qa" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click((await screen.findAllByRole("button", { name: /publishCreate/ }))[0]);
  const dialog = await screen.findByRole("dialog", { name: "publishCreate" });

  const [assetPicker, accountPicker] = within(dialog).getAllByRole("combobox");
  await user.click(assetPicker);
  await user.click(await screen.findByRole("option", { name: "Final cut" }));
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
  client.clear();
});
