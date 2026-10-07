/** @vitest-environment jsdom */
/**
 * 素材详情里的「来自」:派生素材显示它从哪几份、经过什么操作做出来(来源链,后端 domain/assets/lineage),
 * 点一下看那一份、能退回来;出处被删了写「已删除的素材」。来源标签不再把截出来的一段写成「AI 生成」。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const getAsset = vi.fn();
const getAssetLineage = vi.fn();

vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  fetchWaveform: async () => ({ peaks: [] }),
  getAsset: (id: string) => getAsset(id),
  getAssetLineage: (id: string) => getAssetLineage(id),
}));
vi.mock("@/features/entities/AssetEntities", () => ({ AssetEntitiesList: () => null }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }),
}));

import { AssetPreviewModal } from "./AssetPreviewModal";
import { assetOriginKey, showsContainsAi } from "@/lib/assetOrigin";

const base = { workspace_id: "ws", project_id: null, original_filename: "", file_key: "", tags: [], media_info: {},
               proxy_expected: false, created_at: "2026-10-01T10:00:00" };
const gif = { ...base, id: "gif", name: "片段 · GIF", kind: "image", source: "generated", ai_generated: true,
              derived_from: [{ asset_id: "cut", op: "gif" }], derived: true };
const cut = { ...base, id: "cut", name: "AI 视频 · 0.2-1.2s", kind: "video", source: "generated", ai_generated: true,
              derived_from: [{ asset_id: "root", op: "trim" }], derived: true };

function show(asset: object) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AssetPreviewModal asset={asset as never} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("素材详情的来源链", () => {
  it("列出出处和操作、一级一级往上;删掉的出处写「已删除」;点一下看那一份,能退回来", async () => {
    getAssetLineage.mockImplementation(async (id: string) => id === "gif"
      ? { asset_id: "gif", ai_generated: true, parents: [
          { asset_id: "cut", op: "gif", name: cut.name, kind: "video", ai_generated: true, parents: [
            { asset_id: "root", op: "trim", name: null, kind: null, ai_generated: null, parents: [] },
          ] },
        ] }
      : { asset_id: "cut", ai_generated: true, parents: [
          { asset_id: "root", op: "trim", name: null, kind: null, ai_generated: null, parents: [] },
        ] });
    getAsset.mockResolvedValue(cut);
    show(gif);

    expect(screen.getByText("assetLineageTitle")).toBeTruthy();
    const source = await screen.findByRole("button", { name: cut.name });
    expect(screen.getByText("(assetLineageOpGif)")).toBeTruthy();
    expect(screen.getByText("(assetLineageOpTrim)")).toBeTruthy();
    expect(screen.getByText("assetLineageDeleted")).toBeTruthy();
    // 截出来、转出来的是「加工」,含 AI 另挂一枚 —— 不再一律写成「AI 生成」。
    expect(screen.getByText("mediaSourceDerived")).toBeTruthy();
    expect(screen.getByText("mediaSourceContainsAi")).toBeTruthy();

    fireEvent.click(source);
    await waitFor(() => expect(screen.getByRole("heading", { name: cut.name })).toBeTruthy());
    expect(getAsset).toHaveBeenCalledWith("cut");

    fireEvent.click(screen.getByRole("button", { name: /assetLineageBack/ }));
    expect(screen.getByRole("heading", { name: gif.name })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /assetLineageBack/ })).toBeNull();
  });

  it("导入的素材没有「来自」这一行,也不去取来源链", () => {
    getAssetLineage.mockClear();
    show({ ...base, id: "plain", name: "实拍.mp4", kind: "image", source: "imported", ai_generated: false, derived_from: [], derived: false });
    expect(screen.queryByText("assetLineageTitle")).toBeNull();
    expect(getAssetLineage).not.toHaveBeenCalled();
    expect(screen.getByText("mediaSourceImported")).toBeTruthy();
  });
});

describe("来源标签", () => {
  const origin = (source: string, aiGenerated: boolean, derived = false) => ({
    source, ai_generated: aiGenerated, derived,
  });

  it("生成任务的产出是「AI 生成」,不另挂含 AI", () => {
    expect(assetOriginKey(origin("generated", true))).toBe("mediaSourceGenerated");
    expect(showsContainsAi(origin("generated", true))).toBe(false);
    expect(assetOriginKey(origin("tts", true))).toBe("mediaSourceGenerated");
  });

  it("实拍截一段是「加工」,不是 AI;老的 generated 没记出处、又不含 AI 的也是「加工」", () => {
    expect(assetOriginKey(origin("generated", false, true))).toBe("mediaSourceDerived");
    expect(assetOriginKey(origin("generated", false))).toBe("mediaSourceDerived");
    expect(showsContainsAi(origin("generated", false, true))).toBe(false);
  });

  it("含 AI 的成片是「导出」,另挂「含 AI 生成内容」", () => {
    expect(assetOriginKey(origin("exported", true, true))).toBe("mediaSourceExported");
    expect(showsContainsAi(origin("exported", true, true))).toBe(true);
  });
});
