import { describe, expect, it } from "vitest";
import { Package, Sparkles } from "lucide-react";

import type { BoardProducerInfo } from "@/api/client";
import { kindIcon } from "@/features/boards/boardNodes";
import { boardToolIcon, boardToolOptions } from "@/features/boards/boardTools";

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

  it("每一组都有图标:吃什么内容就用那种格子的图标,凭空产出的用「生成」那颗", () => {
    const icons = Object.fromEntries(boardToolOptions(producers).map((one) => [one.value, one.icon]));
    expect(icons["node:plugin.comfy.wf_1"]).toBe(Sparkles);
    expect(icons["node:video_to_gif"]).toBe(kindIcon("video"));
    expect(icons["node:translate"]).toBe(kindIcon("note"));
    expect(boardToolIcon("asset")).toBe(Package);
    expect(boardToolIcon("scene")).toBe(kindIcon("scene"));
    //: 没见过的组(后端多了一种)也有图标,不会是一行空着的。
    expect(boardToolIcon("someday")).toBe(kindIcon("action"));
  });
});
