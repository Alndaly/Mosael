/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Workspace } from "@/api/client";
import { MediaLibraryView } from "./MediaLibraryView";

//: 素材列表永远在路上 —— 只看首屏加载那一刻画的是什么。
vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  api: vi.fn(() => new Promise(() => {})),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "en" }) }));
vi.mock("@/features/media/RecordingProvider", () => ({ useRecorder: () => ({ openRecorder: vi.fn() }) }));
vi.mock("@/features/media/UrlImportDialog", () => ({ UrlImportDialog: () => null }));
vi.mock("@/features/media/AssetPreviewModal", () => ({ AssetPreviewModal: () => null }));

afterEach(cleanup);

function renderLibrary(display: "grid" | "list") {
  localStorage.clear();
  localStorage.setItem("mosael:tab:media-display", display);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MediaLibraryView workspace={{ id: "ws" } as Workspace} />
    </QueryClientProvider>,
  );
}

it("首屏加载画的是和素材卡同形的扫光骨架,不是页面正中一个转圈", () => {
  renderLibrary("grid");
  const status = screen.getByRole("status");
  expect(status).toHaveAttribute("aria-busy", "true");
  expect(status).toHaveTextContent("pageLoading");
  const skeletons = status.querySelectorAll("[data-slot='skeleton']");
  expect(skeletons.length).toBeGreaterThan(0);
  expect(status.querySelector(".aspect-video")).not.toBeNull();
  expect(document.querySelector(".animate-mosael-spin")).toBeNull();
});

it("列表视图的骨架是一行一行的,缩略图和 AssetTile 的行同尺寸", () => {
  renderLibrary("list");
  const status = screen.getByRole("status");
  expect(status.querySelector(".aspect-video")).toBeNull();
  expect(status.querySelector("[data-slot='skeleton'].h-20.w-32")).not.toBeNull();
});
