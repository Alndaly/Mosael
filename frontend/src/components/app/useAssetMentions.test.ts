/**
 * `@` 什么时候算「正在挑素材」—— 这条判错了,用户打个邮箱地址就会被弹一张素材单子,
 * 或者他明明打了 @ 却什么都不出来。两种都不报错。
 */
import { describe, expect, it } from "vitest";

import { mentionRange } from "./useAssetMentions";

describe("光标前那段 @词", () => {
  it("行首和空白之后的 @ 才算", () => {
    expect(mentionRange("@猫", 2)).toEqual({ start: 0, query: "猫" });
    expect(mentionRange("画一只 @猫", 6)).toEqual({ start: 4, query: "猫" });
  });

  it("贴在字后面的 @ 不算 —— 那是邮箱,不是引用", () => {
    expect(mentionRange("a@b.com", 7)).toBeNull();
  });

  it("打完 @ 又敲了空格就不算了", () => {
    expect(mentionRange("@猫 在窗台", 5)).toBeNull();
  });

  it("光标在 @ 前面时不算 —— 看的是光标**之前**那段", () => {
    expect(mentionRange("画一只@猫", 2)).toBeNull();
  });

  it("空的 @ 也算:刚敲下去就该出全部候选", () => {
    expect(mentionRange("@", 1)).toEqual({ start: 0, query: "" });
  });
});
