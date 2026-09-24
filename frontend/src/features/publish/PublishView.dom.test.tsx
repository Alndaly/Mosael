/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { Workspace } from "@/api/client";

vi.mock("@/api/client", async importOriginal => ({
  ...await importOriginal<typeof import("@/api/client")>(),
  listPublishTasks: vi.fn().mockResolvedValue([
    { id: "done", title: "Published film", status: "succeeded", created_at: "2026-09-06T10:00:00Z", tags: [], result: {} },
    { id: "failed", title: "Needs a retry", status: "failed", created_at: "2026-09-06T10:00:00Z", tags: [], result: {} },
  ]),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key === "mediaSelectedCount" ? "Selected {n}" : key,
  usePreferences: () => ({ locale: "en-US" }),
}));

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

// 统计页「近 7 天发布」点进来:发布记录筛到已成功 —— 那个数数的就是成功的发布。
it("enters at the succeeded records when the statistics tile sends it there", async () => {
  gotoSection("publish", "succeeded");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><PublishView workspace={{ id: "qa" } as Workspace} /></QueryClientProvider>);
  await screen.findByRole("button", { name: /Published film/ });
  await waitFor(() => expect(screen.queryByRole("button", { name: /Needs a retry/ })).toBeNull());
  client.clear();
});
