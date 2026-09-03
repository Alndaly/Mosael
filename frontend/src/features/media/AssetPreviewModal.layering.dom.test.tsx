/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
}));

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
    render(
      <ImagePreviewProvider>
        <AssetPreviewModal asset={imageAsset as never} onClose={onClose} />
      </ImagePreviewProvider>,
    );

    fireEvent.click(screen.getByTitle("assetClickToZoom"));

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
