import { describe, expect, it } from "vitest";

import type { Job, ModelFile } from "@/api/client";
import {
  byRecipe,
  comboInputs,
  encoderFit,
  folderFamilies,
  folderModels,
  liveProgress,
  missingByPack,
  modelSlots,
  nodeLabels,
  nodesOfType,
  nodesUsingModel,
  onlyResult,
  outputGroups,
  packPage,
  presentIn,
  runGallery,
  runsByWorkflow,
  withoutResult,
  type WorkbenchNode,
} from "./workbenchLogic";

const loader: WorkbenchNode = {
  id: "4", type: "CheckpointLoaderSimple", title: "Load Checkpoint",
  widgets: [{ name: "ckpt_name", type: "combo", value: "sdxl\\base.safetensors", combo: true }],
};
const lora: WorkbenchNode = {
  id: "10", type: "LoraLoader", title: "LoRA",
  widgets: [
    { name: "lora_name", type: "combo", value: "style.safetensors", combo: true },
    { name: "strength_model", type: "number", value: 1, combo: false },
    { name: "mode", type: "combo", value: "x", combo: true },
  ],
};

const model = (folder: string, name: string, extra: Partial<ModelFile> = {}): ModelFile =>
  ({ folder, name, family: "", family_source: "", triggers: [], triggers_source: "", title: "", has_preview: false, preview_origin: "", preview_kind: "image", ...extra });

