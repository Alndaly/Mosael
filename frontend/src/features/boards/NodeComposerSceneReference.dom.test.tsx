/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";
import { NodeComposer } from "./NodeComposer";
import { sceneReferenceUses } from "./SceneReferencePicker";

/**
 * 生成格上的「3D 参考」(ADR 0029 §2):连进来一个 3D 场景,面板上挑镜头和用法;用法只列模型收得下的,
 * 一种都不收时说清楚、发不出去(服务端照连线一定会现渲它,发出去只会被拒)。发出去的带着镜头和用法。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
let shots = [{ id: "shot-1", name: "全景" }, { id: "shot-2", name: "跟拍" }];
vi.mock("@tanstack/react-query", () => ({
  useQuery: ({ queryKey }: { queryKey: unknown[] }) =>
    queryKey[0] === "scene" ? { data: { name: "草原", revision: 2, content: { shots } } } : { data: [] },
  //: 按 id 取引到的素材(useAssetDetails):一份都没取到。
  useQueries: ({ combine }: { combine: (results: unknown[]) => unknown }) => combine([]),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("./PromptEditor", () => ({
  PromptEditor: () => <div data-testid="prompt-editor" />,
  restorePromptDocument: vi.fn(),
  textDocument: vi.fn(),
  collect: () => [],
}));

function model(kind: "image" | "video", keys: string[]): GenerationOption {
  return {
    id: "m", provider_profile_id: "p", plugin_instance_id: "", profile_name: "火山", label: "模型", adapter_available: true, is_default: true,
    capabilities_known: true, provider: "bytedance", model: "m", model_label: "m", kind, capabilities: { parameter_keys: keys, prompt: "optional" },
  } as GenerationOption;
}

function mount(kind: "image" | "video", keys: string[], form?: BoardItem["form"]) {
  const onSubmit = vi.fn();
  render(<NodeComposer
    item={{ id: "shot", kind, x: 0, y: 0, form } as BoardItem}
    models={[model(kind, keys)]}
    upstreamScene="sc"
    busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
  />);
  return { onSubmit };
}

it("用法只列模型收得下的:首尾帧和运镜只给视频", () => {
  const all = ["reference_image", "first_frame", "last_frame", "reference_video"];
  expect(sceneReferenceUses(model("video", all), "video")).toEqual(["composition", "frames", "motion"]);
  expect(sceneReferenceUses(model("image", all), "image")).toEqual(["composition"]);
  expect(sceneReferenceUses(model("video", ["first_frame"]), "video")).toEqual(["frames"]);
  expect(sceneReferenceUses(null, "video")).toEqual([]);
});

it("连了场景:一枚芯片写着场景名、镜头、用法(不是铺满整行的下拉),发出去的带着存着的镜头和用法", () => {
  const { onSubmit } = mount("video", ["first_frame", "last_frame"], { scene_reference: { shot_id: "shot-2", use: "frames" } });
  const chip = document.querySelector("[data-scene-reference]");
  expect(chip?.tagName).toBe("BUTTON");
  expect(chip?.textContent).toBe("草原· 跟拍 · boardSceneRefFrames");
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ sceneReference: { shot_id: "shot-2", use: "frames" } }));
});

it("存着的用法这个模型不收:换成它收的那一种发", () => {
  const { onSubmit } = mount("video", ["reference_image"], { scene_reference: { shot_id: "shot-1", use: "motion" } });
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ sceneReference: { shot_id: "shot-1", use: "composition" } }));
});

it("好几个镜头却没挑(或挑的镜头场景里已经没了):芯片上说,发不出去;只有一个镜头时就是它", () => {
  const { onSubmit } = mount("video", ["reference_image"], { scene_reference: { shot_id: "gone", use: "composition" } });
  expect(document.querySelector("[data-scene-reference]")?.getAttribute("data-scene-reference-state")).toBe("needs-shot");
  expect(screen.getByRole("button", { name: "boardGenerate" })).toBeDisabled();
  expect(onSubmit).not.toHaveBeenCalled();
});

it("场景只有一个镜头:不用挑,发出去的就是它", () => {
  shots = [{ id: "only", name: "唯一" }];
  const { onSubmit } = mount("video", ["reference_image"]);
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ sceneReference: { shot_id: "only", use: "composition" } }));
  shots = [{ id: "shot-1", name: "全景" }, { id: "shot-2", name: "跟拍" }];
});

it("模型一种都不收:说清楚,发不出去", () => {
  const { onSubmit } = mount("image", []);
  expect(document.querySelector("[data-scene-reference]")?.getAttribute("data-scene-reference-state")).toBe("unsupported");
  expect(document.querySelector("[data-scene-reference]")?.textContent).toContain("boardSceneRefUnsupported");
  const generate = screen.getByRole("button", { name: "boardGenerate" });
  expect(generate).toBeDisabled();
  fireEvent.click(generate);
  expect(onSubmit).not.toHaveBeenCalled();
});
