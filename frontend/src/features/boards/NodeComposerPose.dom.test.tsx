/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";
import { NodeComposer } from "./NodeComposer";

/**
 * 画板生成格里 `@` 了姿势(ADR 0091 §5):和 AI Studio 同一组控件 —— 这一镜的机位(姿势参考只发同机位那张)、
 * 「按普通参考图发送」。此前画板根本不发机位,`@` 姿势在这里永远发不出去。存着的选择重新打开照它还原,发出去带着它。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
const actualQuery = vi.hoisted(() => vi.importActual<typeof import("@tanstack/react-query")>("@tanstack/react-query"));
vi.mock("@/features/entities/EntityPreviewDialog", () => ({ EntityPreviewDialog: () => null }));
vi.mock("./SourceAssetSlotPreview", () => ({ SourceAssetSlotPreview: () => null }));
vi.mock("@tanstack/react-query", async () => ({
  QueryClientContext: (await actualQuery).QueryClientContext,
  useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
    if (queryKey[0] === "entity-catalog") {
      return { data: { roles: [{ role: "side", label: "侧面" }], shot_angles: ["side"], kinds: [], roles_by_kind: {} } };
    }
    if (queryKey[0] === "entities") return { data: [
      { id: "pose-1", kind: "pose", name: "坐姿", reference_count: 1 },
      { id: "zhang", kind: "character", name: "张三", reference_count: 1 },
      { id: "multi", kind: "character", name: "多图", reference_count: 3 },
    ] };
    return { data: [] };
  },
  useQueries: ({ combine }: { combine: (results: unknown[]) => unknown }) => combine([]),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
//: 正文里的 `@姿势` 小条由 PromptEditor 画;这里只看这一格交给小条的那颗附加控件挂没挂对。
vi.mock("./PromptEditor", () => ({
  PromptEditor: ({ entityChip }: {
    entityChip?: {
      accessory?: (id: string) => React.ReactNode;
      warning?: (id: string) => string | null;
      assetWarning?: (id: string) => string | null;
    };
  }) => (
    <div data-testid="prompt-editor">
      {entityChip?.accessory?.("pose-1")}{entityChip?.accessory?.("zhang")}
      {entityChip?.assetWarning?.("img2") && <span data-asset-warning>{entityChip.assetWarning("img2")}</span>}
      {entityChip?.warning?.("zhang") && <span data-entity-warning>{entityChip.warning("zhang")}</span>}
      {entityChip?.warning?.("pose-1") && <span data-pose-warning>{entityChip.warning("pose-1")}</span>}
      {entityChip?.warning?.("multi") && <span data-entity-partial-warning>{entityChip.warning("multi")}</span>}
    </div>
  ),
  restorePromptDocument: vi.fn(),
  textDocument: vi.fn(),
  collect: () => [],
}));

function model(keys: string[]): GenerationOption {
  return {
    id: "m", provider_profile_id: "p", plugin_instance_id: "", profile_name: "ComfyUI", label: "模型", adapter_available: true, is_default: true,
    capabilities_known: true, provider: "plugin", model: "m", model_label: "m", kind: "image",
    capabilities: { parameter_keys: keys, prompt: "optional" },
  } as GenerationOption;
}

function mount(keys: string[], form: BoardItem["form"]) {
  const onSubmit = vi.fn();
  render(<NodeComposer
    item={{ id: "shot", kind: "image", x: 0, y: 0, form } as BoardItem}
    models={[model(keys)]}
    busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
  />);
  return { onSubmit };
}

it("没 @ 姿势:不摆机位那一行", () => {
  mount(["reference_image", "pose_reference"], { mentioned_entity_ids: ["zhang"] });
  expect(document.querySelector("[data-pose-use]")).toBeNull();
});

it("@ 了姿势、模型收姿势参考:摆机位;存着的机位还原,发出去带着它", () => {
  const { onSubmit } = mount(["reference_image", "pose_reference"], {
    mentioned_entity_ids: ["pose-1"], pose: { shot_angle: "side", as_reference: false },
  });
  expect(document.querySelector("[data-pose-use] [data-shot-angle]")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ pose: { shot_angle: "side", as_reference: false } }));
});

it("正文引用装不进模型的槽位时,在引用块里提示哪些不会发送", () => {
  mount(["reference_image"], {
    source_assets: [{ asset_id: "img1", role: "reference_image" }],
    mentioned_asset_ids: ["img2"],
  });
  const warning = document.querySelector("[data-asset-warning]");
  expect(warning).not.toBeNull();
  expect(warning?.textContent).toContain("boardMentionNotSentTip");
});

it("资产参考图没有名额时,在引用块里提示描述仍会发送", () => {
  mount(["reference_image"], {
    source_assets: [{ asset_id: "img1", role: "reference_image" }],
    mentioned_entity_ids: ["zhang"],
  });
  const warning = document.querySelector("[data-entity-warning]");
  expect(warning).not.toBeNull();
  expect(warning?.textContent).toContain("boardEntityImageNotSentTip");
});

it("资产有多张参考图、名额不够时提示最多发几张", () => {
  mount(["reference_image"], { mentioned_entity_ids: ["multi"] });
  const warning = document.querySelector("[data-entity-partial-warning]");
  expect(warning).not.toBeNull();
  expect(warning?.textContent).toContain("boardEntityImagePartlySentTip");
});

it("模型不收姿势参考:说清原因,不谎报名额已满;勾上后按普通参考图发送", () => {
  const { onSubmit } = mount(["reference_image"], { mentioned_entity_ids: ["pose-1", "zhang"] });
  expect(document.querySelector("[data-pose-use]")).toBeNull();
  expect(screen.getAllByRole("checkbox", { name: "genPoseAsReference" })).toHaveLength(1);
  expect(document.querySelector("[data-pose-warning]")?.textContent).toContain("boardEntityPoseReferenceUnsupportedTip");
  fireEvent.click(screen.getByRole("checkbox", { name: "genPoseAsReference" }));
  expect(document.querySelector("[data-pose-warning]")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ pose: { shot_angle: null, as_reference: true } }));
});
