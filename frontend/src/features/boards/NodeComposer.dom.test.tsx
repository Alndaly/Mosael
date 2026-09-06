/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";
import { NodeComposer } from "./NodeComposer";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: [] }) }));
vi.mock("./PromptEditor", () => ({ PromptEditor: () => <div />, restorePromptDocument: vi.fn(), collect: () => [] }));

it("edits parameters in the settings popup, persists them after closing, and submits those values", async () => {
  HTMLElement.prototype.scrollIntoView = vi.fn();
  const onSubmit = vi.fn();
  const onFormChange = vi.fn();
  render(<NodeComposer
    item={{ id: "video", kind: "video", text: "A sunrise" } as BoardItem}
    models={[{ id: "model", provider_profile_id: "profile", profile_name: "Test", label: "Video", adapter_available: true, provider: "test", model: "a-long-video-model-name", kind: "video", capabilities: {
      parameter_keys: ["aspect_ratio", "generate_audio"], aspect_ratios: ["16:9", "9:16"], default_aspect_ratio: "16:9",
    } } as GenerationOption]}
    busy={false} workspaceId="test" onPickAsset={vi.fn()} onFormChange={onFormChange} onSubmit={onSubmit}
  />);
  expect(screen.queryByRole("combobox", { name: "wfGenAspectRatio" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "boardGenerationSettings" }));
  fireEvent.click(await screen.findByRole("combobox", { name: "wfGenAspectRatio" }));
  fireEvent.click(await screen.findByRole("option", { name: "9:16" }));
  await waitFor(() => expect(onFormChange).toHaveBeenLastCalledWith(expect.objectContaining({ parameters: expect.objectContaining({ aspect_ratio: "9:16" }) })));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ parameters: expect.objectContaining({ aspect_ratio: "9:16" }) }));
});
