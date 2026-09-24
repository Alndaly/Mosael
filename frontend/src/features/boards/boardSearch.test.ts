import { describe, expect, it } from "vitest";

import type { BoardItem } from "@/api/client";
import { messages, type MessageKey } from "@/app/messages";
import { matchCanvasEntries } from "@/components/app/CanvasNodeSearch";

import { searchFocusZoom } from "./BoardCanvas";
import { boardSearchEntries } from "./boardSearch";

const t = (key: MessageKey) => messages["zh-CN"][key];

const items: BoardItem[] = [
  { id: "n1", kind: "note", x: 0, y: 0, text: "开场白\n先讲痛点,再讲猫" },
  { id: "i1", kind: "image", x: 0, y: 0, form: { prompt: "一只橘猫趴在窗台" } },
  { id: "v1", kind: "video", x: 0, y: 0 },
  { id: "f1", kind: "frame", x: 0, y: 0, text: "第一幕" },
];

describe("画板的查找条目", () => {
  it("标题取正文第一行,没有正文取提示词,都没有退到类型", () => {
    const entries = boardSearchEntries(items, t);
    expect(entries.map((one) => one.title)).toEqual(["开场白", "一只橘猫趴在窗台", t("boardKindVideo"), "第一幕"]);
    expect(entries.map((one) => one.subtitle)).toEqual([
      t("boardKindNote"),
      t("boardKindImage"),
      t("boardKindVideo"),
      t("boardKindFrame"),
    ]);
  });

  it("正文全文、提示词、类型(显示名和原始值)都搜得到", () => {
    const entries = boardSearchEntries(items, t);
    expect(matchCanvasEntries(entries, "猫").map((one) => one.id)).toEqual(["n1", "i1"]);
    expect(matchCanvasEntries(entries, "video").map((one) => one.id)).toEqual(["v1"]);
    expect(matchCanvasEntries(entries, t("boardKindFrame")).map((one) => one.id)).toEqual(["f1"]);
  });

  it("太长的第一行截断,列表里一行放得下", () => {
    const [entry] = boardSearchEntries([{ id: "n", kind: "note", x: 0, y: 0, text: "字".repeat(100) }], t);
    expect(entry!.title).toHaveLength(61);
    expect(entry!.title.endsWith("…")).toBe(true);
  });
});

describe("跳到命中项时的缩放", () => {
  const visible = { width: 1000, height: 800 };
  it("拉远着的时候拉近到看得清", () => {
    expect(searchFocusZoom(0.3, { width: 200, height: 120 }, visible)).toBe(0.9);
  });
  it("用户自己拉近的、而且放得下,保持原样", () => {
    expect(searchFocusZoom(1.6, { width: 200, height: 120 }, visible)).toBe(1.6);
  });
  it("节点大到放不下时退到刚好装得下", () => {
    expect(searchFocusZoom(1, { width: 2000, height: 400 }, visible)).toBeCloseTo(1000 / 2500);
  });
});
