// @vitest-environment jsdom
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReferenceItem, Workspace } from "@/api/client";

/**
 * 参考库(ADR 0091 §3)那一页的两处:机位名读资产库词表(插件交的是角度的键,不是给人看的字),
 * 图集取不出来时只说一次(此前「没加载出来」和「没有匹配的条目」叠在一屏上)。
 */

const api = vi.hoisted(() => ({
  listReferenceConnections: vi.fn(),
  listReferenceCollections: vi.fn(),
  searchReferenceItems: vi.fn(),
  getReferenceItem: vi.fn(),
  ingestReferenceItem: vi.fn(),
  getEntityCatalog: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...api,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ReferenceLibraryView } from "@/features/entities/ReferenceLibraryView";

const WORKSPACE = { id: "w1", name: "W" } as Workspace;
const ITEM: ReferenceItem = {
  id: "full_single_P001", collection: "poses", kind: "pose",
  name: { zh: "后仰坐・单膝立起", en: "Reclining sit" }, tags: ["坐姿"],
  thumbnail: "https://example.test/front.jpg",
  views: [
    { role: "front", thumbnail: "https://example.test/front.jpg", original: "https://example.test/front.png" },
    { role: "three_quarter", thumbnail: "https://example.test/diag.jpg", original: "https://example.test/diag.png" },
  ],
  nsfw: false,
  provenance: { author: "作者", url: "https://example.test/", license: "仅供参考" },
};
const CATALOG = {
  kinds: [{ kind: "pose", label: "姿势" }],
  roles: [{ role: "front", label: "正面" }, { role: "three_quarter", label: "斜侧" }],
  roles_by_kind: { pose: ["front", "three_quarter"] },
  consent_kinds: [], attach_priority: {}, attributes: {}, default_role: { pose: "front" }, attribute_choices: {},
};

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReferenceLibraryView workspace={WORKSPACE} />
    </QueryClientProvider>,
  );
}

describe("参考库", () => {
  beforeEach(() => {
    api.listReferenceConnections.mockResolvedValue([{ id: "c1", name: "PoseAtlas" }]);
    api.listReferenceCollections.mockResolvedValue([
      { id: "poses", kind: "pose", name: { zh: "姿势图鉴", en: "Pose atlas" }, count: 1, filters: [] },
    ]);
    api.searchReferenceItems.mockResolvedValue({ items: [ITEM], next_cursor: "" });
    api.getReferenceItem.mockResolvedValue(ITEM);
    api.getEntityCatalog.mockResolvedValue(CATALOG);
  });
  afterEach(cleanup);

  it("条目详情里的机位按资产库词表说,不是插件给的键", async () => {
    renderView();
    fireEvent.click(await screen.findByText("后仰坐・单膝立起"));

    expect(await screen.findByText("斜侧")).toBeTruthy();
    expect(screen.getByText("正面")).toBeTruthy();
    expect(screen.queryByText("three_quarter")).toBeNull();
  });

  it("用作素材取选中的那个视角;存为资产不点名视角(每个视角各取一张)", async () => {
    api.ingestReferenceItem.mockResolvedValue({ asset_id: "a1", asset_ids: ["a1"], entity_id: "" });
    renderView();
    fireEvent.click(await screen.findByText("后仰坐・单膝立起"));
    const side = await screen.findByRole("radio", { name: /斜侧/ });
    fireEvent.click(side);
    expect((side as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /referenceLibraryUse/ }));
    await waitFor(() => expect(api.ingestReferenceItem).toHaveBeenCalledWith("c1", expect.objectContaining({ role: "three_quarter", save_entity: false })));
  });

  it("图集取不出来时只说一次,并照实说为什么(不是一句「请重试」)", async () => {
    api.listReferenceCollections.mockRejectedValue(new Error("「PoseAtlas」不可用:还没授予权限:network:github"));
    renderView();

    expect(await screen.findByText("referenceLibraryFailed")).toBeTruthy();
    expect(screen.getByText(/还没授予权限:network:github/)).toBeTruthy();
    expect(screen.queryByText("referenceLibraryNoItems")).toBeNull();
  });

  it("缩略图载好之前先占一块骨架，载好再撤掉", async () => {
    const { container } = renderView();
    await screen.findByText("后仰坐・单膝立起");

    expect(container.querySelector("[data-thumb-loading]")).toBeTruthy();
    const image = container.querySelector('img[src="https://example.test/front.jpg"]') as HTMLImageElement;
    fireEvent.load(image);

    await waitFor(() => expect(container.querySelector("[data-thumb-loading]")).toBeNull());
  });
});
