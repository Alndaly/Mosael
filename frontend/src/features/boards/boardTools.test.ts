import { describe, expect, it } from "vitest";
import { Languages, Package, Sparkles } from "lucide-react";

import type { BoardItem, BoardProducerInfo } from "@/api/client";
import { kindIcon } from "@/features/boards/boardNodes";
import { boardToolFace, boardToolIcon, boardToolOptions } from "@/features/boards/boardTools";
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
      board_group: "new", board_group_label: "产出新素材", board_description: "按提示词出图", plugin_name: "ComfyUI · 本机", tool_name: "wf_1",
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
    expect(comfy.description).toBe("ComfyUI · 本机 · 按提示词出图");
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

describe("工具格上那份摘要(boardToolFace)", () => {
  //: 形状照 GET /api/boards/producers 里翻译那一格(字段声明已按语言翻好,带 board_sources)。
  const translate = producer("node:translate", "翻译", {
    type: "translate",
    board_group: "text",
    board_description: "把便签或文档里的文字翻成另一种语言",
    config: {
      text: { type: "text", required: true, label: "文本", board_sources: ["note", "document"] },
      target_lang: { type: "string", required: true, label: "目标语言", options: ["en", "ja"], option_labels: { en: "英语", ja: "日语" }, board_sources: [] },
      engine: { type: "string", label: "引擎", default: "google", options: ["google", "ai"], option_labels: { google: "Google 翻译", ai: "AI 模型" }, board_sources: [] },
      profile_id: { type: "string", label: "供应商配置", options_from: "chat_connections", active_when: { engine: "ai" }, board_sources: [] },
      extra: { type: "number", label: "高级旋钮", advanced: true, board_sources: [] },
    },
    outputs: ["text"],
    output_types: { text: "text" },
    output_labels: { text: "文本" },
    board_products: ["text"],
  });
  const tool = (item: Partial<BoardItem> = {}) => ({ id: "a", kind: "action", x: 0, y: 0, form: { producer: "node:translate" }, ...item }) as BoardItem;
  const note: BoardItem = { id: "n1", kind: "note", x: 0, y: 0, text: "你好" };

  it("空着:吃什么(没接上)、必填还没选的设置、产出什么;缺省值没改过的、要现查的、高级的都不摆", () => {
    const face = boardToolFace(translate, tool(), []);
    expect(face.icon).toBe(Languages);
    expect(face.plugin).toBe("");
    expect(face.inputs).toEqual([{ key: "text", label: "文本", kinds: ["note", "document"], source: undefined, text: undefined }]);
    expect(face.settings).toEqual([{ key: "target_lang", label: "目标语言", value: null }]);
    expect(face.products).toEqual([{ label: "文本", text: true }]);
  });

  it("连上一张便签就算接上了(必填字段跑的时候默认接第一个合适的上游);设置按显示名说,改过缺省值的才摆", () => {
    const face = boardToolFace(translate, tool({ form: { producer: "node:translate", config: { target_lang: "en", engine: "ai" } } }), [note]);
    expect(face.inputs[0].source?.id).toBe("n1");
    expect(face.settings).toEqual([
      { key: "target_lang", label: "目标语言", value: "英语" },
      { key: "engine", label: "引擎", value: "AI 模型" },
    ]);
  });

  it("手填了字、没接上游:给那段字;绑到的那一格已经不在上游了就不算接上", () => {
    const typed = boardToolFace(translate, tool({ form: { producer: "node:translate", config: { text: "hello" } } }), [note]);
    expect(typed.inputs[0]).toMatchObject({ source: undefined, text: "hello" });
    const gone = boardToolFace(translate, tool({ form: { producer: "node:translate", config: { text: "" }, bindings: { text: [{ from: "n9" }] } } }), [note]);
    expect(gone.inputs[0].source).toBeUndefined();
  });

  it("插件工具带上插件名,图标按组", () => {
    const face = boardToolFace(
      producer("node:plugin.cut.out", "去背景", { type: "plugin.cut.out", board_group: "image", plugin_name: "我的抠图" }),
      tool(),
      [],
    );
    expect(face.plugin).toBe("我的抠图");
    expect(face.icon).toBe(kindIcon("image"));
  });
});
