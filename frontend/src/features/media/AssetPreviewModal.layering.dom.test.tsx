/** @vitest-environment jsdom */
/**
 * 这里给的是**一个查询上下文**:详情里那几块(镜头、节奏条、「清除元数据」)各自取数,生产里它们
 * 永远在一个 QueryClientProvider 底下(外壳)。这一份用例测的是灯箱与弹窗的层级,不测取数,
 * 所以给一个空的客户端就够 —— 没有它,`useQuery` 会直接抛 "No QueryClient set"。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  //: 「清除元数据」那一块会读任务列表;这一份不测它,给一条空的。
  listJobs: async () => [],
}));

//: 「属于哪些资产」那一行自己取数(资产库,ADR 0027),和这里要测的预览层次无关。
vi.mock("@/features/entities/AssetEntities", () => ({ AssetEntitiesList: () => null }));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

import { ImagePreviewProvider } from "@/components/app/image-preview";
import { AssetPreviewModal } from "./AssetPreviewModal";

const imageAsset = {
  id: "image-asset",
  name: "city.png",
  original_filename: "city.png",
  kind: "image",
  source: "imported",
  tags: [],
  created_at: "2026-09-04T00:00:00",
  media_info: { width: 1024, height: 1024 },
};

describe("AssetPreviewModal image-preview layering", () => {
  it("keeps the fullscreen preview interactive above the retained asset dialog", async () => {
    const onClose = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ImagePreviewProvider>
          <AssetPreviewModal asset={imageAsset as never} onClose={onClose} />
        </ImagePreviewProvider>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /assetClickToZoom/ }));

    const preview = await waitFor(() => {
      const element = document.querySelector<HTMLElement>(".PhotoView-Portal");
      expect(element).not.toBeNull();
      return element!;
    });
    expect(document.body.style.pointerEvents).toBe("none");
    expect(window.getComputedStyle(preview).pointerEvents).toBe("auto");

    const closeButton = preview.querySelector<SVGElement>(".PhotoView-Slider__toolbarIcon");
    expect(closeButton).not.toBeNull();
    fireEvent.click(closeButton!);

    await waitFor(() => expect(preview).toHaveClass("PhotoView-Slider__willClose"));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("img", { name: "city.png" })).toBeInTheDocument();
  });
});
