/** @vitest-environment jsdom */

/**
 * 应用表单编辑器(ADR 0038 第一刀):工作流库详情里的「应用」。数据是 `/workflow-library/app` 给的(这张图全部能填的项、
 * 交回结果的输出节点、文件里的标记、读到时的改动时间),这里看的是怎么编、怎么存:
 *
 * - 勾选放进表单、起名、上下挪、当主提示词、收窄可选值;子图里面的节点灰着、说为什么;
 * - 右边的预览和生成面板同一套控件:主提示词有框、槽位按顺序带名字、参数用作者起的名字、收窄后的下拉只剩那几项;
 * - 标成结果的输出节点;对不上的项标着原因,能一键去掉;
 * - 存:每次先确认(写明哪台服务器上的哪个文件、只改这几处标记),带着读到时的改动时间;那张刚被改过(409 stale)就说清楚、
 *   给「重新打开」;一项都不挑就是去掉应用表单。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
import { WorkflowAppEditor, WorkflowAppSection } from "./WorkflowAppEditor";

const instance = { id: "i1", name: "ComfyUI · 192.168.3.15" } as PluginInstance;
const flow = { path: "换装.json", label: "换装" } as WorkflowFile;

function data(overrides: Partial<WorkflowApp> = {}): WorkflowApp {
  return {
    path: "换装.json",
    modified: 1776098682.9,
    kind: "image",
    editable: true,
    items: [
      { key: "6.text", node: "6", input: "text", kind: "text", role: "prompt", title: "提示词", node_title: "", class_type: "CLIPTextEncode",
        common: true, media: "", folder: "", exposable: true, spec: { type: "string", "x-multiline": true, default: "a girl" } },
      { key: "7.text", node: "7", input: "text", kind: "text", role: "negative", title: "反向提示词", node_title: "", class_type: "CLIPTextEncode",
        common: true, media: "", folder: "", exposable: true, spec: { type: "string", "x-multiline": true, default: "blurry" } },
      { key: "10.image", node: "10", input: "image", kind: "media", role: "reference_image", media: "image", title: "参考图 · 人物",
        node_title: "人物", class_type: "LoadImage", common: true, folder: "", exposable: true, spec: null },
      { key: "14.image", node: "14", input: "image", kind: "media", role: "reference_image", media: "image", title: "参考图 · LoadImage #14",
        node_title: "", class_type: "LoadImage", common: true, folder: "", exposable: true, spec: null },
      { key: "seed", node: "", input: "seed", kind: "seed", title: "种子", node_title: "", class_type: "", common: true, role: "", media: "",
        folder: "", exposable: true, spec: { type: "integer", minimum: 0 } },
      { key: "4.ckpt_name", node: "4", input: "ckpt_name", kind: "model", title: "模型", node_title: "", class_type: "CheckpointLoaderSimple",
        common: true, role: "", media: "", folder: "checkpoints", exposable: true,
        spec: { type: "string", enum: ["a.safetensors", "b.safetensors", "c.safetensors"], default: "a.safetensors",
                "x-model-folder": "checkpoints" } },
      { key: "3.steps", node: "3", input: "steps", kind: "number", title: "步数", node_title: "采样", class_type: "KSampler", common: true,
        role: "", media: "", folder: "", exposable: true, spec: { type: "integer", minimum: 1, maximum: 150, default: 20 } },
      { key: "12:5.cfg", node: "12:5", input: "cfg", kind: "number", title: "CFG", node_title: "", class_type: "KSampler", common: true,
        role: "", media: "", folder: "", exposable: false, spec: { type: "number" } },
    ],
    outputs: [
      { node: "9", title: "SaveImage", class_type: "SaveImage", media: "image" },
      { node: "17", title: "高清", class_type: "SaveImage", media: "image" },
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

const t = (key: string, name = "{name}") => `${key}:${name}`;
const preview = () => screen.getByRole("complementary", { name: t("workflowAppPreview") });
const chosenKeys = () => Array.from(document.querySelectorAll("[data-app-item]")).map((one) => one.getAttribute("data-app-item"));
const add = (title: string) => fireEvent.click(screen.getByRole("checkbox", { name: t("workflowAppAdd", title) }));

beforeEach(() => {
  api.getWorkflowApp.mockReset();
  api.annotateWorkflow.mockReset();
});

describe("应用表单编辑器", () => {
  it("没有应用表单时从空的起:列出全部能填的项,子图里的节点灰着", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    mount();
    expect(await screen.findByText(t("workflowAppChosenEmpty"))).toBeTruthy();
    expect(within(preview()).getByText(t("workflowAppPreviewEmpty"))).toBeTruthy();
    for (const group of ["text", "media", "model", "params", "graph"]) {
      expect(screen.getByRole("list", { name: t(`workflowAppGroup_${group}`) })).toBeTruthy();
    }
    const subgraph = screen.getByRole("checkbox", { name: t("workflowAppAdd", "CFG") }) as HTMLButtonElement;
    expect(subgraph.disabled).toBe(true);
    expect(screen.getByRole("button", { name: t("workflowAppSave") }).hasAttribute("disabled")).toBe(true);
  });

  it("挑进来、起名、挪顺序、收窄可选值:右边的预览跟着变,用的是生成面板那套控件", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    mount();
    await screen.findByText(t("workflowAppChosenEmpty"));
    add("参考图 · 人物");
    add("参考图 · LoadImage #14");
    add("提示词");
    add("模型");
    add("步数");
    expect(chosenKeys()).toEqual(["10.image", "14.image", "6.text", "4.ckpt_name", "3.steps"]);

    // 认出来的提示词格缺省就是主提示词:预览里是提示词框;反向提示词没挑就没有
    expect(within(preview()).getByText(t("genPromptLabel"))).toBeTruthy();
    expect(within(preview()).queryByText(t("genNegativePrompt"))).toBeNull();
    // 槽位按顺序带名字:起了名的节点用它的名字,没起名的用「类名 #节点」
    const slots = within(preview()).getByRole("list", { name: t("genReferenceImage") });
    expect(within(slots).getAllByRole("listitem").map((one) => one.textContent)).toEqual(["人物", "LoadImage #14"]);

    fireEvent.change(screen.getByRole("textbox", { name: t("workflowAppLabel", "参考图 · LoadImage #14") }),
                     { target: { value: "背景" } });
    expect(within(slots).getAllByRole("listitem").map((one) => one.textContent)).toEqual(["人物", "背景"]);

    fireEvent.change(screen.getByRole("textbox", { name: t("workflowAppLabel", "步数") }), { target: { value: "精细度" } });
    expect(within(preview()).getByText("精细度")).toBeTruthy();

    // 下移第一项、上移最后一项
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppMoveDown", "参考图 · 人物") }));
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppMoveUp", "精细度") }));
    expect(chosenKeys()).toEqual(["14.image", "10.image", "6.text", "3.steps", "4.ckpt_name"]);

    // 收窄可选值:只许挑 b
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppChoicesAll") }));
    fireEvent.click(screen.getByRole("checkbox", { name: "b.safetensors" }));
    expect(screen.getByRole("button", { name: t("workflowAppChoices") })).toBeTruthy();

    // 主提示词勾掉:预览里没有提示词框了,提示词那几格照工作流原样跑
    fireEvent.click(screen.getByRole("checkbox", { name: t("workflowAppMain", "提示词") }));
    expect(within(preview()).getByText(t("workflowAppPromptNone"))).toBeTruthy();
  });

  it("存:先确认(哪台服务器上的哪个文件、只改标记),带着读到时的改动时间,写进去的是表单的样子", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    api.annotateWorkflow.mockResolvedValue({ path: "换装.json", modified: 1776098699.5 });
    const { onSaved, onClose } = mount();
    await screen.findByText(t("workflowAppChosenEmpty"));
    fireEvent.change(screen.getByRole("textbox", { name: t("workflowAppName") }), { target: { value: " 换装 " } });
    add("参考图 · 人物");
    add("种子");
    add("模型");
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppChoicesAll") }));
    fireEvent.click(screen.getByRole("checkbox", { name: "c.safetensors" }));
    fireEvent.change(screen.getByRole("textbox", { name: t("workflowAppLabel", "参考图 · 人物") }), { target: { value: "人物照片" } });
    fireEvent.click(screen.getByRole("checkbox", { name: t("workflowAppResultsMark", "高清") }));

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

  it("那张刚在 ComfyUI 里改过(409 stale):不存,说清楚,给「重新打开」", async () => {
    api.getWorkflowApp.mockResolvedValue(data());
    api.annotateWorkflow.mockRejectedValue(Object.assign(new Error("stale"), {
      status: 409, body: JSON.stringify({ detail: { code: "stale", message: "x", modified: 2 } }),
    }));
    const { onSaved } = mount();
    await screen.findByText(t("workflowAppChosenEmpty"));
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

  it("文件里已有的表单照它起;对不上的项标着原因,能一键去掉;一项都不剩就是去掉应用表单", async () => {
    api.getWorkflowApp.mockResolvedValue(data({
      app: {
        status: "ok", version: "", app: true, title: "换装", description: "", results: ["9"], invalid: 1, fields: 1,
        items: [
          { key: "10.image", node: "10", input: "image", label: "人物照片", title: "", main: false, problem: "" },
          { key: "3.gone", node: "3", input: "gone", label: "", title: "", main: false, problem: "节点 #3 上没有「gone」这一格了" },
        ],
      },
    }));
    api.annotateWorkflow.mockResolvedValue({ path: "换装.json", modified: 2 });
    mount();
    await waitFor(() => expect(chosenKeys()).toEqual(["10.image", "3.gone"]));
    expect(screen.getByText(t("workflowAppInvalidWhy"))).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: t("workflowAppResultsMark", "SaveImage #9") }) as HTMLButtonElement)
      .getAttribute("data-state")).toBe("checked");
    expect(within(preview()).getByText("人物照片")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: t("workflowAppDropInvalid") }));
    expect(chosenKeys()).toEqual(["10.image"]);
    fireEvent.click(screen.getByRole("button", { name: t("workflowAppRemove", "人物照片") }));
    expect(chosenKeys()).toEqual([]);

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

  it("有应用表单:标题、挑了哪几项、标成结果的节点;「编辑应用表单」打开编辑器", () => {
    const { onEdit } = section({
      status: "ok", version: "", app: true, title: "换装", description: "上传人物", results: ["17"], invalid: 0, fields: 2,
      items: [{ key: "10.image", node: "10", input: "image", label: "人物照片", title: "", main: false, problem: "" },
              { key: "3.steps", node: "3", input: "steps", label: "", title: "步数", main: false, problem: "" }],
    });
    const list = screen.getByRole("list", { name: t("workflowAppChosen") });
    expect(within(list).getAllByRole("listitem").map((one) => one.textContent)).toEqual(["人物照片", "步数"]);
    expect(screen.getByText("换装")).toBeTruthy();
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
