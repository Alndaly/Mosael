import { describe, expect, it } from "vitest";

import type { ModelFile } from "@/api/client";

import {
  NOT_APPLICABLE_FAMILY,
  UNKNOWN_FAMILY,
  familyCounts,
  familyLabelKey,
  familyOf,
  familySource,
  filterModels,
  pairedWith,
  pairsFirst,
} from "./modelLibraryView";

const file = (name: string, family: string, family_source: string): ModelFile => ({
  folder: "loras",
  name,
  family,
  family_source,
  triggers: [],
  triggers_source: "",
  title: "",
  has_preview: false,
  preview_origin: "", preview_kind: "image",
  used_by: [],
});

describe("模型库的底模", () => {
  // 文本编码器、放大模型这类文件不是给某一个底模做的:插件报 family_source = not_applicable,不该和「认不出」混在一起
  const models = [
    file("a.safetensors", "SDXL", "weights"),
    file("b.safetensors", "SDXL", "metadata"),
    file("c.safetensors", "Flux", "filename"),
    file("t5xxl.safetensors", "", "not_applicable"),
    file("clip_l.safetensors", "", "not_applicable"),
    file("x.safetensors", "", ""),
  ];

  it("不适用的单独一类,不算「认不出」", () => {
    expect(familyOf(models[3])).toBe(NOT_APPLICABLE_FAMILY);
    expect(familyOf(models[5])).toBe(UNKNOWN_FAMILY);
    expect(familyOf(models[0])).toBe("SDXL");
  });

  it("筛选里认得的按数目,认不出的、不适用的排最后", () => {
    expect(familyCounts(models)).toEqual([
      ["SDXL", 2, 0],
      ["Flux", 1, 0],
      [UNKNOWN_FAMILY, 1, 0],
      [NOT_APPLICABLE_FAMILY, 2, 0],
    ]);
    expect(filterModels(models, { families: [NOT_APPLICABLE_FAMILY], query: "" }).map((one) => one.name)).toEqual([
      "t5xxl.safetensors",
      "clip_l.safetensors",
    ]);
  });

  it("两个特殊项有自己的文案,别的就是家族名", () => {
    expect(familyLabelKey(UNKNOWN_FAMILY)).toBe("modelLibraryFamilyUnknown");
    expect(familyLabelKey(NOT_APPLICABLE_FAMILY)).toBe("modelLibraryFamilyNotApplicable");
    expect(familyLabelKey("SDXL")).toBeNull();
  });

  it("凭的是什么:元数据、权重结构写在文件里(实),文件名是猜的(虚)", () => {
    expect(familySource(models[0])).toEqual({ hint: "modelFamilySourceWeights", certain: true });
    expect(familySource(models[1])).toEqual({ hint: "modelFamilySourceMetadata", certain: true });
    expect(familySource(models[2])).toEqual({ hint: "modelFamilySourceFilename", certain: false });
    expect(familySource(models[3])).toEqual({ hint: "modelFamilyNotApplicableHint", certain: false });
    expect(familySource(models[5])).toBeNull();
    //: 权重只看得出 SDXL,Civitai 上按哈希对上的版本登记的是 Illustrious:凭的是 Civitai(实)
    expect(familySource(file("x.safetensors", "Illustrious", "civitai"))).toEqual({ hint: "modelFamilySourceCivitai", certain: true });
  });
});

describe("文本编码器的「常配」", () => {
  //: 一个文本编码器给好几种底模用:不贴底模(仍是不适用那一类),按底模筛时常配它的一起列出
  const encoder = (name: string, kind: string, label: string, pairs: string[]): ModelFile => ({
    ...file(name, "", "not_applicable"),
    folder: "text_encoders",
    encoder: { kind, label, source: "weights", pairs },
  });
  const models = [
    file("krea.safetensors", "Krea 2", "weights"),
    file("flux.safetensors", "Flux", "weights"),
    encoder("t5xxl.safetensors", "t5_xxl", "T5-XXL", ["Flux", "SD 3", "HiDream"]),
    encoder("qwen3vl_4b.safetensors", "qwen3vl_4b", "Qwen3-VL 4B", ["Krea 2", "Flux.2"]),
    file("4x.pth", "", "not_applicable"),
  ];

  it("筛选里每一种底模另数常配它的编码器;只有编码器常配的底模也列", () => {
    expect(familyCounts(models)).toEqual([
      ["Flux", 1, 1],
      ["Krea 2", 1, 1],
      ["Flux.2", 0, 1],
      ["HiDream", 0, 1],
      ["SD 3", 0, 1],
      [NOT_APPLICABLE_FAMILY, 3, 0],
    ]);
  });

  it("按底模筛:是它的、常配它的都留下;常配的不算是它的", () => {
    expect(filterModels(models, { families: ["Krea 2"], query: "" }).map((one) => one.name)).toEqual([
      "krea.safetensors",
      "qwen3vl_4b.safetensors",
    ]);
    expect(pairedWith(models[3], ["Krea 2"])).toEqual(["Krea 2"]);
    expect(pairedWith(models[0], ["Krea 2"])).toEqual([]);
    expect(familyOf(models[3])).toBe(NOT_APPLICABLE_FAMILY);
    expect(filterModels(models, { families: [NOT_APPLICABLE_FAMILY], query: "" }).map((one) => one.name)).toEqual([
      "t5xxl.safetensors",
      "qwen3vl_4b.safetensors",
      "4x.pth",
    ]);
  });

  it("搜索看得到是哪一种编码器;「常配」先写勾着的那几种", () => {
    expect(filterModels(models, { families: [], query: "t5-x" }).map((one) => one.name)).toEqual(["t5xxl.safetensors"]);
    expect(pairsFirst(["Flux", "SD 3", "HiDream"], ["HiDream"])).toEqual(["HiDream", "Flux", "SD 3"]);
    expect(pairsFirst(["Flux", "SD 3"], [])).toEqual(["Flux", "SD 3"]);
  });
});
