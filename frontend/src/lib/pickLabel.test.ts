/**
 * 一条名字按界面语言挑一句(见 lib/pickLabel):名字是**一组多语言的事实**,挑语言是界面的事 ——
 * 中文界面里那几栏显示中文,英文界面里显示英文,认不出的语言不塌成空白。
 */

import { describe, expect, it } from "vitest";

import { labelValues, pickLabel } from "@/lib/pickLabel";

const PAIR = { zh: "加载图像", en: "LoadImage" };

describe("pickLabel:按界面语言挑一句", () => {
  it("界面语言是中文就挑中文,是英文就挑英文", () => {
    expect(pickLabel(PAIR, "zh")).toBe("加载图像");
    expect(pickLabel(PAIR, "en")).toBe("LoadImage");
  });

  it("界面语言带地区、带大小写也认(`zh-CN` / `zh-Hans` / `EN-US` 认 `zh` / `en`)", () => {
    expect(pickLabel(PAIR, "zh-CN")).toBe("加载图像");
    expect(pickLabel(PAIR, "zh_Hans")).toBe("加载图像");
    expect(pickLabel(PAIR, "EN-US")).toBe("LoadImage");
    //: 表那边的键也可以是带地区的
    expect(pickLabel({ "zh-CN": "加载图像", "en-US": "LoadImage" }, "zh-CN")).toBe("加载图像");
  });

  it("认不出的语言回落到 `en`(这一类数据的原文语言)", () => {
    expect(pickLabel(PAIR, "ja")).toBe("LoadImage");
    expect(pickLabel(PAIR, "")).toBe("LoadImage");
  });

  it("连 `en` 都没有就回落到表里任意一个 —— 有一种写法总比空白强", () => {
    expect(pickLabel({ ja: "画像を読み込む" }, "zh")).toBe("画像を読み込む");
    expect(pickLabel({ fr: "Charger", de: "Laden" }, "zh")).toBe("Charger");
  });

  it("字符串原样透出(插件只给一句的那些项)", () => {
    expect(pickLabel("参考图 · 人物", "en")).toBe("参考图 · 人物");
    expect(pickLabel("步数", "zh")).toBe("步数");
  });

  it("空表、空串、什么都没有都是空串", () => {
    expect(pickLabel({}, "zh")).toBe("");
    expect(pickLabel("", "zh")).toBe("");
    expect(pickLabel(undefined, "zh")).toBe("");
    expect(pickLabel(null, "zh")).toBe("");
    //: 表里那一条是空的当没写(不然会挑出一句空白,界面上就是这一格没名字)
    expect(pickLabel({ zh: "", en: "" }, "zh")).toBe("");
    expect(pickLabel({ zh: "", en: "LoadImage" }, "zh")).toBe("LoadImage");
  });
});

describe("labelValues:一条名字里全部语言的写法(搜索的 haystack)", () => {
  it("表里每一种语言都算数,字符串就是它自己", () => {
    expect(labelValues(PAIR)).toEqual(["加载图像", "LoadImage"]);
    expect(labelValues("种子")).toEqual(["种子"]);
  });

  it("空的、不是字符串的都滤掉", () => {
    expect(labelValues({ zh: "", en: "LoadImage", ja: 3 })).toEqual(["LoadImage"]);
    expect(labelValues("")).toEqual([]);
    expect(labelValues(undefined)).toEqual([]);
  });
});
