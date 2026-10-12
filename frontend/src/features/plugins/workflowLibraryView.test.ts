import { describe, expect, it } from "vitest";

import type { WorkflowFile } from "@/api/client";
import {
  ALL_MODELS,
  ALL_WORKFLOWS,
  conflictOf,
  filterWorkflows,
  filesIn,
  folderOfView,
  folderPathFrom,
  folderTree,
  folderView,
  freeFolderPath,
  inView,
  modelCounts,
  notEmptyOf,
  searchHaystackOf,
  validFolderPath,
  WORKFLOW_KINDS,
} from "./workflowLibraryView";
import { matchesSource } from "@/features/plugins/workflowAppForm";

/**
 * 工作流库左栏的文件夹树和改文件夹时的几样纯函数(ADR 0035 后续「文件夹」)。
 */

const flow = (path: string) => ({ path, label: path, folder: path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "" }) as WorkflowFile;
const failure = (detail: unknown) => Object.assign(new Error("409"), { status: 409, body: JSON.stringify({ detail }) });

describe("文件夹树", () => {
  it("插件报的加上工作流所在的,补齐上级;同一层按名字的自然顺序,数量连同子文件夹", () => {
    const workflows = [flow("a.json"), flow("v/x.json"), flow("v/drafts/y.json"), flow("img 10/z.json"), flow("img 9/z.json")];
    expect(folderTree(["空的", "v/deep/deeper"], workflows)).toEqual([
      { path: "img 9", name: "img 9", depth: 0, count: 1 },
      { path: "img 10", name: "img 10", depth: 0, count: 1 },
      { path: "v", name: "v", depth: 0, count: 2 },
      { path: "v/deep", name: "deep", depth: 1, count: 0 },
      { path: "v/deep/deeper", name: "deeper", depth: 2, count: 0 },
      { path: "v/drafts", name: "drafts", depth: 1, count: 1 },
      { path: "空的", name: "空的", depth: 0, count: 0 },
    ]);
  });

  it("选一个文件夹:它和它下面的;名字只是前缀相同的别的文件夹不算", () => {
    const workflows = [flow("v/x.json"), flow("v/草稿/y.json"), flow("video/z.json")];
    expect(inView(workflows, folderView("v")).map((one) => one.path)).toEqual(["v/x.json", "v/草稿/y.json"]);
    expect(inView(workflows, ALL_WORKFLOWS)).toHaveLength(3);
    expect(folderOfView(folderView("__all__")), "叫 __all__ 的文件夹也和「全部」分得开").toBe("__all__");
    expect(folderOfView(ALL_WORKFLOWS)).toBeNull();
    expect(filesIn("v", ["v/x.json", "v/pack.zip", "video/z.json"])).toBe(2);
  });
});

describe("文件夹名", () => {
  it("输入框里的字:去掉开头的 workflows/ 和末尾的 /;和工作流路径同一套分段规则,不以 .json 结尾", () => {
    expect(folderPathFrom("  workflows/人像/草稿/ ")).toBe("人像/草稿");
    for (const good of ["人像", "a/b c", "v (1)"]) expect(validFolderPath(good), good).toBe(true);
    for (const bad of ["", "../x", "a//b", ".hidden", "a/.b", "a:b", "x.json", "a /b", "a\\b"]) expect(validFolderPath(bad), bad).toBe(false);
  });

  it("不撞名的建议:不分大小写比(那台机器可能是 Windows)", () => {
    expect(freeFolderPath("Video", ["video", "video (1)"])).toBe("Video (2)");
    expect(freeFolderPath("新的", ["video"])).toBe("新的");
  });

  it("409 分得清:撞名(带建议名)和文件夹不空(带个数)", () => {
    expect(conflictOf(failure({ code: "exists", suggestion: "a (1)" }))).toEqual({ suggestion: "a (1)" });
    expect(conflictOf(failure({ code: "not_empty", count: 2 })), "不空不是撞名").toBeNull();
    expect(conflictOf(failure({ code: "stale", modified: 1 }))).toBeNull();
    expect(notEmptyOf(failure({ code: "not_empty", count: 2 }))).toEqual({ count: 2 });
    expect(notEmptyOf(failure({ code: "exists", suggestion: "" }))).toBeNull();
    expect(notEmptyOf(new Error("x"))).toBeNull();
  });
});

