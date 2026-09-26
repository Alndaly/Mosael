import { describe, expect, it } from "vitest";
import { Languages, Package, Sparkles } from "lucide-react";

import type { BoardItem, BoardProducerInfo } from "@/api/client";
import { DEFAULT_SIZE, kindIcon } from "@/features/boards/boardNodes";
import { boardToolFace, boardToolIcon, boardToolOptions, boardToolSubtitle, firstSentence, toolCellKind, toolCellSize } from "@/features/boards/boardTools";
import { nodeTypeIcon } from "@/features/nodeForms/nodeIcons";

/** 形状和 GET /api/boards/producers 发下来的一样(后端已按 board_group 排好、同组挨着)。 */
const producer = (id: string, label: string, extra: Partial<BoardProducerInfo> = {}): BoardProducerInfo =>
  ({
    id, type: id.replace(/^node:/, ""), label, description: "工作流节点的说明,如 {{转写.text}}", category: "数据",
    config: {}, outputs: [], output_types: {}, output_labels: {}, plugin_name: "", tool_name: "", body_scope: {},
    hosts: ["action"], permission: "edit", effects: "none", fills_empty_slot: false,
    board_group: "", board_group_label: "", board_description: "", ...extra,
  }) as BoardProducerInfo;

describe("画板上的工具怎么分组(boardToolOptions)", () => {
  const producers = [
    producer("write", "写字", { hosts: ["note"], fills_empty_slot: true }),
    producer("node:plugin.comfy.wf_1", "工作流 · 文生图", {
      board_group: "new", board_group_label: "产出新素材", board_description: "按提示词出图", plugin_name: "ComfyUI", tool_name: "wf_1",
    }),
    producer("node:video_to_gif", "视频转 GIF", { board_group: "video", board_group_label: "处理视频", board_description: "把一段视频做成 GIF 动图" }),
    producer("node:separate_audio", "分离人声与背景音", { board_group: "audio", board_group_label: "处理音频", board_description: "拆成人声和背景音" }),
    producer("node:denoise_audio", "降噪", { board_group: "audio", board_group_label: "处理音频", board_description: "去掉底噪" }),
    producer("node:translate", "翻译", { board_group: "text", board_group_label: "处理文字", board_description: "翻成另一种语言" }),
  ];

  it("按它对内容做什么分组(后端给的组名和顺序),不是工作流面板的「数据 / 流程」;内置的四个不在里面", () => {
    const options = boardToolOptions(producers);
    expect(options.map((one) => [one.value, one.group])).toEqual([
      ["node:plugin.comfy.wf_1", "产出新素材"],
      ["node:video_to_gif", "处理视频"],
      ["node:separate_audio", "处理音频"],
      ["node:denoise_audio", "处理音频"],
      ["node:translate", "处理文字"],
    ]);
    expect(options.some((one) => one.group.includes("数据"))).toBe(false);
  });

  it("副标题是画板那一句说明(插件工具点名出处),不是带 {{…}} 的节点说明;调用名能搜", () => {
    const [comfy, gif] = boardToolOptions(producers);
    expect(comfy.description).toBe("ComfyUI · 按提示词出图");
    expect(comfy.keywords).toEqual(["wf_1"]);
    expect(gif.description).toBe("把一段视频做成 GIF 动图");
    expect(boardToolOptions(producers).every((one) => !one.description.includes("{{"))).toBe(true);
  });

  it("图标说的是这个工具做什么:内置节点用它在工作流画布上的那颗(同一份 nodeIcons),插件工具按吃什么内容的那一组", () => {
    const icons = Object.fromEntries(boardToolOptions(producers).map((one) => [one.value, one.icon]));
    expect(icons["node:translate"]).toBe(Languages);
    expect(icons["node:video_to_gif"]).toBe(nodeTypeIcon("video_to_gif"));
    expect(icons["node:separate_audio"]).toBe(nodeTypeIcon("separate_audio"));
    //: 每个工具不再顶着同一把扳手。
    expect(new Set(Object.values(icons)).size).toBe(Object.keys(icons).length);
    //: 插件节点(`plugin.<插件>.<工具>`)不在节点图标表里:凭空产出的用「生成」那颗。
    expect(icons["node:plugin.comfy.wf_1"]).toBe(Sparkles);
    expect(boardToolIcon({ type: "plugin.x.cut", board_group: "image" })).toBe(kindIcon("image"));
    expect(boardToolIcon({ type: "plugin.x.any", board_group: "asset" })).toBe(Package);
    expect(boardToolIcon({ type: "plugin.x.text", board_group: "text" })).toBe(kindIcon("note"));
    //: 没见过的组(后端多了一种)也有图标,不会是一行空着的;原型链上的名字不算节点类型。
    expect(boardToolIcon({ type: "plugin.x.y", board_group: "someday" })).toBe(kindIcon("action"));
    expect(boardToolIcon({ type: "constructor", board_group: "" })).toBe(kindIcon("action"));
  });
});

