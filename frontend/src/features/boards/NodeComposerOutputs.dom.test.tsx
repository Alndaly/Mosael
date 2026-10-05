/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";
import { NodeComposer } from "./NodeComposer";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: [] }),
  //: 按 id 取引到的素材(useAssetDetails):一份都没取到。
  useQueries: ({ combine }: { combine: (results: unknown[]) => unknown }) => combine([]),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("./PromptEditor", () => ({ PromptEditor: () => <div />, restorePromptDocument: vi.fn(), textDocument: vi.fn(), collect: () => [] }));

/**
 * ComfyUI 的一张工作流有两个保存节点(「原图」「高清」):一次运行各交回一份。插件在描述符里给一项「结果取自」——
 * 选项是节点 id,给人看的是节点标题(`x-enum-labels`),每个选项一次交回几份写在 `x-outputs-per-run` 上。
 */
function twoSaves(extra: Record<string, unknown> = {}): GenerationOption {
  return {
    id: "two", provider_profile_id: "comfy", plugin_instance_id: "", profile_name: "ComfyUI", label: "古风女孩.json · ComfyUI",
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

/**
 * 「N×」只在模型有张数(`num_images`)时出现,上面的数是**这一次会落出几格**:两个保存节点 × 张数。
 * 每个选项的副标题说清楚它调的是每个节点几张;「结果取自」选了一个节点,数就回到 1×–4×。
 */
function batched(): GenerationOption {
  const model = twoSaves();
  return { ...model, capabilities: { ...model.capabilities, parameter_keys: ["num_images", "output_node"], max_num_images: 4 } };
}

it("「N×」按一次会落出几格显示:两个保存节点时是 2×、4×、6×、8×,发出去的是每个节点几张", async () => {
  const { onSubmit } = renderComposer(batched());
  const count = screen.getByRole("combobox", { name: "boardOutputCount" });
  expect(count).toHaveTextContent("2×");
  fireEvent.click(count);
  const options = within(await screen.findByRole("listbox")).getAllByRole("option");
  expect(options.map((one) => one.textContent)).toEqual(
    ["2×", "4×", "6×", "8×"].map((label) => `${label}boardOutputsPerNode`),
  );
  fireEvent.click(options[1]);
  await waitFor(() => expect(screen.getByRole("combobox", { name: "boardOutputCount" })).toHaveTextContent("4×"));
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ parameters: expect.objectContaining({ num_images: 2 }) }));
});

it("「结果取自」选了一个节点:「N×」回到每次一张的数", async () => {
  renderComposer(batched());
  fireEvent.click(screen.getByRole("button", { name: "boardGenerationSettings" }));
  fireEvent.click(await screen.findByRole("combobox", { name: "结果取自" }));
  fireEvent.click(within(await screen.findByRole("listbox")).getByRole("option", { name: "原图" }));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  const count = screen.getByRole("combobox", { name: "boardOutputCount" });
  expect(count).toHaveTextContent("1×");
  fireEvent.click(count);
  expect(within(await screen.findByRole("listbox")).getAllByRole("option").map((one) => one.textContent)).toEqual([
    "1×", "2×", "3×", "4×",
  ]);
});

it("没有张数的模型(视频、没有 batch_size 的工作流)不摆「N×」", () => {
  renderComposer(twoSaves());
  expect(screen.queryByRole("combobox", { name: "boardOutputCount" })).not.toBeInTheDocument();
});

/**
 * 只接了预览节点的两遍出图(维护者的「古风女孩1」):第一遍、从它算出来的控制图、第二遍各一个预览。插件把「结果取自」的
 * 缺省设成「最终结果」(`final`,一次一份),第一遍标着「中间一步」、控制图标着「控制图」;目录里的 `outputs_per_run` 是 1(宿主不写)。
 */
function twoPassPreviews(): GenerationOption {
  const model = twoSaves();
  return {
    ...model,
    label: "古风女孩1.json · ComfyUI",
    model: "古风女孩1.json",
    capabilities: {
      prompt: "optional",
      parameter_keys: ["num_images", "output_node"],
      max_num_images: 4,
      parameter_schema: {
        output_node: {
          type: "string", title: "结果取自", enum: ["final", "all", "8", "17", "18"], default: "final",
          "x-enum-labels": {
            final: "最终结果(PreviewImage #17)", all: "全部(3 个预览节点)",
            "8": "PreviewImage #8(中间一步)", "17": "PreviewImage #17", "18": "PreviewImage #18(控制图)",
          },
          "x-outputs-per-run": { final: 1, all: 3, "8": 1, "17": 1, "18": 1 },
        },
      },
    },
  } as GenerationOption;
}

it("缺省是「最终结果」:「结果取自」写明是哪个节点,「N×」是 1×;选「全部」变成 3×", async () => {
  renderComposer(twoPassPreviews());
  expect(screen.getByRole("combobox", { name: "boardOutputCount" })).toHaveTextContent("1×");
  fireEvent.click(screen.getByRole("button", { name: "boardGenerationSettings" }));
  const pick = await screen.findByRole("combobox", { name: "结果取自" });
  expect(pick).toHaveTextContent("最终结果(PreviewImage #17)");
  fireEvent.click(pick);
  fireEvent.click(within(await screen.findByRole("listbox")).getByRole("option", { name: "全部(3 个预览节点)" }));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByRole("combobox", { name: "boardOutputCount" })).toHaveTextContent("3×");
});

/**
 * ComfyUI 的工作流「张数」是跑几遍(`num_images_unit: "runs"`):画布存着一次 4 张的工作流(真的「古风女孩1」),「N×」是
 * 跑几遍 × 一遍 4 张,每一档的副标题写跑几遍;发出去的是跑几遍。
 */
function runsModel(): GenerationOption {
  const model = twoPassPreviews();
  const schema = (model.capabilities as Record<string, unknown>).parameter_schema as Record<string, Record<string, unknown>>;
  return {
    ...model,
    capabilities: {
      ...model.capabilities,
      num_images_unit: "runs",
      batch_per_run: 4,
      outputs_per_run: 4,
      parameter_schema: {
        output_node: { ...schema.output_node, "x-outputs-per-run": { final: 4, all: 12, "8": 4, "17": 4, "18": 4 } },
      },
    },
  } as GenerationOption;
}

it("张数是跑几遍:「N×」= 跑几遍 × 一遍几张,副标题写跑几遍,发出去的是跑几遍", async () => {
  const { onSubmit } = renderComposer(runsModel());
  const count = screen.getByRole("combobox", { name: "boardOutputCount" });
  expect(count).toHaveTextContent("4×");
  fireEvent.click(count);
  const options = within(await screen.findByRole("listbox")).getAllByRole("option");
  expect(options.map((one) => one.textContent)).toEqual(["4×", "8×", "12×", "16×"].map((label) => `${label}boardOutputsRuns`));
  fireEvent.click(options[1]);
  await waitFor(() => expect(screen.getByRole("combobox", { name: "boardOutputCount" })).toHaveTextContent("8×"));
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ parameters: expect.objectContaining({ num_images: 2 }) }));
});
