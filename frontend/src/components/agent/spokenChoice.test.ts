/**
 * 说的话对到哪个选项。**猜错了不会报错** —— 它只是顺着一条你没选的路一直做下去,
 * 而你以为自己选的是另一条。所以这里验的重点不是"能不能认出来",是"拿不准时会不会硬猜"。
 */

import { describe, expect, it } from "vitest";

import { matchSpokenChoice } from "@/components/agent/spokenChoice";

const OPTIONS = ["告白场景", "失恋与救赎", "架空异世界"];

describe("说的话对到哪个选项", () => {
  it("说标签就选那一个", () => {
    expect(matchSpokenChoice("失恋与救赎", OPTIONS)).toEqual({ kind: "picked", index: 1 });
  });

  it("说标签的一部分也认 —— 人不会每次都念全", () => {
    expect(matchSpokenChoice("告白", OPTIONS)).toEqual({ kind: "picked", index: 0 });
  });

  it("说序号也认", () => {
    expect(matchSpokenChoice("第三个", OPTIONS)).toEqual({ kind: "picked", index: 2 });
    expect(matchSpokenChoice("第一", OPTIONS)).toEqual({ kind: "picked", index: 0 });
  });

  it("标点和空格不算数 —— 识别结果常带句号", () => {
    expect(matchSpokenChoice("告白场景。", OPTIONS)).toEqual({ kind: "picked", index: 0 });
    expect(matchSpokenChoice(" 失恋 与 救赎 ", OPTIONS)).toEqual({ kind: "picked", index: 1 });
  });

  it("命中两个就说拿不准,不替他挑", () => {
    // 「导出」同时是两个选项的一部分。硬挑一个的话,他以为自己选的是另一个。
    const result = matchSpokenChoice("导出", ["导出成片", "导出字幕"]);
    expect(result.kind).toBe("ambiguous");
  });

  it("一个前缀是另一个时,说全了要选中说全的那个", () => {
    // 只有"包含"判据的话,「导出」会同时命中两个 —— 完全一致要优先。
    expect(matchSpokenChoice("导出", ["导出", "导出并发布"])).toEqual({ kind: "picked", index: 0 });
  });

  it("完全没关系的话就是没命中", () => {
    expect(matchSpokenChoice("帮我把音量调大一点", OPTIONS)).toEqual({ kind: "none" });
  });

  it("超出选项数量的序号不算命中", () => {
    // 三个选项时说「第五个」—— 那多半是识别错了,不该悄悄落到某一个上。
    expect(matchSpokenChoice("第五个", OPTIONS)).toEqual({ kind: "none" });
  });

  it("空话不命中", () => {
    expect(matchSpokenChoice("  ", OPTIONS)).toEqual({ kind: "none" });
    expect(matchSpokenChoice("告白", [])).toEqual({ kind: "none" });
  });

  it("英文选项也认序号和标签", () => {
    const english = ["Keep the template", "Run it now"];
    expect(matchSpokenChoice("second", english)).toEqual({ kind: "picked", index: 1 });
    expect(matchSpokenChoice("run it now", english)).toEqual({ kind: "picked", index: 1 });
  });
});
