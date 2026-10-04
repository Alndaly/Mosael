/**
 * 确认卡上「原文 → 新文」的差异:按字(中文)/ 词(西文)对齐,没变的照常、删去的划掉、新加的高亮。
 */
import { expect, it } from "vitest";
import { diffText } from "./textDiff";

it("中文按字对齐:只标出真正换掉的那几个字", () => {
  expect(diffText("开场的三十秒还是太慢。", "开场三十秒节奏偏慢。")).toEqual([
    { kind: "same", text: "开场" },
    { kind: "del", text: "的" },
    { kind: "same", text: "三十秒" },
    { kind: "del", text: "还是太" },
    { kind: "ins", text: "节奏偏" },
    { kind: "same", text: "慢。" },
  ]);
});

it("西文按词对齐,不把一个词拆成几个字母", () => {
  expect(diffText("the quick fox", "the slow fox")).toEqual([
    { kind: "same", text: "the " },
    { kind: "del", text: "quick" },
    { kind: "ins", text: "slow" },
    { kind: "same", text: " fox" },
  ]);
});

it("整段删掉 / 整段新写", () => {
  expect(diffText("要删的一句", "")).toEqual([{ kind: "del", text: "要删的一句" }]);
  expect(diffText("", "新写的一句")).toEqual([{ kind: "ins", text: "新写的一句" }]);
});

it("很长、差异又多的两段不逐字对齐(太贵),退回整段删 + 整段加", () => {
  const a = "甲".repeat(3000);
  const b = "乙".repeat(3000);
  expect(diffText(a, b)).toEqual([{ kind: "del", text: a }, { kind: "ins", text: b }]);
});
