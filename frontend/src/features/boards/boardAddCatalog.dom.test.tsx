/** @vitest-environment jsdom */
import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { BoardProducerInfo } from "@/api/client";
import { messages, type MessageKey } from "@/app/messages";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { boardAddCatalog } from "@/features/boards/boardTools";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: MessageKey) => messages["zh-CN"][key] }));

const t = (key: MessageKey) => messages["zh-CN"][key];

/** 形状和 GET /api/boards/producers 发下来的一样。 */
const producer = (id: string, label: string, extra: Partial<BoardProducerInfo> = {}): BoardProducerInfo =>
  ({
    id, type: id.replace(/^node:/, ""), label, description: "", category: "插件",
    config: {}, outputs: [], output_types: {}, output_labels: {}, plugin_name: "", tool_name: "", body_scope: {},
    hosts: ["action"], permission: "edit", effects: "none", fills_empty_slot: false,
    board_group: "new", board_group_label: "产出新素材", board_description: "", ...extra,
  }) as BoardProducerInfo;

//: 用户截图里那一组:对象存储的取回工具(说明带 markdown、两句),ComfyUI 的导入,百度网盘的导入。
const PRODUCERS = [
  producer("write", "写字", { hosts: ["note"], fills_empty_slot: true }),
  producer("node:plugin.dev.mosael.object-storage.storage_fetch", "从对象存储取回", {
    plugin_name: "对象存储", tool_name: "storage_fetch",
    board_description: "把桶里的一个对象拉回素材库。**交回的是地址,由宿主搬字节** —— 进度、取消、重试都归它。",
  }),
  producer("node:plugin.dev.mosael.comfyui.import_outputs", "导入 ComfyUI 产出", {
    plugin_name: "ComfyUI", tool_name: "import_outputs",
    board_description: "把 ComfyUI 历史里的产出收进素材库:给任务号就取那一个,不给就取最近几次。",
  }),
  producer("node:plugin.dev.mosael.comfyui.server_status", "ComfyUI 服务器状态", {
    plugin_name: "ComfyUI", tool_name: "server_status", board_description: "看一眼显存和队列。",
  }),
  producer("node:plugin.dev.mosael.baidu-pan.pan_import", "从百度网盘导入", {
    plugin_name: "百度网盘", tool_name: "pan_import", board_description: "",
  }),
  producer("node:video_to_gif", "视频转 GIF", {
    board_group: "video", board_group_label: "处理视频", board_description: "把一段视频做成 GIF 动图",
  }),
];

function openMenu(): HTMLElement[] {
  render(
    <SearchableSelect
      value=""
      onValueChange={vi.fn()}
      options={boardAddCatalog(t, PRODUCERS).map(({ icon: Icon, ...one }) => ({ ...one, icon: <Icon /> }))}
      trigger={<button type="button">添加</button>}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "添加" }));
  return [...document.querySelectorAll<HTMLElement>("[cmdk-item]")];
}

/** 一行的名字和说明:SearchableSelect 把它们排成文字列里的两行。 */
function lines(row: HTMLElement): string[] {
  const column = row.querySelector(":scope > span:not([aria-hidden])");
  return [...(column?.children ?? [])].map((one) => one.textContent ?? "");
}

describe("画板「添加」单子:每一行都是图标、名字、一句说明", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
  });

  it("格子、分组和工具一样有说明;名字里没有 markdown,也不和说明是同一句", () => {
    const rows = openMenu();
    //: 十种格子 + 五个工具(「写字」挂在便签上,不在单子里)。
    expect(rows).toHaveLength(15);
    for (const row of rows) {
      const [label, description] = lines(row);
      expect(label, "每一行都有名字").toBeTruthy();
      expect(description, `「${label}」这一行没有说明`).toBeTruthy();
      expect(label).not.toContain("**");
      expect(description).not.toContain("**");
      expect(description).not.toBe(label);
      //: 图标一样大、一样的颜色:都在同一个图标槽里。
      expect(row.querySelector(":scope > span[aria-hidden] svg"), `「${label}」这一行没有图标`).not.toBeNull();
    }
  });

  it("格子那几行是给创作者的一句话(和拉线菜单同一份)", () => {
    const byLabel = Object.fromEntries(openMenu().map((row) => lines(row) as [string, string]));
    expect(byLabel["图片"]).toBe("写一句话生成，或从素材库挑一张");
    expect(byLabel["视频"]).toBe("写一句话、或接一张图生成视频");
    expect(byLabel["音频"]).toBe("配音、音乐或音效");
    expect(byLabel["便签"]).toBe("随手写，或让 AI 写");
    expect(byLabel["文档"]).toBe("引用一篇笔记");
    expect(byLabel["3D 场景"]).toBe("引用一个 3D 场景");
    expect(byLabel["分组"]).toBe("把几格圈在一起");
  });

  it("对象存储的取回工具叫它声明的名字;说明只取第一句、纯文字,出处只写插件名", () => {
    const byLabel = Object.fromEntries(openMenu().map((row) => lines(row) as [string, string]));
    expect(byLabel["从对象存储取回"]).toBe("对象存储 · 把桶里的一个对象拉回素材库。");
    expect(byLabel["导入 ComfyUI 产出"]).toBe("ComfyUI · 把 ComfyUI 历史里的产出收进素材库:给任务号就取那一个,不给就取最近几次。");
    //: 名字已经以出处开头,不再念一遍。
    expect(byLabel["ComfyUI 服务器状态"]).toBe("看一眼显存和队列。");
    //: 没有说明的工具也不空着:至少点名出处。
    expect(byLabel["从百度网盘导入"]).toBe("百度网盘");
  });

  it("说明截在一行里(省略号),不把行撑高", () => {
    for (const row of openMenu()) {
      const description = row.querySelector(":scope > span:not([aria-hidden]) > span:nth-child(2)");
      expect(description?.className).toContain("truncate");
    }
  });
});
