/** @vitest-environment jsdom */

/**
 * 应用表单编辑器(ADR 0038 第一刀,1.10.0 重做成「搭一张表单」):工作流库详情里的「编辑应用表单」,和工作台「应用」面板里的同一个
 * 编辑器。数据是 `/workflow-library/app` 给的(这张图全部能填的项、交回结果的输出节点、文件里的标记、读到时的改动时间),这里看的是
 * 怎么搭、怎么存:
 *
 * - 三块:工作流里能填的(按节点分组、人话名字、现在的值、一颗「+」)、表单(卡片)、预览(生成面板那套控件);
 * - 加、拿掉;排序 —— 指针拖手柄、聚焦手柄按 ↑ ↓、设置里的上移下移;就地改名;设置里收窄可选值、当主提示词;
 * - 空着时「按推荐先挑一版」;「结果取自」单独一节:只要这个节点的图 / 撤销;
 * - 失效的项标着原因:能修的一键修(只留还在的可选值),修不了的一键去掉;
 * - 窄的时候(工作台面板)是「挑项 / 表单 / 预览」三个标签;
 * - 存:有没存的修改时说出来、关掉先问;每次存先确认(哪台服务器上的哪个文件),带着读到时的改动时间;那张刚被改过(409 stale)就说清楚、
 *   给「重新打开」;一项都不挑就是去掉应用表单。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getWorkflowApp: vi.fn(),
  annotateWorkflow: vi.fn(),
}));
vi.mock("@/api/client", () => api);
//: 文案用键名 + 一个 {name} 占位:替换进去的名字看得出来,按名字找得到那颗按钮
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => `${key}:{name}`,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { PluginInstance, WorkflowApp, WorkflowFile } from "@/api/client";
import { AppFormEditor } from "@/features/plugins/appForm/AppFormEditor";
import { initialDraft, type AppDraft } from "@/features/plugins/workflowAppForm";
import { WorkflowAppEditor, WorkflowAppSection } from "./WorkflowAppEditor";

const instance = { id: "i1", name: "ComfyUI · 192.168.3.15" } as PluginInstance;
const flow = { path: "换装.json", label: "换装" } as WorkflowFile;

function data(overrides: Partial<WorkflowApp> = {}): WorkflowApp {
  const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "", common: true, exposable: true };
  return {
    path: "换装.json",
    modified: 1776098682.9,
    kind: "image",
    editable: true,
    items: [
      { ...base, key: "6.text", node: "6", input: "text", kind: "text", role: "prompt", title: "提示词", node_label: "CLIP 文本编码",
        class_type: "CLIPTextEncode", spec: { type: "string", "x-multiline": true, default: "a girl" } },
      { ...base, key: "7.text", node: "7", input: "text", kind: "text", role: "negative", title: "反向提示词", node_label: "CLIP 文本编码",
        class_type: "CLIPTextEncode", spec: { type: "string", "x-multiline": true, default: "blurry" } },
      { ...base, key: "10.image", node: "10", input: "image", kind: "media", role: "reference_image", media: "image",
        title: "参考图 · 人物", node_title: "人物", node_label: "人物", class_type: "LoadImage", spec: null },
      { ...base, key: "14.image", node: "14", input: "image", kind: "media", role: "reference_image", media: "image",
        title: "参考图 · 加载图像 #14", node_label: "加载图像", class_type: "LoadImage", spec: null },
      { ...base, key: "seed", node: "", input: "seed", kind: "seed", title: "种子", class_type: "", spec: { type: "integer", minimum: 0 } },
      { ...base, key: "4.ckpt_name", node: "4", input: "ckpt_name", kind: "model", title: "模型", node_label: "Checkpoint 加载器",
        class_type: "CheckpointLoaderSimple", folder: "checkpoints",
        spec: { type: "string", enum: ["a.safetensors", "b.safetensors", "c.safetensors"], default: "a.safetensors",
                "x-model-folder": "checkpoints" } },
      { ...base, key: "13.strength_model", node: "13", input: "strength_model", kind: "number", title: "LoRA 强度",
        node_label: "Lora Loader 🐍", hint: "How strongly to modify the diffusion model.", class_type: "LoraLoader|pysssss",
        spec: { type: "number", default: 0.8 } },
      { ...base, key: "3.steps", node: "3", input: "steps", kind: "number", title: "步数", node_title: "采样", node_label: "采样",
        class_type: "KSampler", spec: { type: "integer", minimum: 1, maximum: 150, default: 20 } },
      { ...base, key: "12:5.cfg", node: "12:5", input: "cfg", kind: "number", title: "CFG", node_label: "K 采样器",
        class_type: "KSampler", exposable: false, spec: { type: "number" } },
    ],
    outputs: [
      { node: "9", title: "SaveImage", label: "保存图像", class_type: "SaveImage", media: "image" },
      { node: "17", title: "高清", label: "高清", class_type: "SaveImage", media: "image" },
    ],
    app: { status: "none", version: "", app: false, title: "", description: "", items: [], results: [], invalid: 0, fields: 0 },
    ...overrides,
  };
}

function mount(onSaved = vi.fn(), onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowAppEditor instance={instance} flow={flow} onClose={onClose} onSaved={onSaved} />
    </QueryClientProvider>,
  );
  return { onSaved, onClose };
}

/** 直接挂编辑器正文(工作台面板那样),草稿在测试里自己管。 */
function Harness({ value, layout }: { value: WorkflowApp; layout?: "auto" | "narrow" }) {
  const [draft, setDraft] = React.useState<AppDraft>(() => initialDraft(value));
  return (
    <>
      <AppFormEditor instance={{ id: "i1" }} data={value} draft={draft} onChange={setDraft} layout={layout} />
      <div hidden data-draft>{JSON.stringify(draft)}</div>
    </>
  );
}

