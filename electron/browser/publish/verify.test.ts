/**
 * 判定原语:字进没进编辑器 / 每行在不在、顺不顺序。
 *
 * 这几条对应 2026-10-23 真机上判错的四种情形:富文本改写、旧草稿混进来、正文被重排、
 * 以及只判"包含"就放行。原语的口径必须把这几条分清楚。
 */
import { describe, expect, it, vi } from "vitest";

import { linesEntered, squash, textEntered } from "./verify";
import type { PageDriver } from "../driver/pageDriver";

/** 只实现原语用得到的两个方法:读编辑器 / 整页文字。 */
function fakeDriver(editorText: string, bodyText = "") {
  return {
    evaluate: vi.fn(async (expr: string) => {
      //: 原语里读编辑器的那段带 `querySelectorAll`;读整页字数的那段带 `body?.innerText`。
      if (expr.includes("querySelectorAll")) return editorText;
      if (expr.includes("match(")) {
        const found = bodyText.match(/(\d+)\s*\/\s*1000/);
        return found ? found[1] : "";
      }
      return "";
    }),
  } as unknown as PageDriver;
}

describe("squash", () => {
  it("去掉空白与零宽字符 —— 富文本改的只是排版", () => {
    expect(squash("1. 表情\u200b\n2.  衣着")).toBe("1.表情2.衣着");
  });
});

describe("textEntered", () => {
  it("字数计数兜一层:富文本改了标点也算进去了", async () => {
    const driver = fakeDriver("第一行第二行", "35 / 1000");
    await expect(
      textEntered(driver, "div.editor", "第一行、第二行（带标点）", { counter: /(\d+)\s*\/\s*1000/ }),
    ).resolves.toBe(true);
  });

  it("混着上一轮的旧字:**不算**进去(只判包含会放过一条内容不对的发布)", async () => {
    const driver = fakeDriver("旧草稿第一行第二行旧草稿旧草稿旧草稿旧草稿旧草稿旧草稿");
    await expect(textEntered(driver, "div.editor", "第一行\n第二行")).resolves.toBe(false);
  });
});

describe("linesEntered", () => {
  it("每行都在、顺序也对 → 通过", async () => {
    const driver = fakeDriver("1. 表情精细化\n2. 衣着精细");
    const result = await linesEntered(driver, "div.editor", "1. 表情精细化\n2. 衣着精细");
    expect(result.ok).toBe(true);
    expect(result.matched).toBe(2);
  });

  it("字都在但**顺序被重排** → 不通过,并说出对上了几行", async () => {
    const driver = fakeDriver("2. 衣着精细. 1. 表情精细化");
    const result = await linesEntered(driver, "div.editor", "1. 表情精细化\n2. 衣着精细");
    expect(result.ok).toBe(false);
    expect(result.matched).toBeLessThan(result.total);
  });

  it("平台字数计数对得上时宽容一次(富文本把列表改成有序列表)", async () => {
    const driver = fakeDriver("表情精细化衣着精细", "20 / 1000");
    const result = await linesEntered(driver, "div.editor", "1. 表情精细化\n2. 衣着精细", {
      counter: /(\d+)\s*\/\s*1000/,
    });
    expect(result.ok).toBe(true);
  });
});
