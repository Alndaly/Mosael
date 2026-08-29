/**
 * 正文里的素材 chip 要能被**收出来** —— 收不出来的话,用户在句子里 @ 了图,提交时那张图
 * 却没跟着发出去:界面上明明写着,生成结果里却没有它,而没有任何地方会报错。
 */
import { describe, expect, it } from "vitest";

import { collect } from "./PromptEditor";

const doc = (...content: unknown[]) => ({ type: "doc", content });
const para = (...content: unknown[]) => ({ type: "paragraph", content });
const chip = (id: string) => ({ type: "assetRef", attrs: { assetId: id, name: `${id}.png` } });
const text = (value: string) => ({ type: "text", text: value });

describe("收正文里的素材引用", () => {
  it("按出现顺序收", () => {
    expect(collect(doc(para(text("把 "), chip("a"), text(" 和 "), chip("b"), text(" 拼一起"))))).toEqual(["a", "b"]);
  });

  it("同一张 @ 了两次只算一次 —— 重复发一份会被厂商算进参考图的份数", () => {
    expect(collect(doc(para(chip("a"), text(" 再来一次 "), chip("a"))))).toEqual(["a"]);
  });

  it("嵌在更深一层里也要收得到", () => {
    expect(collect(doc(para(text("上")), para(text("下 "), chip("c"))))).toEqual(["c"]);
  });

  it("没有 chip 就是空,不是 undefined", () => {
    expect(collect(doc(para(text("光是一句话"))))).toEqual([]);
    expect(collect(null)).toEqual([]);
  });
})
