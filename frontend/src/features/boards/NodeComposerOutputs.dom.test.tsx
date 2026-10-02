/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";
import { NodeComposer } from "./NodeComposer";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: [] }) }));
vi.mock("./PromptEditor", () => ({ PromptEditor: () => <div />, restorePromptDocument: vi.fn(), textDocument: vi.fn(), collect: () => [] }));

/**
 * ComfyUI 的一张工作流有两个保存节点(「原图」「高清」):一次运行各交回一份。插件在描述符里给一项「结果取自」——
 * 选项是节点 id,给人看的是节点标题(`x-enum-labels`),每个选项一次交回几份写在 `x-outputs-per-run` 上。
 */
function twoSaves(extra: Record<string, unknown> = {}): GenerationOption {
  return {
    id: "two", provider_profile_id: "comfy", profile_name: "ComfyUI", label: "古风女孩.json · ComfyUI",
    adapter_available: true, is_default: true, capabilities_known: true, provider: "plugin:dev.mosael.comfyui",
    model: "古风女孩.json", kind: "image",
    capabilities: {
      prompt: "optional",
      parameter_keys: ["output_node"],
      outputs_per_run: 2,
      parameter_schema: {
        output_node: {
          type: "string", title: "结果取自", enum: ["all", "9", "12"], default: "all",
          "x-enum-labels": { all: "全部(2 个保存节点)", "9": "原图", "12": "高清" },
          "x-outputs-per-run": { all: 2, "9": 1, "12": 1 },
        },
      },
      ...extra,
    },
  } as GenerationOption;
}

function renderComposer(model: GenerationOption, onSubmit = vi.fn(), onFormChange = vi.fn()) {
  HTMLElement.prototype.scrollIntoView = vi.fn();
  render(<NodeComposer
    item={{ id: "image", kind: "image", text: "" } as BoardItem}
    models={[model]}
    busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={onFormChange} onSubmit={onSubmit}
  />);
  return { onSubmit, onFormChange };
}

it("「结果取自」列出每个保存节点的标题,缺省是「全部」;选了一个就只发它", async () => {
  const { onSubmit, onFormChange } = renderComposer(twoSaves());
  fireEvent.click(screen.getByRole("button", { name: "boardGenerationSettings" }));
  const pick = await screen.findByRole("combobox", { name: "结果取自" });
  expect(pick).toHaveTextContent("全部(2 个保存节点)");
  fireEvent.click(pick);
  const listbox = await screen.findByRole("listbox");
  expect(within(listbox).getAllByRole("option").map((one) => one.textContent)).toEqual([
    expect.stringContaining("全部(2 个保存节点)"), "原图", "高清",
  ]);
  fireEvent.click(within(listbox).getByRole("option", { name: "高清" }));
  await waitFor(() => expect(onFormChange).toHaveBeenLastCalledWith(
    expect.objectContaining({ parameters: expect.objectContaining({ output_node: "12" }) }),
  ));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ parameters: expect.objectContaining({ output_node: "12" }) }));
});

it("只有一个保存节点(插件不给「结果取自」)时参数里没有这一项", async () => {
  const single = twoSaves({ parameter_keys: ["3.steps"], outputs_per_run: undefined,
    parameter_schema: { "3.steps": { type: "integer", title: "步数", default: 20 } } });
  renderComposer(single);
  fireEvent.click(screen.getByRole("button", { name: "boardGenerationSettings" }));
  await screen.findByRole("dialog");
  expect(screen.queryByRole("combobox", { name: "结果取自" })).not.toBeInTheDocument();
});
