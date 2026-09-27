import { describe, expect, it } from "vitest";
import { Languages, Package, Sparkles, Wrench } from "lucide-react";

import type { BoardItem, BoardProducerInfo } from "@/api/client";
import { messages, type MessageKey } from "@/app/messages";
import { kindIcon } from "@/features/boards/boardNodes";
import { boardAbilities, boardAddCatalog, boardToolIcon, firstSentence, hostHasContent } from "@/features/boards/boardTools";
import { nodeTypeIcon } from "@/features/nodeForms/nodeIcons";

/** 形状和 GET /api/boards/producers 发下来的一样(后端按注册表的顺序:内置的、内置节点、插件工具)。 */
const producer = (id: string, label: string, extra: Partial<BoardProducerInfo> = {}): BoardProducerInfo =>
  ({
    id, type: id.replace(/^node:/, ""), label, description: "工作流节点的说明,如 {{转写.text}}", category: "数据",
    config: {}, outputs: [], output_types: {}, output_labels: {}, plugin_name: "", tool_name: "", body_scope: {},
    hosts: [], role: "slot", host_fields: {}, permission: "edit", effects: "none", fills_empty_slot: false,
    board_group: "", board_group_label: "", board_description: "", ...extra,
  }) as BoardProducerInfo;

const ability = (id: string, label: string, hosts: string[], extra: Partial<BoardProducerInfo> = {}) =>
  producer(id, label, { hosts, role: "ability", host_fields: Object.fromEntries(hosts.map((one) => [one, "asset_id"])), ...extra });

const PRODUCERS = [
  producer("write", "写字", { hosts: ["note"], fills_empty_slot: true }),
  producer("trim", "截一段", { hosts: ["video", "audio"] }),
  ability("node:transcribe_asset", "素材转写", ["video", "audio"], { board_group: "audio" }),
  ability("node:video_to_gif", "视频转 GIF", ["video"], { board_group: "video" }),
  ability("node:translate", "翻译", ["note", "document"], { board_group: "text" }),
  ability("node:separate_audio", "分离人声与背景音", ["video", "audio"], { board_group: "audio" }),
  producer("node:plugin.comfy.wf_1", "工作流 · 文生图", { hosts: ["image"], fills_empty_slot: true, board_group: "new" }),
];

describe("一格的能力(boardAbilities)", () => {
  const at = (kind: BoardItem["kind"], extra: Partial<BoardItem> = {}): BoardItem => ({ id: "x", kind, x: 0, y: 0, ...extra });

  it("按后端说的挂在哪(role + hosts)列,顺序照后端;内置产出者和生成器不是能力", () => {
    expect(boardAbilities(at("audio", { asset_id: "a" }), PRODUCERS).map((one) => one.label)).toEqual([
      "素材转写", "分离人声与背景音",
    ]);
    expect(boardAbilities(at("video", { asset_id: "v" }), PRODUCERS).map((one) => one.label)).toEqual([
      "素材转写", "视频转 GIF", "分离人声与背景音",
    ]);
    expect(boardAbilities(at("note", { text: "你好" }), PRODUCERS).map((one) => one.label)).toEqual(["翻译"]);
    expect(boardAbilities(at("image", { asset_id: "i" }), PRODUCERS)).toEqual([]);
  });

  it("这一格还没有内容就没有能力可用(空槽、空便签、没挑笔记的文档);清单没到也没有", () => {
    expect(boardAbilities(at("audio"), PRODUCERS)).toEqual([]);
    expect(boardAbilities(at("note", { text: "   " }), PRODUCERS)).toEqual([]);
    expect(boardAbilities(at("document"), PRODUCERS)).toEqual([]);
    expect(boardAbilities(at("document", { note_id: "n1", note_revision: 2 }), PRODUCERS).map((one) => one.label)).toEqual(["翻译"]);
    expect(boardAbilities(at("audio", { asset_id: "a" }), undefined)).toEqual([]);
    expect(hostHasContent(at("scene", { scene_id: "s" }))).toBe(true);
    expect(hostHasContent(at("frame"))).toBe(false);
  });

  it("资产格按它引用的是哪一种资产列:生成表情只有人物有,种类没取到时先不列点名了种类的", () => {
    const entityAbilities = [
      ability("node:entity_angles", "补全多角度", ["entity"], { host_fields: { entity: "entity_id" } }),
      ability("node:entity_expressions", "生成表情", ["entity"], { host_fields: { entity: "entity_id" }, host_entity_kinds: ["character"] }),
    ];
    const cell = at("entity", { entity_id: "e1" });
    expect(boardAbilities(cell, entityAbilities, "character").map((one) => one.label)).toEqual(["补全多角度", "生成表情"]);
    expect(boardAbilities(cell, entityAbilities, "location").map((one) => one.label)).toEqual(["补全多角度"]);
    expect(boardAbilities(cell, entityAbilities).map((one) => one.label)).toEqual(["补全多角度"]);
    expect(boardAbilities(at("entity"), entityAbilities, "character")).toEqual([]);
  });
});

