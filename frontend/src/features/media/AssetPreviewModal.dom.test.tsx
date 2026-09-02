/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openImagePreview = vi.fn();

vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview }),
}));

import { AssetPreviewModal } from "./AssetPreviewModal";

const imageAsset = {
  id: "heic-asset",
  name: "IMG_0665.HEIC",
  original_filename: "IMG_0665.HEIC",
  kind: "image",
  source: "imported",
  tags: [],
  created_at: "2026-08-30T12:14:00",
  media_info: { width: 512, height: 512 },
};

describe("AssetPreviewModal", () => {
  beforeEach(() => openImagePreview.mockReset());

  it("uses the browser-compatible image endpoint in both inline and zoomed previews", () => {
    render(<AssetPreviewModal asset={imageAsset as never} onClose={vi.fn()} />);

    const image = screen.getByRole("img", { name: "IMG_0665.HEIC" });
    expect(image.getAttribute("src")).toBe("/preview/heic-asset");

    fireEvent.click(screen.getByTitle("assetClickToZoom"));
    expect(openImagePreview).toHaveBeenCalledWith({
      src: "/preview/heic-asset",
      title: "IMG_0665.HEIC",
    });
  });
});