const t = (key: string, name = "{name}") => `${key}:${name}`;
const preview = () => screen.getByRole("complementary", { name: t("workflowAppPreview") });
const chosenKeys = () => Array.from(document.querySelectorAll("[data-app-item]")).map((one) => one.getAttribute("data-app-item"));
const add = (title: string) => fireEvent.click(screen.getByRole("button", { name: t("workflowAppAdd", title) }));
const card = (key: string) => document.querySelector(`[data-app-item='${key}']`) as HTMLElement;
const handle = (key: string) => card(key).querySelector("[data-drag-handle]") as HTMLElement;
const settings = (name: string) => fireEvent.click(screen.getByRole("button", { name: t("workflowAppSettings", name) }));
const announced = () => document.querySelector("[data-app-announce]")?.textContent;
const draftOf = () => JSON.parse(document.querySelector("[data-draft]")?.textContent ?? "{}") as AppDraft;

beforeEach(() => {
  api.getWorkflowApp.mockReset();
  api.annotateWorkflow.mockReset();
});

describe("应用表单编辑器:三块", () => {
  it("工作流里能填的按节点分组、用人话名字、带着现在的值;类名只在悬停的技术名里;子图里的节点灰着", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    mount();
    const source = await screen.findByRole("region", { name: t("workflowAppSource") });
    const lora = within(source).getByRole("list", { name: "Lora Loader 🐍 #13" });
    expect(within(lora).getByText("LoRA 强度")).toBeTruthy();
    expect(within(lora).getByText("0.8"), "现在的值").toBeTruthy();
    expect(within(source).getByRole("list", { name: t("workflowAppGraphGroup") }), "种子这类图级的项自成「整张图」一组").toBeTruthy();
    expect(within(within(source).getByRole("list", { name: "人物 #10" })).getByText("参考图"),
           "组里的名字去掉重复的节点名(组名就是「人物」)").toBeTruthy();
    expect(source.textContent, "类名不当名字").not.toContain("LoraLoader|pysssss");
    const subgraph = screen.getByRole("button", { name: t("workflowAppAdd", "CFG") }) as HTMLButtonElement;
    expect(subgraph.disabled).toBe(true);
    expect(screen.getByRole("button", { name: t("workflowAppSave") }).hasAttribute("disabled")).toBe(true);
    // 空着的表单不是一块死框:说怎么加、给「按推荐先挑一版」;预览画的是现在用的人看到的那张(全部能填的项)
    expect(screen.getByRole("button", { name: /workflowAppRecommend/ })).toBeTruthy();
    expect(within(preview()).getByText(t("workflowAppPreviewDefault"))).toBeTruthy();
    expect(within(preview()).getByText(t("genPromptLabel")), "缺省的应用里认出来的提示词格写进提示词框").toBeTruthy();
  });

  it("加:点「+」放进表单,那一行打勾;再点一下拿掉;卡片上的 × 也能拿掉", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    mount();
    await screen.findByRole("region", { name: t("workflowAppSource") });
    add("步数");
    add("参考图 · 人物");
    expect(chosenKeys()).toEqual(["3.steps", "10.image"]);
    const added = screen.getByRole("button", { name: t("workflowAppAdded", "步数") });
    expect(added.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(added);
    expect(chosenKeys()).toEqual(["10.image"]);
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppRemove", "参考图 · 人物") }));
    expect(chosenKeys()).toEqual([]);
  });

  it("按推荐先挑一版:提示词、反向提示词、主模型、种子、读图的槽位;子图里的不挑,别的不碰", async () => {
    const base = data();
    //: 子图里面一个读图节点:推荐本来会挑读图的槽位,但它这一版放不进表单
    api.getWorkflowApp.mockResolvedValue(data({ items: [...(base.items ?? []), {
      key: "12:7.image", node: "12:7", input: "image", kind: "media", role: "reference_image", media: "image", title: "参考图 · 子图",
      node_title: "", node_label: "加载图像", hint: "", class_type: "LoadImage", common: true, folder: "", exposable: false, spec: null,
    }] }));
    mount();
    const recommend = await screen.findByRole("button", { name: /workflowAppRecommend/ });
    expect(screen.getByText(t("workflowAppRecommendWhat")), "按钮下面写明会挑哪几项").toBeTruthy();
    fireEvent.click(recommend);
    expect(chosenKeys()).toEqual(["6.text", "7.text", "4.ckpt_name", "seed", "10.image", "14.image"]);
    expect(within(card("6.text")).getByText(t("workflowAppMainShort")), "认出来的提示词格是主提示词").toBeTruthy();
    expect(within(preview()).getByText(t("genNegativePrompt"))).toBeTruthy();
    expect(within(preview()).queryByText(t("workflowAppPreviewDefault")), "有表单了:预览是这张表").toBeNull();
  });

  it("起名就地改:预览里的槽位和参数跟着变;主提示词、种子这类用宿主控件的项名字固定", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    mount();
    await screen.findByRole("region", { name: t("workflowAppSource") });
    add("参考图 · 人物");
    add("参考图 · 加载图像 #14");
    add("步数");
    add("提示词");
    add("种子");
    const slots = within(preview()).getByRole("list", { name: t("genReferenceImage") });
    expect(within(slots).getAllByRole("listitem").map((one) => one.textContent), "没起名的用「节点名 #节点」,不是类名")
      .toEqual(["人物", "加载图像 #14"]);
    fireEvent.change(screen.getByRole("textbox", { name: t("workflowAppLabel", "参考图 · 加载图像 #14") }), { target: { value: "背景" } });
    expect(within(slots).getAllByRole("listitem").map((one) => one.textContent)).toEqual(["人物", "背景"]);
    fireEvent.change(screen.getByRole("textbox", { name: t("workflowAppLabel", "步数") }), { target: { value: "精细度" } });
    expect(within(preview()).getByText("精细度")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: t("workflowAppLabel", "提示词") }), "主提示词进宿主的提示词框:名字固定").toBeNull();
    expect(screen.queryByRole("textbox", { name: t("workflowAppLabel", "种子") })).toBeNull();
  });

  it("设置:当不当主提示词(关掉就是表单上一格文字)、收窄可选值;技术名和 ComfyUI 的说明在这里", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    mount();
    await screen.findByRole("region", { name: t("workflowAppSource") });
    add("提示词");
    add("模型");
    add("LoRA 强度");

    settings("LoRA 强度");
    const lora = await screen.findByRole("dialog", { name: t("workflowAppSettings", "LoRA 强度") });
    expect(within(lora).getByText(t("workflowAppTech")), "节点号、类名、输入名给排错用").toBeTruthy();
    expect(within(lora).getByText("How strongly to modify the diffusion model.")).toBeTruthy();
    fireEvent.keyDown(lora, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: t("workflowAppSettings", "LoRA 强度") })).toBeNull());

    settings("提示词");
    const prompt = await screen.findByRole("dialog", { name: t("workflowAppSettings", "提示词") });
    fireEvent.click(within(prompt).getByRole("switch", { name: `${t("workflowAppMain")}: 提示词` }));
    fireEvent.keyDown(prompt, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: t("workflowAppSettings", "提示词") })).toBeNull());
    expect(within(preview()).getByText(t("workflowAppPromptNone")), "主提示词关掉:提示词那几格照工作流原样跑").toBeTruthy();
    expect(screen.getByRole("textbox", { name: t("workflowAppLabel", "提示词") }), "成了单独的一格文字,能起名").toBeTruthy();

    settings("模型");
    const model = await screen.findByRole("dialog", { name: t("workflowAppSettings", "模型") });
    fireEvent.click(within(model).getByRole("checkbox", { name: "b.safetensors" }));
    fireEvent.click(within(model).getByRole("checkbox", { name: "c.safetensors" }));
    expect(within(card("4.ckpt_name")).getByText(t("workflowAppChoices"))).toBeTruthy();
    expect(screen.getByText(t("workflowAppDirty")), "改过了:尾上说有没存的修改").toBeTruthy();
  });
});