describe("种类", () => {
  it("只交出一段字的(反推提示词、打标签)是「文字」一类,能单独筛出来,不混在「图像」里(PLG-11)", () => {
    const caption = { ...flow("caption.json"), kind: "text" } as WorkflowFile;
    const portrait = { ...flow("portrait.json"), kind: "image" } as WorkflowFile;
    expect(WORKFLOW_KINDS).toContain("text");
    expect(filterWorkflows([caption, portrait], { kind: "text", query: "" })).toEqual([caption]);
    expect(filterWorkflows([caption, portrait], { kind: "image", query: "" })).toEqual([portrait]);
  });
});

describe("搜索", () => {
  it("每张表单的标题都算(ADR 0045):AI Studio 里看到「快速用krea2生图」「精调」,在库里搜得到是哪张工作流", () => {
    const form = (id: string, title: string) => ({ id, title, description: "", fields: 1, invalid: 0, model: "", tool: "" });
    const formed = {
      ...flow("krea2-text-2-image.json"),
      app: { status: "ok", version: "", upgradable: false, invalid: 0, stray: 0, results: [],
             forms: [form("app", "快速用krea2生图"), form("k3x9a2", "精调")] },
    } as WorkflowFile;
    const other = flow("girl.json");
    expect(filterWorkflows([formed, other], { kind: "all", query: "快速" })).toEqual([formed]);
    expect(filterWorkflows([formed, other], { kind: "all", query: "精调" })).toEqual([formed]);
    expect(filterWorkflows([formed, other], { kind: "all", query: "krea2" })).toEqual([formed]);
  });

  //: 边界就是这条:**搜索只管卡上看得见的字**(名字、路径、表单标题,见 searchHaystackOf)。用到的模型名只在
  //: 卡片点开之后的详情里,卡面上没有 —— 搜索里再认一遍,就和顶栏的「用到模型」筛选器成了同一件事的两种干法。
  it("只在用到的模型名里出现的词搜不到(那条召回交给「用到模型」筛选器)", () => {
    const krea = {
      ...flow("krea2-text-2-image.json"), label: "krea2-text-2-image",
      models: [{ folder: "diffusion_models", name: "qwen_2.5_vl_7b.safetensors", present: true }],
    } as WorkflowFile;
    const other = flow("girl.json");
    expect(searchHaystackOf(krea), "就是名字、路径、表单标题这几样").toBe("krea2-text-2-image krea2-text-2-image.json");
    expect(filterWorkflows([krea, other], { kind: "all", query: "qwen" }), "模型名不再是搜索词").toEqual([]);
    expect(filterWorkflows([krea, other], { kind: "all", query: "krea2" }), "名字里的词照旧命中").toEqual([krea]);
    //: 同一条召回,筛选器能办到:选中那个模型只剩用到它的
    expect(filterWorkflows([krea, other], { kind: "all", model: "qwen_2.5_vl_7b.safetensors", query: "" })).toEqual([krea]);
    expect(filterWorkflows([krea, other], { kind: "all", model: ALL_MODELS, query: "" })).toHaveLength(2);
    //: 两个叠加:都要满足
    expect(filterWorkflows([krea, other], { kind: "all", model: "qwen_2.5_vl_7b.safetensors", query: "girl" })).toEqual([]);
    expect(filterWorkflows([krea, other], { kind: "all", model: "qwen_2.5_vl_7b.safetensors", query: "krea2" })).toEqual([krea]);
  });

  it("出了什么问题、缺的节点类型、输入输出的名字也不算:缺的归左栏「缺节点或模型」那一页", () => {
    const broken = {
      ...flow("sketch.json"),
      problem: "这台 ComfyUI 上没有这几种节点:CR Prompt Text",
      missing_nodes: [{ type: "CR Prompt Text", count: 1, packs: [] }],
      missing_models: [{ folder: "loras", name: "gone.safetensors", url: "" }],
      inputs: [{ node: "10", title: "LoadImage", media: "image", role: "reference_image" }],
      outputs: [{ node: "9", title: "保存图像", media: "image" }],
    } as WorkflowFile;
    for (const word of ["CR Prompt Text", "gone", "LoadImage", "保存图像"]) {
      expect(filterWorkflows([broken], { kind: "all", query: word }), word).toEqual([]);
    }
    expect(filterWorkflows([broken], { kind: "all", query: "sketch" }), "名字照旧").toEqual([broken]);
  });
});

