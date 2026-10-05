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
      ["SDXL", 2],
      ["Flux", 1],
      [UNKNOWN_FAMILY, 1],
      [NOT_APPLICABLE_FAMILY, 2],
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