describe("排序", () => {
  it("键盘:聚焦手柄按 ↑ ↓ 挪一格,焦点留在挪过去的那一项上、读屏念第几项;设置里也有上移下移", async () => {
    render(<Harness value={data({ app: appWith(["3.steps", "10.image", "seed"]) })} />);
    expect(chosenKeys()).toEqual(["3.steps", "10.image", "seed"]);
    handle("3.steps").focus();
    fireEvent.keyDown(handle("3.steps"), { key: "ArrowDown" });
    expect(chosenKeys()).toEqual(["10.image", "3.steps", "seed"]);
    expect(document.activeElement, "焦点留在挪过去的那一项的手柄上,接着按还能挪").toBe(handle("3.steps"));
    expect(announced()).toBe(t("workflowAppMoved", "步数"));
    fireEvent.keyDown(handle("seed"), { key: "ArrowUp" });
    fireEvent.keyDown(handle("seed"), { key: "ArrowUp" });
    expect(chosenKeys()).toEqual(["seed", "10.image", "3.steps"]);
    fireEvent.keyDown(handle("seed"), { key: "ArrowUp" });
    expect(chosenKeys(), "到头了就不动").toEqual(["seed", "10.image", "3.steps"]);

    settings("步数");
    const panel = await screen.findByRole("dialog", { name: t("workflowAppSettings", "步数") });
    expect((within(panel).getByRole("button", { name: /workflowAppMoveDown/ }) as HTMLButtonElement).disabled, "已经在最后").toBe(true);
    fireEvent.click(within(panel).getByRole("button", { name: /workflowAppMoveUp/ }));
    expect(chosenKeys()).toEqual(["seed", "3.steps", "10.image"]);
  });

  describe("指针", () => {
    const original = Element.prototype.getBoundingClientRect;
    afterEach(async () => {
      Element.prototype.getBoundingClientRect = original;
      //: 拖动库松手后 50ms 内在 document 上吞掉点击(免得松手那一下被当成点击):等它过去,别吞了下一条测试的点击
      await new Promise((done) => setTimeout(done, 80));
    });

    it("按住手柄拖到别的项上松手:挪到那一格(拖动库 @dnd-kit,不靠浏览器的拖放);一下点击不算拖", async () => {
      render(<Harness value={data({ app: appWith(["3.steps", "10.image", "seed"]) })} />);
      //: jsdom 不排版:照竖着一列卡片的样子给每一项一个位置,拖动库按它们找落点
      Element.prototype.getBoundingClientRect = function (this: Element) {
        const owner = this.closest("[data-app-item]");
        const index = owner ? chosenKeys().indexOf(owner.getAttribute("data-app-item")) : -1;
        const top = index < 0 ? 0 : index * 60;
        return { top, left: 0, width: 300, height: 56, right: 300, bottom: top + 56, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
      };
      fireEvent.click(handle("seed"));
      expect(chosenKeys()).toEqual(["3.steps", "10.image", "seed"]);
      fireEvent.pointerDown(handle("seed"), { clientX: 10, clientY: 148, isPrimary: true, button: 0, pointerId: 1 });
      fireEvent.pointerMove(document, { clientX: 10, clientY: 100, pointerId: 1 });
      await waitFor(() => expect(card("seed").className, "挪过起手的距离:拖起来了").toContain("shadow-lg"));
      fireEvent.pointerMove(document, { clientX: 10, clientY: 30, pointerId: 1 });
      await act(async () => {
        await new Promise((done) => setTimeout(done, 20));
      });
      fireEvent.pointerUp(document, { clientX: 10, clientY: 30, pointerId: 1 });
      await waitFor(() => expect(chosenKeys()).toEqual(["seed", "3.steps", "10.image"]));
      expect(announced()).toBe(t("workflowAppMoved", "种子"));
    });
  });
});

/** 文件里已有的应用表单:按这几项起(没起名、没收窄)。 */
function appWith(keys: string[], extra: Partial<NonNullable<WorkflowApp["app"]>> = {}): NonNullable<WorkflowApp["app"]> {
  return {
    status: "ok", version: "", app: true, title: "", description: "", results: [], invalid: 0, fields: keys.length,
    items: keys.map((key) => {
      const [node, input] = key.includes(".") ? key.split(".") : ["", key];
      return { key, node, input, label: "", title: "", main: false, problem: "" };
    }),
    ...extra,
  };
}

describe("结果取自", () => {
  it("说的是节点:只要这个节点的图;标了写「结果取自这个节点」,能撤销", async () => {
    render(<Harness value={data()} />);
    const results = screen.getByRole("region", { name: t("workflowAppResults") });
    expect(within(results).getByText(t("workflowAppResultsHint"))).toBeTruthy();
    expect(within(results).getByText("保存图像 #9"), "节点给人看的名字加节点号").toBeTruthy();
    fireEvent.click(within(results).getByRole("button", { name: t("workflowAppResultsMarkLabel", "高清 #17") }));
    expect(draftOf().results).toEqual(["17"]);
    const marked = results.querySelector("[data-result-node='17']") as HTMLElement;
    expect(within(marked).getByText(t("workflowAppResultsChosen"))).toBeTruthy();
    fireEvent.click(within(marked).getByRole("button", { name: t("workflowAppResultsUndoLabel", "高清 #17") }));
    expect(draftOf().results).toEqual([]);
  });

  it("只有一个出图的节点:没有可挑的,不出这一节", () => {
    render(<Harness value={data({ outputs: [{ node: "9", title: "SaveImage", label: "保存图像", class_type: "SaveImage", media: "image" }] })} />);
    expect(screen.queryByRole("region", { name: t("workflowAppResults") })).toBeNull();
  });
});

describe("失效的项", () => {
  const broken = () => data({
    app: appWith(["10.image", "3.gone", "4.ckpt_name"], {
      invalid: 2,
      items: [
        { key: "10.image", node: "10", input: "image", label: "人物照片", title: "", main: false, problem: "" },
        { key: "3.gone", node: "3", input: "gone", label: "", title: "", main: false, problem: "节点 #3 上没有「gone」这一格了" },
        { key: "4.ckpt_name", node: "4", input: "ckpt_name", label: "", title: "", main: false,
          choices: ["a.safetensors", "old.safetensors"], problem: "可选值「old.safetensors」已经不在下拉里了" },
      ],
    }),
  });

  it("标着原因;可选值不在下拉里了能一键修(只留还在的),节点没了的只能拿掉;也能一次去掉全部失效的", () => {
    render(<Harness value={broken()} />);
    expect(screen.getByRole("alert").textContent).toContain(t("workflowAppInvalidNotice"));
    expect(within(card("3.gone")).getByRole("note").textContent).toContain(t("workflowAppInvalidWhy"));
    expect(within(card("3.gone")).queryByRole("button", { name: /workflowAppFixChoices/ }), "节点上没有这一格了:修不了").toBeNull();
    fireEvent.click(within(card("4.ckpt_name")).getByRole("button", { name: /workflowAppFixChoices/ }));
    const fixed = draftOf().items.find((one) => one.key === "4.ckpt_name");
    expect(fixed?.choices).toEqual(["a.safetensors"]);
    expect(fixed?.problem).toBe("");
    expect(within(card("4.ckpt_name")).queryByRole("note"), "修好了就不再标").toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /workflowAppDropInvalid/ }));
    expect(chosenKeys()).toEqual(["10.image", "4.ckpt_name"]);
  });
});

