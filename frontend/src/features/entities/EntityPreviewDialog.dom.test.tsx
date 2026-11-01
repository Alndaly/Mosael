/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { EntitySummary } from "@/api/client";

const api = vi.hoisted(() => ({
  getEntity: vi.fn(),
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  entityKeys: { detail: (_workspace: string, id: string) => ["entities", "detail", id] },
}));
vi.mock("@/api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/api/client")>()), ...api }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: openImagePreview }) }));
vi.mock("@/components/app/modals", () => ({ ModalShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("./entityMeta", () => ({
  entityDisplayName: (entity: { name: string }) => entity.name,
  useCatalogLabels: () => ({ kind: () => "kind", role: (role: string) => role }),
}));
const openImagePreview = vi.hoisted(() => vi.fn());

import { EntityPreviewDialog } from "./EntityPreviewDialog";

const summary = {
  id: "e1", kind: "character", name: "张三", description: "", cover_asset_id: "cover",
  parent_id: null, parent_name: "", tags: [], reference_count: 1, variant_count: 0, updated_at: "",
} as EntitySummary;

describe("资产预览弹窗", () => {
  it("点封面和参考图都交给全局灯箱，翻页是这一组参考图", async () => {
    api.getEntity.mockResolvedValue({
      ...summary, prompt: "黑色短发", display_cover_asset_id: "cover",
      references: [{ asset_id: "ref1", role: "front", position: 1, asset_kind: "image", asset_name: "正面.png" }],
      variants: [], attributes: {}, lost_references: [], usable_for_digital_human: true,
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <EntityPreviewDialog workspaceId="w1" entity={summary} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(api.getEntity).toHaveBeenCalledWith("e1"));
    await user.click(await screen.findByRole("button", { name: "imagePreviewTitle" }));
    expect(openImagePreview).toHaveBeenCalledWith({ src: "/preview/cover", title: "张三", assetId: "cover" });

    await user.click(screen.getByRole("button", { name: "imagePreviewTitle 正面.png" }));
    expect(openImagePreview).toHaveBeenLastCalledWith({
      src: "/preview/ref1", title: "正面.png", assetId: "ref1",
      gallery: [{ src: "/preview/ref1", title: "正面.png", assetId: "ref1" }],
    });
  });
});
