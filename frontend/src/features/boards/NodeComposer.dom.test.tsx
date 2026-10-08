/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

it("edits parameters in the settings popup, persists them after closing, and submits those values", async () => {
  HTMLElement.prototype.scrollIntoView = vi.fn();
  const onSubmit = vi.fn();
  const onFormChange = vi.fn();
  render(<NodeComposer
    item={{ id: "video", kind: "video", text: "A sunrise" } as BoardItem}
    models={[{ id: "model", provider_profile_id: "profile", plugin_instance_id: "", profile_name: "Test", adapter_available: true, is_default: true, capabilities_known: true, provider: "test", model: "a-long-video-model-name", model_label: "a-long-video-model-name", kind: "video", capabilities: {
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

it("把模型旁那枚图标画在触发器里面 —— 装饰和控件必须是同一个盒子", () => {
  // 图标曾经和触发器并排放在一个只负责 hover 底色的 span 里。于是这一格有了两个盒子:
  // 悬停高亮的是外层(左边紧贴图标、没有内边距),聚焦时的环却只圈住触发器(把图标排除在外)。
  // 同一个控件高亮出两个大小不同的方框,左右内边距还不对称。
  //
  // 断言「图标在 combobox 里面」而不是「外面没有 span」:后者换个写法就绕过去了,而前者
  // 正是那两个高亮框合成一个的充分条件 —— 内边距、hover、焦点环都由触发器这一个盒子出。
  render(<NodeComposer
    item={{ id: "video", kind: "video", text: "A sunrise" } as BoardItem}
    models={[{ id: "model", provider_profile_id: "profile", profile_name: "Test", adapter_available: true, is_default: true, capabilities_known: true, provider: "test", model: "a-long-video-model-name", model_label: "a-long-video-model-name", kind: "video", capabilities: {} } as GenerationOption]}
    busy={false} workspaceId="test" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={vi.fn()}
  />);
  const trigger = screen.getAllByRole("combobox").find((one) => one.textContent?.includes("a-long-video-model-name"));
  expect(trigger).toBeDefined();
  expect(trigger!.querySelector("svg.lucide-sparkles")).not.toBeNull();
  // 左右内边距由触发器自己出,两侧同一个值 —— 这正是「左侧边距明显不对」的那一处。
  expect(trigger!.className).toContain("px-2");
});

it("认不出参数时要出声,而不是和「确实没有参数」一样静默", async () => {
  // 两种零。「这个模型确实没有可调参数」不摆按钮是对的 —— 点开是个只有标题的空盒子。
  // 但「我们不认识这个模型」多半**有**参数,只是目录里查不到(手填的别名、经另一条中转配的
  // 同一个模型)。两者都静默的话,用户会以为这个模型就是没参数 —— 今天就是这么错的。
  const model = (known: boolean) => ({
    id: "m", provider_profile_id: "p", plugin_instance_id: "", profile_name: "T", label: "L",
    adapter_available: true, is_default: true, capabilities_known: known,
    provider: "test", model: "some-image-model", model_label: "some-image-model", kind: "image", capabilities: { parameter_keys: [] },
  } as GenerationOption);
  const props = {
    item: { id: "image", kind: "image", text: "x" } as BoardItem,
    busy: false, workspaceId: "w", onPickAsset: vi.fn(), onFormChange: vi.fn(), onSubmit: vi.fn(),
  };

  const unknown = render(<NodeComposer {...props} models={[model(false)]} />);
  expect(screen.getByText("boardGenerationUnknownParams")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "boardGenerationSettings" })).not.toBeInTheDocument();
  unknown.unmount();

  // 认得出、但这个模型真的没有可调参数:什么都不说,也不摆按钮。
  render(<NodeComposer {...props} models={[model(true)]} />);
  expect(screen.queryByText("boardGenerationUnknownParams")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "boardGenerationSettings" })).not.toBeInTheDocument();
});

it("存着的模型已经不在可选清单里时,选择器显示的就是实际要用的那一个(用户设的默认)", () => {
  // 节点表单记着上次用的模型,而那个模型后来被删了(或那条通道被停了、不再被认成这种生成)。
  // 提交时用的是用户设的默认,选择器却还挂着那个已经不存在的值 —— 显示的和发出去的不是同一个模型。
  const onSubmit = vi.fn();
  render(<NodeComposer
    item={{ id: "video", kind: "video", text: "A sunrise", form: { prompt: "A sunrise", provider_profile_id: "gone", model: "retired-model" } } as BoardItem}
    models={[{ id: "model", provider_profile_id: "profile", profile_name: "Test", adapter_available: true, is_default: true, capabilities_known: true, provider: "test", model: "a-long-video-model-name", model_label: "a-long-video-model-name", kind: "video", capabilities: {} } as GenerationOption]}
    busy={false} workspaceId="test" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
  />);

  const trigger = screen.getAllByRole("combobox").find((one) => one.textContent?.includes("a-long-video-model-name"));
  expect(trigger).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ model: "a-long-video-model-name" }));
});

