/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { NodeComposer } from "./NodeComposer";

/**
 * 数字人的授权(ADR 0028 §5):生成格挂了驱动音频,就要本人勾上「已取得画面中人物的授权」才发得出去;
 * 发出去的带着它(后端生成漏斗不见它就拒)。没挂驱动音频的生成不出这一格。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: [] }), useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock("./PromptEditor", () => ({
  PromptEditor: () => <div data-testid="prompt-editor" />,
  restorePromptDocument: vi.fn(),
  textDocument: vi.fn(),
  collect: () => [],
}));

const TALKING = {
  id: "m", provider_profile_id: "p", profile_name: "百炼", label: "说话照片", adapter_available: true, is_default: true,
  capabilities_known: true, provider: "alibaba", model: "wan2.2-s2v", kind: "video",
  capabilities: { parameter_keys: ["first_frame", "driving_audio"], prompt: "none" },
} as GenerationOption;

function mount(sources: { asset_id: string; role: string }[]) {
  const onSubmit = vi.fn();
  render(
    <ImagePreviewProvider>
      <NodeComposer
        item={{ id: "talk", kind: "video", x: 0, y: 0, form: { source_assets: sources } } as BoardItem}
        models={[TALKING]}
        busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
      />
    </ImagePreviewProvider>,
  );
  return { onSubmit };
}

it("挂了驱动音频:不勾授权发不出去,勾上之后发出去的带着它", () => {
  const { onSubmit } = mount([{ asset_id: "face", role: "first_frame" }, { asset_id: "line", role: "driving_audio" }]);
  const generate = screen.getByRole("button", { name: "boardGenerate" });
  expect(generate).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /genDigitalHumanConsent/ }));
  expect(generate).not.toBeDisabled();
  fireEvent.click(generate);
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ digitalHumanConsent: true }));
});

it("没挂驱动音频:不出这一格", () => {
  mount([{ asset_id: "face", role: "first_frame" }]);
  expect(document.querySelector("[data-digital-human-consent]")).toBeNull();
});