describe("窄的时候(工作台的「应用」面板)", () => {
  it("挑项 / 表单 / 预览三个标签,缺省在「表单」;在「挑项」里加的项数在「表单」标签上", () => {
    render(<Harness value={data()} layout="narrow" />);
    expect(document.querySelector("[data-app-layout='narrow']")).not.toBeNull();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((one) => one.getAttribute("aria-selected"))).toEqual(["false", "true", "false"]);
    expect(screen.queryByRole("region", { name: t("workflowAppSource") }), "一次只摆一块").toBeNull();
    fireEvent.mouseDown(tabs[0]);
    add("步数");
    expect(tabs[1].textContent).toContain("1");
    fireEvent.mouseDown(tabs[2]);
    expect(within(preview()).getByText("步数")).toBeTruthy();
  });
});

describe("存", () => {
  it("先确认(哪台服务器上的哪个文件),带着读到时的改动时间,写进去的是表单的样子", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    api.annotateWorkflow.mockResolvedValue({ path: "换装.json", modified: 1776098699.5 });
    const { onSaved, onClose } = mount();
    await screen.findByRole("region", { name: t("workflowAppSource") });
    fireEvent.change(screen.getByRole("textbox", { name: t("workflowAppName") }), { target: { value: " 换装 " } });
    expect(screen.getByText(t("workflowAppWhere")), "存在哪用大白话写在头上").toBeTruthy();
    add("参考图 · 人物");
    add("种子");
    add("模型");
    settings("模型");
    const model = await screen.findByRole("dialog", { name: t("workflowAppSettings", "模型") });
    fireEvent.click(within(model).getByRole("checkbox", { name: "c.safetensors" }));
    fireEvent.keyDown(model, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: t("workflowAppSettings", "模型") })).toBeNull());
    fireEvent.change(screen.getByRole("textbox", { name: t("workflowAppLabel", "参考图 · 人物") }), { target: { value: "人物照片" } });
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppResultsMarkLabel", "高清 #17") }));

    fireEvent.click(screen.getByRole("button", { name: t("workflowAppSave") }));
    const confirm = await screen.findByRole("alertdialog");
    expect(within(confirm).getByText(t("workflowAppSaveBody"))).toBeTruthy();
    expect(api.annotateWorkflow).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(within(confirm).getByRole("button", { name: t("workflowAppSaveConfirm") }));
    });
    expect(api.annotateWorkflow).toHaveBeenCalledWith("i1", {
      path: "换装.json",
      modified: 1776098682.9,
      app: {
        title: "换装",
        description: "",
        items: [
          { node: "10", input: "image", label: "人物照片", main: false, choices: null },
          { node: "", input: "seed", label: "", main: false, choices: null },
          { node: "4", input: "ckpt_name", label: "", main: false, choices: ["c.safetensors"] },
        ],
      },
      results: ["17"],
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  it("有没存的修改时关掉:先问放弃不放弃;没改过直接关", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    const { onClose } = mount();
    await screen.findByRole("region", { name: t("workflowAppSource") });
    fireEvent.click(screen.getByRole("button", { name: t("cancel") }));
    expect(onClose).toHaveBeenCalledTimes(1);
    add("步数");
    fireEvent.click(screen.getByRole("button", { name: t("cancel") }));
    const ask = await screen.findByRole("alertdialog");
    expect(within(ask).getByText(t("workflowAppDiscardTitle"))).toBeTruthy();
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(within(ask).getByRole("button", { name: t("workflowAppDiscardConfirm") }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("那张刚在 ComfyUI 里改过(409 stale):不存,说清楚,给「重新打开」", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    api.annotateWorkflow.mockRejectedValue(Object.assign(new Error("stale"), {
      status: 409, body: JSON.stringify({ detail: { code: "stale", message: "x", modified: 2 } }),
    }));
    const { onSaved } = mount();
    await screen.findByRole("region", { name: t("workflowAppSource") });
    add("步数");
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppSave") }));
    await act(async () => {
      fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: t("workflowAppSaveConfirm") }));
    });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(t("workflowAppStale", "换装"));
    expect(onSaved).not.toHaveBeenCalled();
    fireEvent.click(within(alert).getByRole("button", { name: t("workflowAppReload") }));
    await waitFor(() => expect(api.getWorkflowApp).toHaveBeenCalledTimes(2));
  });

  it("文件里已有的表单照它起;一项都不剩就是去掉应用表单(结果标记留着)", async () => {
    api.getWorkflowApp.mockResolvedValue(data({ app: appWith(["10.image"], { title: "换装", results: ["9"] }) }));
    api.annotateWorkflow.mockResolvedValue({ path: "换装.json", modified: 2 });
    mount();
    await waitFor(() => expect(chosenKeys()).toEqual(["10.image"]));
    expect((screen.getByRole("textbox", { name: t("workflowAppName") }) as HTMLInputElement).value).toBe("换装");
    expect(screen.getByText(t("workflowAppResultsChosen"))).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppRemove", "参考图 · 人物") }));
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppSave") }));
    const confirm = await screen.findByRole("alertdialog");
    expect(within(confirm).getByText(t("workflowAppSaveRemoveBody"))).toBeTruthy();
    await act(async () => {
      fireEvent.click(within(confirm).getByRole("button", { name: t("workflowAppSaveConfirm") }));
    });
    expect(api.annotateWorkflow).toHaveBeenCalledWith("i1", { path: "换装.json", modified: 1776098682.9, app: null, results: ["9"] });
  });

  it("版本不认识、API 格式的文件:说清楚;API 格式的存不了", async () => {
    api.getWorkflowApp.mockResolvedValue(data({
      editable: false,
      app: { status: "unsupported", version: "2", app: false, title: "", description: "", items: [], results: [], invalid: 0, fields: 0 },
    }));
    mount();
    expect(await screen.findByText(t("workflowAppUnsupported"))).toBeTruthy();
    expect(screen.getByText(t("workflowAppNotEditable"))).toBeTruthy();
    add("步数");
    expect(screen.getByRole("button", { name: t("workflowAppSave") }).hasAttribute("disabled")).toBe(true);
  });
});

