/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";

/**
 * 画板上一格图连到视频格,视频格选的是只收提示词的模型(维护者的 ComfyUI「minimax-text-image-2-video」:两个读图节点
 * 在 ComfyUI 里旁路了,工作流按文生视频跑)。此前图悄悄不挂、生成照跑,哪儿都没说那张图没用上。现在面板上方那一排
 * 就地说一句;收得下图的模型照旧自动挂上,不说。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: [] }),
  useQueries: ({ combine }: { combine: (results: unknown[]) => unknown }) => combine([]),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("./PromptEditor", () => ({ PromptEditor: () => <div />, restorePromptDocument: vi.fn(), textDocument: vi.fn(), collect: () => [] }));

import { ImagePreviewProvider } from "@/components/app/image-preview";
import { NodeComposer } from "./NodeComposer";

function video(capabilities: Record<string, unknown>): GenerationOption {
  return {
    id: "wf", provider_profile_id: "comfy", plugin_instance_id: "", profile_name: "ComfyUI",
    label: "minimax-text-image-2-video.json · ComfyUI", adapter_available: true, is_default: true, capabilities_known: true,
    provider: "plugin:dev.mosael.comfyui", model: "minimax-text-image-2-video.json", kind: "video",
    capabilities: { prompt: "optional", ...capabilities },
  } as GenerationOption;
}

function mount(option: GenerationOption) {
  const onSubmit = vi.fn();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  render(
    <ImagePreviewProvider>
      <NodeComposer
        item={{ id: "clip", kind: "video", text: "" } as BoardItem}
        models={[option]}
        upstream={[{ assetId: "cat", kind: "image" }]}
        busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
      />
    </ImagePreviewProvider>,
  );
  return onSubmit;
}

it("选的工作流不收图片:连过来的图就地说不会用上,发出去的也没有它", () => {
  const onSubmit = mount(video({ parameter_keys: ["seed"] }));
  expect(screen.getByRole("status")).toHaveTextContent("boardUpstreamUnusedImage");
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  const sent = onSubmit.mock.lastCall?.[0] as { source_assets?: unknown[] } | undefined;
  expect(sent?.source_assets ?? []).toEqual([]);
});

it("收首帧的模型:连过来的图自动挂上,不说用不上", () => {
  mount(video({ parameter_keys: ["first_frame"], source_limits: { first_frame: 1 } }));
  expect(document.querySelector("[data-upstream-unused]")).toBeNull();
});