describe("「用到模型」筛选", () => {
  const withModels = (path: string, names: string[]) =>
    ({ ...flow(path), models: names.map((name) => ({ folder: "loras", name, present: true })) }) as WorkflowFile;

  it("选项是各张工作流 models[].name 的并集,带张数;一张里同一个模型出现两次只算一张", () => {
    const one = withModels("a.json", ["qwen_2.5_vl.safetensors", "qwen_2.5_vl.safetensors", "ae.safetensors"]);
    const two = withModels("b.json", ["qwen_2.5_vl.safetensors"]);
    expect(modelCounts([one, two])).toEqual([
      ["qwen_2.5_vl.safetensors", 2],
      ["ae.safetensors", 1],
    ]);
    expect(modelCounts([flow("plain.json")]), "一张都没用到就没有选项").toEqual([]);
    //: 选项的值就是模型名,拿去筛的时候按整个名字比(前缀相同的不算)
    expect(filterWorkflows([one, two], { kind: "all", model: "ae.safetensors", query: "" })).toEqual([one]);
    expect(filterWorkflows([one, two], { kind: "all", model: "qwen_2.5_vl", query: "" })).toEqual([]);
  });

  it("多的在前,一样多按名字的自然顺序(和「底模」筛选同一个排法)", () => {
    const one = withModels("a.json", ["m10.safetensors", "m9.safetensors", "rare.safetensors"]);
    const two = withModels("b.json", ["m10.safetensors", "m9.safetensors"]);
    expect(modelCounts([one, two])).toEqual([
      ["m9.safetensors", 2],
      ["m10.safetensors", 2],
      ["rare.safetensors", 1],
    ]);
  });
});

describe("精简表单里搜「工作流里能填的」", () => {
  //: 维护者:「节点名称明明是 Load Image,搜索这个却搜索不到」—— 列表上那一条显示的是本地化的「加载图像」,
  //: 而画布上节点写的是 `Load Image`,类名是 `LoadImage`。按字面比的话带空格的那串一个都命不中。
  const item = {
    key: "674.image", node: "674", input: "image", kind: "media", title: "加载图像",
    node_title: "Load Image", node_label: "加载图像", class_type: "LoadImage", hint: "",
  } as never;

  it("画布上看到的那串(带空格)命得中类名", () => {
    expect(matchesSource(item, "Load Image")).toBe(true);
    expect(matchesSource(item, "loadimage")).toBe(true);
    expect(matchesSource(item, "Load-Image")).toBe(true);
  });

  it("节点号也搜得到(标题上那个 #号 现在可点着定位,按它找是自然的下一步)", () => {
    expect(matchesSource(item, "674")).toBe(true);
    expect(matchesSource(item, "#674")).toBe(true);
    expect(matchesSource(item, "675")).toBe(false);
  });

  it("本地化的名字照旧搜得到;搜不到的还是搜不到", () => {
    expect(matchesSource(item, "加载图像")).toBe(true);
    expect(matchesSource(item, "video")).toBe(false);
  });

  it("名字只有挑好的那一句:另一种语言里的写法搜不到(撤掉语言表之后的代价)", () => {
    //: 撤语言表之前,插件另带一条 `node_label_en` 兜着这种情形(显示「加载图像」、搜索比 `Load Image (as Mask)`)。
    //: 维护者否掉了那一套:「为了 ComfyUI 和 Mosael 的语言不匹配问题特地兼容做一套方案是不合理的」。现在名字是按请求
    //: 语言挑好的**一句**,没被挑中的那门语言在数据里不存在 —— 这一条把这个代价写下来,免得以后当成 bug 又修回去。
    //: `node_title` 有值时还救得回来(上面那条用例就是靠它命中的:画布上节点标题写的就是那串英文)。
    const masked = {
      key: "674.image", node: "674", input: "image", kind: "media", title: "参考图 · 加载图像 #674",
      node_title: "", node_label: "加载图像",
      class_type: "LoadImageMask", hint: "",
    } as never;
    expect(matchesSource(masked, "加载图像")).toBe(true);
    expect(matchesSource(masked, "LoadImageMask")).toBe(true);
    expect(matchesSource(masked, "Load - Image ( as  mask )")).toBe(false);
    expect(matchesSource(masked, "as Mask")).toBe(false);
    expect(matchesSource(masked, "SaveImage")).toBe(false);
    //: 空搜索不筛掉任何一项,照旧
    expect(matchesSource(masked, "")).toBe(true);
  });

  it("没有节点的项(种子、尺寸、跑几遍)名字是空串,照旧搜原来那几样", () => {
    const graphLevel = { key: "seed", node: "", input: "seed", kind: "seed", title: "种子",
                         node_title: "", node_label: "", class_type: "",
                         hint: "" } as never;
    expect(matchesSource(graphLevel, "as Mask")).toBe(false);
    expect(matchesSource(graphLevel, "种子")).toBe(true);
    expect(matchesSource(graphLevel, "Seed")).toBe(true);
  });
});
