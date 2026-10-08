/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 存储清理(SEC-7):没人认领的文件**只列出来**,打开这一页什么都不删;勾选、在确认框里点了「删除」,
 * 才把勾选的那几处交给后端。没勾的不交。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), message: vi.fn() } }));

const deletes: string[][] = [];
const ORPHANS = [
  { key: "media/assets/gone-ws", reason: "workspace_gone", bytes: 2048, modified_at: "2026-10-01T00:00:00Z" },
  { key: "avatars/nobody.png", reason: "avatar_unused", bytes: 512, modified_at: "2026-10-01T00:00:00Z" },
];
vi.mock("@/api/client", () => ({
  storageOrphansQuery: () => ({
    queryKey: ["admin", "storage-orphans"],
    queryFn: () => Promise.resolve({ items: ORPHANS, total_bytes: 2560 }),
  }),
  deleteStorageOrphans: (keys: string[]) => {
    deletes.push(keys);
    return Promise.resolve({ deleted: keys, skipped: [] });
  },
}));

const { StorageCleanupSection } = await import("./StorageCleanupSection");

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StorageCleanupSection />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  deletes.length = 0;
});

it("打开只列出来,不删;删除键在勾选之前点不了", async () => {
  show();
  expect(await screen.findByText("media/assets/gone-ws")).toBeInTheDocument();
  expect(screen.getByText("avatars/nobody.png")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /storageOrphansDelete/ })).toBeDisabled();
  expect(deletes).toEqual([]);
});

it("勾一处、确认之后只删那一处", async () => {
  show();
  fireEvent.click(await screen.findByRole("checkbox", { name: "media/assets/gone-ws" }));
  fireEvent.click(screen.getByRole("button", { name: /storageOrphansDelete/ }));
  const dialog = await screen.findByRole("alertdialog");
  expect(deletes).toEqual([]); // 确认之前不删
  fireEvent.click(within(dialog).getByRole("button", { name: "storageOrphansConfirmAction" }));
  await waitFor(() => expect(deletes).toEqual([["media/assets/gone-ws"]]));
});

it("确认框里点取消:什么都不删", async () => {
  show();
  fireEvent.click(await screen.findByRole("checkbox", { name: "avatars/nobody.png" }));
  fireEvent.click(screen.getByRole("button", { name: /storageOrphansDelete/ }));
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "cancel" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  expect(deletes).toEqual([]);
});