describe("菜单里工具那一行的副标题(boardToolSubtitle)", () => {
  const tool = (label: string, extra: Partial<BoardProducerInfo> = {}) =>
    ({ label, plugin_name: "", board_description: "", board_group_label: "产出新素材", ...extra }) as BoardProducerInfo;

  it("说明只取第一句、去掉 markdown 记号 —— 两颗星号不上菜单", () => {
    expect(firstSentence("把桶里的一个对象拉回素材库。**交回的是地址** —— 进度归宿主。")).toBe("把桶里的一个对象拉回素材库。");
    expect(firstSentence("Pull an object back. The **host** moves the bytes.")).toBe("Pull an object back.");
    expect(firstSentence("**只有加粗的一句**")).toBe("只有加粗的一句");
    //: 版本号里的点不是句末。
    expect(firstSentence("Works with v1.5 and later")).toBe("Works with v1.5 and later");
  });

  it("出处只写插件名;名字已经以它开头就不再念一遍;和名字一样的说明不重复", () => {
    expect(boardToolSubtitle(tool("从对象存储取回", { plugin_name: "对象存储", board_description: "把桶里的一个对象拉回素材库。" })))
      .toBe("对象存储 · 把桶里的一个对象拉回素材库。");
    expect(boardToolSubtitle(tool("ComfyUI 服务器状态", { plugin_name: "ComfyUI", board_description: "看一眼显存。" }))).toBe("看一眼显存。");
    expect(boardToolSubtitle(tool("把对象拉回素材库。", { plugin_name: "对象存储", board_description: "把对象拉回素材库。**交地址**" }))).toBe("对象存储");
  });

  it("什么都没说的工具也不空着:退到它那一组", () => {
    expect(boardToolSubtitle(tool("转一下"))).toBe("产出新素材");
  });
});

describe("工具格长成什么(boardToolFace / toolCellKind)", () => {
  //: 形状照 GET /api/boards/producers 里翻译那一格(字段声明已按语言翻好,带 board_sources)。
  const translate = producer("node:translate", "翻译", {
    type: "translate",
    board_group: "text",
    board_description: "把便签或文档里的文字翻成另一种语言",
    config: {
      text: { type: "text", required: true, label: "文本", board_sources: ["note", "document"] },
      target_lang: { type: "string", required: true, label: "目标语言", options: ["en", "ja"], option_labels: { en: "英语", ja: "日语" }, board_sources: [] },
      extra: { type: "number", label: "高级旋钮", advanced: true, board_sources: [] },
    },
    outputs: ["text"],
    output_types: { text: "text" },
    output_labels: { text: "文本" },
    output_kinds: ["note"],
  });
  const tool = (item: Partial<BoardItem> = {}) => ({ id: "a", kind: "action", x: 0, y: 0, form: { producer: "node:translate" }, ...item }) as BoardItem;
  const note: BoardItem = { id: "n1", kind: "note", x: 0, y: 0, text: "你好" };

  it("长成它主产出的那种内容格:文字是便签,素材按后端说的种类;说不清的(asset)按图片格;清单没到也是图片格", () => {
    expect(toolCellKind({ output_kinds: ["note"] })).toBe("note");
    expect(toolCellKind({ output_kinds: ["audio", "audio"] })).toBe("audio");
    //: 一次出好几种:第一种是主产出(渲白模参考:首帧、尾帧、运镜视频)。
    expect(toolCellKind({ output_kinds: ["image", "image", "video"] })).toBe("image");
    expect(toolCellKind({ output_kinds: ["video"] })).toBe("video");
    expect(toolCellKind({ output_kinds: ["asset"] })).toBe("image");
    expect(toolCellKind({ output_kinds: [] })).toBe("image");
    expect(toolCellKind(undefined)).toBe("image");
    //: 放下时和那种内容格一样大。
    expect(toolCellSize({ output_kinds: ["audio"] })).toEqual(DEFAULT_SIZE.audio);
    expect(toolCellSize({ output_kinds: ["note"] })).toEqual(DEFAULT_SIZE.note);
    expect(toolCellSize(undefined)).toEqual(DEFAULT_SIZE.action);
  });

  it("空着:格子上至多一句「还差什么」—— 第一个没接上、没手填的必填输入能接哪几种;设置不上格子", () => {
    const face = boardToolFace(translate, tool(), []);
    expect(face).toMatchObject({ label: "翻译", plugin: "", icon: Languages, kind: "note", missing: ["note", "document"] });
    expect(Object.keys(face).sort()).toEqual(["description", "icon", "kind", "label", "missing", "plugin"]);
  });

  it("连上一张便签就不差了(必填字段跑的时候默认接第一个合适的上游);手填了字也不差", () => {
    expect(boardToolFace(translate, tool(), [note]).missing).toBeNull();
    expect(boardToolFace(translate, tool({ form: { producer: "node:translate", config: { text: "hello" } } }), []).missing).toBeNull();
    //: 绑到的那一格已经不在上游了,就又差了。
    const gone = boardToolFace(translate, tool({ form: { producer: "node:translate", config: { text: "" }, bindings: { text: [{ from: "n9" }] } } }), [note]);
    expect(gone.missing).toEqual(["note", "document"]);
  });

  it("插件工具带上插件名,图标按组", () => {
    const face = boardToolFace(
      producer("node:plugin.cut.out", "去背景", { type: "plugin.cut.out", board_group: "image", plugin_name: "我的抠图", output_kinds: ["image"] }),
      tool(),
      [],
    );
    expect(face.plugin).toBe("我的抠图");
    expect(face.icon).toBe(kindIcon("image"));
    expect(face.kind).toBe("image");
    expect(face.missing).toBeNull();
  });
});
