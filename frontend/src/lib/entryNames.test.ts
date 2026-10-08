import { describe, expect, it } from "vitest";

import { entryNamedOptions, entryOrigin, formedGroups, generationOptionKeywords, generationOptionNames, twoLayerTitle } from "@/lib/entryNames";

/** 两层名字(ADR 0045:表单是工作流的入口):主名是这一项自己的,副名说它来自哪 —— 后端只给结构化的几格,这里一处摆。 */

const said: Record<string, string> = { entryFromGroup: "来自 {name}", entryFullWorkflow: "完整工作流" };
const t = (key: string) => said[key] ?? key;
const GROUP = { id: "krea2-text-2-image.json", label: "krea2-text-2-image" };
const SERVER = "ComfyUI · http://192.168.3.15:8188";
const full = { model: "krea2-text-2-image.json", model_label: "krea2-text-2-image", profile_name: SERVER, group: { ...GROUP, entry: "full", order: 0 } };
const form = { model: "krea2-text-2-image.json#app", model_label: "快速用krea2生图", profile_name: SERVER, group: { ...GROUP, entry: "form", order: 1 } };
const lone = { model: "girl.json", model_label: "girl", profile_name: SERVER, group: { id: "girl.json", label: "girl", entry: "full", order: 0 } };
const plain = { model: "gpt-image-1", model_label: "gpt-image-1", profile_name: "OpenAI", group: null };

describe("两层名字", () => {
  const formed = formedGroups([full, form, lone, plain]);

  it("表单入口:主名是表单标题,副名「来自 工作流名 · 连接名」", () => {
    expect(generationOptionNames(form, formed, t)).toEqual({ primary: "快速用krea2生图", secondary: `来自 krea2-text-2-image · ${SERVER}` });
  });

  it("有表单的完整工作流写「完整工作流」,和表单分得开;没有表单的、不属于哪一组的只写连接名(和以前一样)", () => {
    expect(generationOptionNames(full, formed, t).secondary).toBe(`完整工作流 · ${SERVER}`);
    expect(generationOptionNames(lone, formed, t).secondary).toBe(SERVER);
    expect(generationOptionNames(plain, formed, t)).toEqual({ primary: "gpt-image-1", secondary: "OpenAI" });
  });

  it("插件节点、画板能力按插件聚合、不分连接:只要入口那一截", () => {
    expect(entryOrigin(form.group, formed, t)).toBe("来自 krea2-text-2-image");
    expect(entryOrigin(full.group, formed, t)).toBe("完整工作流");
    expect(entryOrigin(lone.group, formed, t)).toBe("");
    expect(entryOrigin(null, formed, t)).toBe("");
  });

  it("搜得到它的词:主名、工作流名、模型 id(文件路径)、连接名", () => {
    expect(generationOptionKeywords(form)).toEqual(["快速用krea2生图", "krea2-text-2-image", "krea2-text-2-image.json#app", SERVER]);
  });

  it("只有一行的悬停说明:两层连成一句", () => {
    expect(twoLayerTitle({ primary: "快速用krea2生图", secondary: "来自 krea2-text-2-image" })).toBe("快速用krea2生图 — 来自 krea2-text-2-image");
    expect(twoLayerTitle({ primary: "gpt-image-1", secondary: "" })).toBe("gpt-image-1");
  });

  it("工作流字段的现查选项:有表单的工作流每个入口一行、名字是它自己的,第二行说来自哪张;同属一小组只为搜索;别的原样", () => {
    const listed = entryNamedOptions(
      [
        { value: "p9:image:krea2-text-2-image.json#app", label: "快速用krea2生图", model: form.model, profile_name: SERVER,
          entry_group: form.group },
        { value: "p9:image:krea2-text-2-image.json", label: "krea2-text-2-image · 默认", model: full.model, profile_name: SERVER,
          entry_group: full.group },
        { value: "edge", label: "Edge TTS" },
      ],
      t,
    );
    const section = { key: `${SERVER}\nkrea2-text-2-image.json` };
    expect(listed[0]).toMatchObject({ label: "快速用krea2生图", description: `来自 krea2-text-2-image · ${SERVER}`, section });
    expect(listed[1]).toMatchObject({ label: "krea2-text-2-image · 默认", description: `完整工作流 · ${SERVER}`, section });
    expect(listed[2]).toEqual({ value: "edge", label: "Edge TTS" });
  });
});
