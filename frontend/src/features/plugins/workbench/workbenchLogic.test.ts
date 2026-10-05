import { describe, expect, it } from "vitest";

import type { Job, ModelFile } from "@/api/client";
import {
  comboInputs,
  folderFamilies,
  folderModels,
  liveProgress,
  modelSlots,
  nodeLabels,
  onlyResult,
  outputGroups,
  presentIn,
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
  ({ folder, name, family: "", family_source: "", triggers: [], triggers_source: "", title: "", has_preview: false, ...extra });

describe("工作台面板背后的纯函数", () => {
  it("选中节点上的下拉格子交给插件问目录;插件说了目录的那几格才是选模型文件的", () => {
    expect(comboInputs(lora)).toEqual([
      { class_type: "LoraLoader", input: "lora_name" },
      { class_type: "LoraLoader", input: "mode" },
    ]);
    expect(comboInputs(null)).toEqual([]);
    expect(modelSlots(lora, ["loras", ""])).toEqual([{ widget: "lora_name", folder: "loras", value: "style.safetensors" }]);
    expect(modelSlots(loader, []), "插件还没回话就当没有").toEqual([]);
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

  it("「以后只要这张」:只标这一个结果,应用表单别的部分不动", () => {
    const draft = { title: "人像", description: "", items: [], results: ["9", "17"] };
    expect(onlyResult(draft, "17")).toEqual({ ...draft, results: ["17"] });
  });
});