describe("工作台面板背后的纯函数", () => {
  it("选中节点上的下拉格子交给插件问目录;插件说了目录的那几格才是选模型文件的", () => {
    //: 每一格都带上这个节点上下拉格子现在的值(只有字符串的那几格):插件据此判,界面不认识它们
    const values = { lora_name: "style.safetensors", mode: "x" };
    expect(comboInputs(lora)).toEqual([
      { class_type: "LoraLoader", input: "lora_name", values },
      { class_type: "LoraLoader", input: "mode", values },
    ]);
    expect(comboInputs(null)).toEqual([]);
    expect(modelSlots(lora, ["loras", ""])).toEqual([{ widget: "lora_name", folder: "loras", value: "style.safetensors", encoders: null }]);
    expect(modelSlots(loader, []), "插件还没回话就当没有").toEqual([]);
  });

  it("CLIP 加载节点:合它现在 type 的编码器排前面,ComfyUI 不看 type 的、认不出的居中,不在配方里的最后", () => {
    const clip: WorkbenchNode = {
      id: "3", type: "CLIPLoader", title: "Load CLIP",
      widgets: [
        { name: "clip_name", type: "combo", value: "umt5_xxl.safetensors", combo: true },
        { name: "type", type: "combo", value: "wan", combo: true },
      ],
    };
    const recipe = { type: "wan", fits: ["umt5_xxl"], any_type: ["qwen3_06b"] };
    const [slot] = modelSlots(clip, ["text_encoders", ""], [recipe, null]);
    expect(slot.encoders).toEqual(recipe);
    const encoder = (name: string, kind: string) =>
      model("text_encoders", name, { family_source: "not_applicable", encoder: { kind, label: kind, source: "weights", pairs: [] } });
    const models = [
      encoder("a_clip_l.safetensors", "clip_l"),
      encoder("b_mystery.safetensors", ""),
      encoder("c_qwen.safetensors", "qwen3_06b"),
      encoder("d_umt5.safetensors", "umt5_xxl"),
    ];
    expect(byRecipe(models, recipe).map((one) => one.name))
      .toEqual(["d_umt5.safetensors", "b_mystery.safetensors", "c_qwen.safetensors", "a_clip_l.safetensors"]);
    expect(models.map((one) => encoderFit(one, recipe))).toEqual(["misfit", null, "any", "fits"]);
    expect(byRecipe(models, null), "不是 CLIP 加载节点:照原来的先后").toEqual(models);
    expect(encoderFit(model("loras", "x.safetensors"), recipe), "不是文本编码器的文件不标").toBeNull();
  });

  it("这个目录里有没有那个文件:Windows 的反斜杠和正斜杠当一样;空值不算缺", () => {
    const models = [model("checkpoints", "sdxl/base.safetensors"), model("loras", "base.safetensors")];
    expect(presentIn(models, "checkpoints", "sdxl\\base.safetensors")).toBe(true);
    expect(presentIn(models, "checkpoints", "base.safetensors")).toBe(false);
    expect(presentIn(models, "checkpoints", "")).toBe(true);
  });

  it("模型库面板:只列这个目录的,搜名字 / 标题 / 触发词,按家族筛,按名字排;家族按数量排", () => {
    const models = [
      model("loras", "b.safetensors", { family: "SDXL", triggers: ["watercolor"] }),
      model("loras", "a.safetensors", { family: "SDXL", title: "Anime" }),
      model("loras", "c.safetensors", { family: "Flux" }),
      model("checkpoints", "d.safetensors", { family: "SDXL" }),
    ];
    expect(folderModels(models, "loras", { query: "", family: "" }).map((one) => one.name))
      .toEqual(["a.safetensors", "b.safetensors", "c.safetensors"]);
    expect(folderModels(models, "loras", { query: "WATER", family: "" }).map((one) => one.name)).toEqual(["b.safetensors"]);
    expect(folderModels(models, "loras", { query: "anime", family: "" }).map((one) => one.name)).toEqual(["a.safetensors"]);
    expect(folderModels(models, "loras", { query: "", family: "Flux" }).map((one) => one.name)).toEqual(["c.safetensors"]);
    expect(folderFamilies(models, "loras")).toEqual(["SDXL", "Flux"]);
  });

  it("产出按来自的节点分组(以任务回执为准)、标节点名,说不出来源的放最后", () => {
    const labels = nodeLabels({ nodes: [{ id: 9, type: "SaveImage", title: "高清" }, { id: 17, type: "PreviewImage" }, "bad"] });
    expect([...labels]).toEqual([["9", "高清"], ["17", "PreviewImage"]]);
    const job = {
      result: {
        asset_ids: ["a1", "a2", "a3", "a4"],
        output_parameters: [
          { asset_id: "a1", parameters: { source_node: "17" } },
          { asset_id: "a2", parameters: { source_node: "9" } },
          { asset_id: "a3", parameters: { source_node: "17" } },
          { asset_id: "a4", parameters: {} },
        ],
      },
    } as unknown as Job;
    expect(outputGroups(job, labels)).toEqual([
      { node: "17", label: "PreviewImage", assets: ["a1", "a3"] },
      { node: "9", label: "高清", assets: ["a2"] },
      { node: "", label: "", assets: ["a4"] },
    ]);
    expect(outputGroups({ result: {} } as unknown as Job, labels)).toEqual([]);
  });

  it("画布上的事件:最近一次开始之后正在跑哪个节点、第几步;跑完 / 出错 / 中断就不再显示", () => {
    const event = (type: string, extra: Record<string, unknown> = {}) => ({ type, at: 0, promptId: "p1", node: "", ...extra });
    const running = [event("execution_start"), event("executing", { node: "3" }), event("progress", { node: "3", value: 4, max: 20 })];
    expect(liveProgress(running)).toEqual({ promptId: "p1", node: "3", value: 4, max: 20 });
    expect(liveProgress([...running, event("executing", { node: "8" })])).toEqual({ promptId: "p1", node: "8", value: 0, max: 0 });
    expect(liveProgress([...running, event("executing")]), "节点是空的:跑完了").toBeNull();
    expect(liveProgress([...running, event("execution_error", { node: "3" })])).toBeNull();
    expect(liveProgress([...running, event("progress", { promptId: "p2", value: 1, max: 2 })], "p1"), "只看这一次的").toEqual(
      { promptId: "p1", node: "3", value: 4, max: 20 });
  });

  it("「只要这个节点的图」:只标这一个结果;撤销只去掉这一个;应用表单别的部分不动", () => {
    const draft = { title: "人像", description: "", items: [], results: ["9", "17"] };
    expect(onlyResult(draft, "17")).toEqual({ ...draft, results: ["17"] });
    expect(withoutResult(draft, "9")).toEqual({ ...draft, results: ["17"] });
    expect(withoutResult(draft, "5")).toEqual(draft);
  });

  it("看大图:一次跑出的全部产出按面板上的顺序成组,标题带来源节点和第几张", () => {
    const groups = [{ node: "17", label: "PreviewImage", assets: ["a1", "a3"] }, { node: "", label: "", assets: ["a4"] }];
    expect(runGallery(groups, (node) => `PreviewImage #${node}`, "不知道")).toEqual([
      { asset: "a1", title: "PreviewImage #17 · 1/3" },
      { asset: "a3", title: "PreviewImage #17 · 2/3" },
      { asset: "a4", title: "不知道 · 3/3" },
    ]);
  });

  it("运行与结果按工作流分:开着的这一张在前,别的那几张各一组(没存过的按前端里的那一张认)", () => {
    const run = (jobId: string, workflowKey: string, workflowName = "") =>
      ({ jobId, path: "", workflowKey, workflowName, kind: "image", startedAt: 0, labels: [] });
    const runs = [run("j4", "workflows/b.json", "b"), run("j3", "workflows/a.json", "a"), run("j2", "workflows/Unsaved Workflow (2).json"),
                  run("j1", "workflows/b.json", "b")];
    const { current, others } = runsByWorkflow(runs, "workflows/a.json");
    expect(current.map((one) => one.jobId)).toEqual(["j3"]);
    expect(others.map((one) => [one.key, one.runs.map((r) => r.jobId)])).toEqual([
      ["workflows/b.json", ["j4", "j1"]], ["workflows/Unsaved Workflow (2).json", ["j2"]],
    ]);
  });

  it("定位:根图和子图里的节点都找得到;按类型找缺的节点,按 widget 里填的文件找缺的模型(路径写法不同也认)", () => {
    const workflow = {
      nodes: [{ id: 4, type: "CheckpointLoaderSimple", widgets_values: ["wan\\i2v.safetensors"] }, { id: 7, type: "CR Prompt Text" },
              { id: 9, type: "VHS_LoadVideo", widgets_values: { video: "i2v.safetensors", force_rate: 0 } }, "bad"],
      definitions: { subgraphs: [{ id: "sg-1", name: "细节", nodes: [{ id: 5, type: "CR Prompt Text" },
                                                                    { id: 6, type: "UNETLoader", widgets_values: ["wan/i2v.safetensors"] }] }] },
    };
    expect(nodesOfType(workflow, "CR Prompt Text")).toEqual([
      { node: "7", subgraph: null, subgraphName: "" }, { node: "5", subgraph: "sg-1", subgraphName: "细节" },
    ]);
    expect(nodesUsingModel(workflow, "wan/i2v.safetensors").map((one) => one.node)).toEqual(["4", "9", "6"]);
    expect(nodesUsingModel(workflow, "other.safetensors")).toEqual([]);
    expect(nodesOfType(null, "x")).toEqual([]);
  });

  it("缺的节点按节点包分组:同一个包的几种一起装,认不出包的各自一组、排在后面;包的主页", () => {
    const pack = (id: string) => ({ id, title: id, installed: false });
    const groups = missingByPack([
      { type: "Unknown", packs: [] },
      { type: "CR A", packs: [pack("comfyroll")] },
      { type: "CR B", packs: [pack("comfyroll")] },
      { type: "Either", packs: [pack("y"), pack("x")] },
    ]);
    expect(groups.map((one) => [one.packs.map((p) => p.id), one.nodes.map((n) => n.type)])).toEqual([
      [["comfyroll"], ["CR A", "CR B"]], [["y", "x"], ["Either"]], [[], ["Unknown"]],
    ]);
    expect(packPage("https://github.com/acme/nodes.git")).toBe("https://github.com/acme/nodes");
    expect(packPage("comfyui-kjnodes")).toBe("https://registry.comfy.org/nodes/comfyui-kjnodes");
  });
});