it("没设默认模型时不拿清单第一项顶上:显示「选择模型」,选了才发得出去", () => {
  // 清单按连接名排序,第一项不是谁的选择 —— 画板的出图格就是这么默认挑中了 147ai 上的
  // claude-opus-4-6,而用户在设置里设过的默认生图模型被晾在一边。
  const onSubmit = vi.fn();
  const option = (model: string) => ({
    id: model, provider_profile_id: "relay", profile_name: "147ai",
    adapter_available: true, is_default: false, capabilities_known: true,
    provider: "openai-compatible", model, model_label: model, kind: "image", capabilities: {},
  } as GenerationOption);
  render(<NodeComposer
    item={{ id: "image", kind: "image", text: "一只猫" } as BoardItem}
    models={[option("aaa-first-by-name"), option("my-flux")]}
    busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
  />);
  const trigger = screen.getAllByRole("combobox").find((one) => one.textContent?.includes("genPickModel"));
  expect(trigger).toBeDefined();
  expect(screen.queryByText(/aaa-first-by-name/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).not.toHaveBeenCalled();
});

it("目录没给取值时,用户没填就一个值都不提交", async () => {
  // 这条盯的是整件事的要害。曾经的链条是:兜底给出 duration_seconds 这个键 → 界面渲染时长
  // → 没有可选值也没有默认值 → defaultDuration 编一个 5 → 提交带上 duration_seconds: 5
  // → 适配器 `if ... is not None` 成立 → 发出 5 秒。用户一项都没选,成片却是 5 秒。
  //
  // 现在这些项渲染成自由输入:**摆出来,但在用户填之前不带任何值**。
  const onSubmit = vi.fn();
  render(<NodeComposer
    item={{ id: "video", kind: "video", text: "一段风景" } as BoardItem}
    models={[{
      id: "m", provider_profile_id: "p", plugin_instance_id: "", profile_name: "T", label: "L",
      adapter_available: true, is_default: true, capabilities_known: false,
      provider: "relay", model: "上游昨天刚上的型号", model_label: "上游昨天刚上的型号", kind: "video",
      capabilities: { parameter_keys: ["size", "resolution", "aspect_ratio", "duration_seconds"] },
    } as GenerationOption]}
    busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
  />);

  // 「参数」按钮要在 —— 这些项点得开,而不是看起来像"这个模型没参数"。
  expect(screen.getByRole("button", { name: "boardGenerationSettings" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledTimes(1);
  const { parameters } = onSubmit.mock.calls[0][0] as { parameters: Record<string, unknown> };
  for (const key of ["size", "resolution", "aspect_ratio", "duration_seconds"]) {
    expect(parameters).not.toHaveProperty(key);
  }
});

it("尺寸只是推荐值时可以手填 —— 768x1024 照写的发出去", async () => {
  // 用户拍板:ComfyUI 的工作流尺寸放开成任意宽高,推荐的几档还在下拉里,手填的也收(写法不对的不收)。
  HTMLElement.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  const onSubmit = vi.fn();
  render(<NodeComposer
    item={{ id: "image", kind: "image", text: "一只猫" } as BoardItem}
    models={[{
      id: "m", provider_profile_id: "p", plugin_instance_id: "", profile_name: "ComfyUI", label: "girl", adapter_available: true, is_default: true,
      capabilities_known: true, provider: "plugin:dev.mosael.comfyui", model: "girl.json", model_label: "girl.json", kind: "image",
      capabilities: { parameter_keys: ["size"], sizes: ["1280x1920", "512x512"], default_size: "1280x1920",
        custom_size: { minimum: 16, multiple_of: 8 } },
    } as GenerationOption]}
    busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
  />);
  fireEvent.click(screen.getByRole("button", { name: "boardGenerationSettings" }));
  fireEvent.click(await screen.findByRole("combobox", { name: "wfGenSize" }));
  const typing = await screen.findByPlaceholderText("genSizeCustomPlaceholder");
  fireEvent.change(typing, { target: { value: "8x8" } });
  expect(screen.queryByRole("option", { name: "comboboxUseCustomValue" })).not.toBeInTheDocument();
  fireEvent.change(typing, { target: { value: "768 × 1024" } });
  fireEvent.click(await screen.findByRole("option", { name: "comboboxUseCustomValue" }));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ parameters: expect.objectContaining({ size: "768x1024" }) }));
});

it("模型下拉按工作流分组:小标题工作流名 + 连接名,下面「完整工作流」和表单;搜表单标题整组留着、命中的那行加粗", async () => {
  // 维护者(ADR 0045):起了「快速用krea2生图」,到处只叫表单名 —— 认不出是哪张图,也拿不到全部参数。现在同一张工作流是一小组:
  // 小标题写工作流名和哪台服务器,下面「完整工作流」(全部参数)和每张表单各一行;触发器上写主名
  HTMLElement.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  const group = { id: "krea2-text-2-image.json", label: "krea2-text-2-image" };
  const option = (model: string, name: string, extra: Partial<GenerationOption>) => ({
    id: `p:image:${model}`, provider_profile_id: "p", plugin_instance_id: "", profile_name: "ComfyUI · http://192.168.3.15:8188",
    adapter_available: true, is_default: false, capabilities_known: true, provider: "plugin:dev.mosael.comfyui", model,
    model_label: name, kind: "image", capabilities: { prompt: "optional", parameter_keys: [] }, ...extra,
  } as GenerationOption);
  render(<NodeComposer
    item={{ id: "image", kind: "image", text: "" } as BoardItem}
    models={[
      option("krea2-text-2-image.json", "krea2-text-2-image", { group: { ...group, entry: "full", order: 0 } }),
      option("krea2-text-2-image.json#app", "快速用krea2生图", { group: { ...group, entry: "form", order: 1 }, is_default: true }),
      ...Array.from({ length: 11 }, (_, index) => option(`flow-${index}.json`, `工作流 ${index}`, {})),
    ]}
    busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={vi.fn()}
  />);
  const picker = screen.getAllByRole("combobox").find((one) => one.querySelector("svg.lucide-sparkles"))!;
  expect(picker.textContent).toContain("快速用krea2生图");
  expect(picker.textContent).not.toContain(".json");
  //: 触发器只写主名,第二行只在清单里
  expect(picker.textContent).not.toContain("ComfyUI ·");
  fireEvent.click(picker);
  const search = await waitFor(() => {
    const input = document.querySelector<HTMLInputElement>("[role=dialog] input, [role=listbox] input, input[cmdk-input]");
    expect(input).not.toBeNull();
    return input!;
  });
  const form = await screen.findByRole("option", { name: /快速用krea2生图/ });
  expect(form).toHaveAttribute("data-indent");
  const head = document.querySelector("[data-section-head]") as HTMLElement;
  expect(head.textContent, "小标题:工作流名和哪台服务器").toBe("krea2-text-2-imageComfyUI · http://192.168.3.15:8188");
  expect(screen.getByRole("option", { name: /^entryFullWorkflow/ }).getAttribute("data-section")).toBe(form.getAttribute("data-section"));
  const named = (rows: HTMLElement[]) => rows.map((one) => one.textContent);
  fireEvent.change(search, { target: { value: "快速" } });
  await waitFor(() => expect(named(screen.getAllByRole("option")), "搜表单标题:整组留着(完整工作流也在)")
    .toEqual(["entryFullWorkflow", "快速用krea2生图"]));
  expect(screen.getByRole("option", { name: /快速用krea2生图/ })).toHaveAttribute("data-hit");
  expect(screen.getByRole("option", { name: /^entryFullWorkflow/ })).not.toHaveAttribute("data-hit");
  fireEvent.change(search, { target: { value: "krea2-text" } });
  await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(2));
});
