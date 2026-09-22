/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { separateAssetAudio, type Asset, type Workspace } from "@/api/client";
import { MediaLibraryView } from "./MediaLibraryView";

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  separateAssetAudio: vi.fn(async () => ({ id: "job-1" })),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "en" }) }));
vi.mock("@/features/media/RecordingProvider", () => ({ useRecorder: () => ({ openRecorder: vi.fn() }) }));
vi.mock("@/features/media/UrlImportDialog", () => ({ UrlImportDialog: () => null }));
vi.mock("@/features/media/AssetPreviewModal", () => ({ AssetPreviewModal: () => null }));

it("keeps only the current asset action menu open and closes it for a context menu", async () => {
  localStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["assets", "ws"], ["one", "two", "three"].map(id => ({
    id, name: id, workspace_id: "ws", project_id: null, original_filename: id, file_key: id, kind: "image", source: "imported", tags: [], media_info: {}, proxy_expected: false,
  }) as Asset));
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();
  for (const id of ["one", "two", "three"]) {
    await user.click(screen.getByRole("button", { name: `studioActions: ${id}` }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "rename" })).toHaveLength(1));
    expect(screen.getByRole("button", { name: `studioActions: ${id}` })).toHaveAttribute("aria-expanded", "true");
  }
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("button", { name: "rename" })).not.toBeInTheDocument());
  await user.click(screen.getByRole("button", { name: "studioActions: one" }));
  fireEvent.contextMenu(screen.getByRole("button", { name: "two" }), { button: 2, clientX: 50, clientY: 50 });
  await waitFor(() => expect(screen.queryByRole("button", { name: "rename" })).not.toBeInTheDocument());
  expect(screen.getByRole("menuitem", { name: "rename" })).toBeInTheDocument();
});

it("有声音的素材才能分离人声与背景音,点了就排任务", async () => {
  localStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  const asset = (id: string, kind: Asset["kind"]) =>
    ({ id, name: id, workspace_id: "ws", project_id: null, original_filename: id, file_key: id, kind, source: "imported", tags: [], media_info: {}, proxy_expected: false }) as Asset;
  client.setQueryData(["assets", "ws"], [asset("clip", "video"), asset("still", "image")]);
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();

  await user.click(screen.getByRole("button", { name: "studioActions: still" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "rename" })).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "separateAudio" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "denoiseAction" })).not.toBeInTheDocument();
  await user.keyboard("{Escape}");

  await user.click(screen.getByRole("button", { name: "studioActions: clip" }));
  await user.click(await screen.findByRole("button", { name: "separateAudio" }));
  await waitFor(() => expect(separateAssetAudio).toHaveBeenCalledWith("clip"));
});

it("有声音的素材能降噪:点了打开降噪对话框", async () => {
  localStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(["assets", "ws"], [
    { id: "clip", name: "clip", workspace_id: "ws", project_id: null, original_filename: "clip", file_key: "clip", kind: "audio", source: "imported", tags: [], media_info: {}, proxy_expected: false } as Asset,
  ]);
  client.setQueryData(["denoise-engines"], []);
  render(<QueryClientProvider client={client}><MediaLibraryView workspace={{ id: "ws" } as Workspace} /></QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "studioActions: clip" }));
  await user.click(await screen.findByRole("button", { name: "denoiseAction" }));
  expect(await screen.findByRole("dialog", { name: "denoiseTitle" })).toBeInTheDocument();
});