describe("能力的图标(boardToolIcon)", () => {
  it("内置节点用它在工作流画布上的那颗(同一份 nodeIcons),插件工具按吃什么内容的那一组", () => {
    expect(boardToolIcon({ type: "translate", board_group: "text" })).toBe(Languages);
    expect(boardToolIcon({ type: "video_to_gif", board_group: "video" })).toBe(nodeTypeIcon("video_to_gif"));
    //: 插件节点(`plugin.<插件>.<工具>`)不在节点图标表里:凭空产出的用「生成」那颗。
    expect(boardToolIcon({ type: "plugin.comfy.wf_1", board_group: "new" })).toBe(Sparkles);
    expect(boardToolIcon({ type: "plugin.x.cut", board_group: "image" })).toBe(kindIcon("image"));
    expect(boardToolIcon({ type: "plugin.x.any", board_group: "asset" })).toBe(Package);
    expect(boardToolIcon({ type: "plugin.x.text", board_group: "text" })).toBe(kindIcon("note"));
    //: 没见过的组(后端多了一种)也有图标;原型链上的名字不算节点类型。
    expect(boardToolIcon({ type: "plugin.x.y", board_group: "someday" })).toBe(Wrench);
    expect(boardToolIcon({ type: "constructor", board_group: "" })).toBe(Wrench);
  });

  it("操作条上同一格的几项能力不顶着同一颗图标(分离人声和剪一段不都是剪刀)", () => {
    const icons = ["transcribe_asset", "separate_audio", "denoise_audio", "video_to_gif"].map((type) =>
      boardToolIcon({ type, board_group: "audio" }),
    );
    expect(new Set(icons).size).toBe(icons.length);
    expect(icons).not.toContain(kindIcon("audio"));
  });
});

describe("「添加」的单子(boardAddCatalog)", () => {
  const t = (key: MessageKey) => messages["zh-CN"][key];

  it("只有格子,按动词分成三组:新建 / 从库里放 / 整理;没有工具那一组", () => {
    const rows = boardAddCatalog(t);
    //: 同样的格子不列两遍(此前「生成」和「从素材库」各有图片 / 视频 / 音频);便签、文档会让 AI 写,是新建的内容格。
    expect(rows.map((one) => [one.group, one.value])).toEqual([
      ["新建", "image"], ["新建", "video"], ["新建", "audio"], ["新建", "note"], ["新建", "document"],
      ["从库里放", "pick-media"], ["从库里放", "entity"], ["从库里放", "scene"],
      ["整理", "frame"],
    ]);
    expect(rows.every((one) => !one.value.startsWith("node:"))).toBe(true);
  });
});

describe("说明的第一句(firstSentence)", () => {
  it("只取第一句、去掉 markdown 记号 —— 两颗星号不上界面", () => {
    expect(firstSentence("把桶里的一个对象拉回素材库。**交回的是地址,由宿主搬字节** —— 进度归它。")).toBe(
      "把桶里的一个对象拉回素材库。",
    );
    expect(firstSentence("Pulls one object. Then more.")).toBe("Pulls one object.");
    expect(firstSentence("")).toBe("");
  });
});