describe("工作流库详情里的「应用」", () => {
  function section(app: WorkflowFile["app"], onEdit = vi.fn(), onSaved = vi.fn()) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <WorkflowAppSection instance={instance} flow={{ ...flow, app } as WorkflowFile} onEdit={onEdit} onSaved={onSaved} />
      </QueryClientProvider>,
    );
    return { onEdit, onSaved };
  }

  it("有应用表单:标题、挑了哪几项、结果取自哪个节点;「编辑应用表单」打开编辑器", () => {
    const { onEdit } = section({
      status: "ok", version: "", app: true, title: "换装", description: "上传人物", results: ["17"], invalid: 0, fields: 2,
      items: [{ key: "10.image", node: "10", input: "image", label: "人物照片", title: "", main: false, problem: "" },
              { key: "3.steps", node: "3", input: "steps", label: "", title: "步数", main: false, problem: "" }],
    });
    const list = screen.getByRole("list", { name: t("workflowAppChosen") });
    expect(within(list).getAllByRole("listitem").map((one) => one.textContent)).toEqual(["人物照片", "步数"]);
    expect(screen.getByText("换装")).toBeTruthy();
    expect(screen.getByText(t("workflowAppResultsMarked"))).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppEdit") }));
    expect(onEdit).toHaveBeenCalled();
  });

  it("没有应用表单就说生成表单列出全部;插件没说就不出这一节", () => {
    section({ status: "none", version: "", app: false, title: "", description: "", items: [], results: [], invalid: 0, fields: 0 });
    expect(screen.getByText(t("workflowAppNone"))).toBeTruthy();
  });

  it("对不上的项:列出来,一键去掉(先确认)—— 重新读一遍、只去掉失效的那几项", async () => {
    api.getWorkflowApp.mockResolvedValue(data({
      app: {
        status: "ok", version: "", app: true, title: "", description: "", results: ["9", "99"], invalid: 2, fields: 1,
        items: [{ key: "10.image", node: "10", input: "image", label: "人物", title: "", main: false, problem: "" },
                { key: "3.gone", node: "3", input: "gone", label: "", title: "", main: false, problem: "没有这一格了" }],
      },
    }));
    api.annotateWorkflow.mockResolvedValue({ path: "换装.json", modified: 2 });
    const { onSaved } = section({
      status: "ok", version: "", app: true, title: "", description: "", results: ["9", "99"], invalid: 2, fields: 1,
      items: [{ key: "10.image", node: "10", input: "image", label: "人物", title: "", main: false, problem: "" },
              { key: "3.gone", node: "3", input: "gone", label: "", title: "", main: false, problem: "没有这一格了" }],
    });
    expect(screen.getByRole("alert").textContent).toContain(t("workflowAppInvalidCount"));
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppDropInvalidSaved") }));
    await act(async () => {
      fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: t("workflowAppSaveConfirm") }));
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(api.annotateWorkflow).toHaveBeenCalledWith("i1", {
      path: "换装.json", modified: 1776098682.9, results: ["9"],
      app: { title: "", description: "", items: [{ node: "10", input: "image", label: "人物", main: false, choices: null }] },
    });
  });
});
