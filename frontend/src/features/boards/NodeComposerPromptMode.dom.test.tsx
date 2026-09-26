/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";
import { NodeComposer } from "./NodeComposer";

/**
 * 画板生成格里,提示词要不要写由模型说(描述符的 `prompt`)。不收提示词的模型(放大工作流)不摆编辑器,
 * 空着就能生成,发出去的是空串 —— 格子上存着的旧字不跟着发;可以不写的,编辑器占位说是可选,空着也能生成;
 * 没说的照旧要写。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: [] }) }));
vi.mock("./PromptEditor", () => ({
  PromptEditor: ({ placeholder }: { placeholder?: string }) => <div data-testid="prompt-editor" data-placeholder={placeholder} />,
  restorePromptDocument: vi.fn(),
  textDocument: vi.fn(),
  collect: () => [],
}));

function model(capabilities: Record<string, unknown>): GenerationOption {
  return {
    id: "m", provider_profile_id: "p", profile_name: "ComfyUI", label: "放大", adapter_available: true,
    capabilities_known: true, provider: "plugin:dev.mosael.comfyui", model: "upscale.json", kind: "image", capabilities,
  } as GenerationOption;
}

function renderComposer(capabilities: Record<string, unknown>, text = "") {
  const onSubmit = vi.fn();
  render(<NodeComposer
    item={{ id: "image", kind: "image", text, form: text ? { prompt: text } : undefined } as BoardItem}
    models={[model(capabilities)]}
    busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
  />);
  return onSubmit;
}

it("不收提示词的模型:不摆编辑器,空着就能生成,格子上存着的旧字不跟着发", () => {
  const onSubmit = renderComposer({ parameter_keys: [], prompt: "none" }, "以前写的一句");
  expect(screen.queryByTestId("prompt-editor")).toBeNull();
  expect(screen.getByText("genPromptNotUsed")).toBeInTheDocument();
  const generate = screen.getByRole("button", { name: "boardGenerate" });
  expect(generate).toBeEnabled();
  fireEvent.click(generate);
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ prompt: "", model: "upscale.json" }));
});

it("可以不写的模型:编辑器占位说是可选,空着也能生成", () => {
  const onSubmit = renderComposer({ parameter_keys: [], prompt: "optional" });
  expect(screen.getByTestId("prompt-editor")).toHaveAttribute("data-placeholder", "boardPromptPlaceholderOptional");
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ prompt: "" }));
});

it("没说的照旧要写:空着不能生成", () => {
  const onSubmit = renderComposer({ parameter_keys: [] });
  expect(screen.getByTestId("prompt-editor")).toHaveAttribute("data-placeholder", "boardPromptPlaceholder");
  const generate = screen.getByRole("button", { name: "boardGenerate" });
  expect(generate).toBeDisabled();
  fireEvent.click(generate);
  expect(onSubmit).not.toHaveBeenCalled();
});
