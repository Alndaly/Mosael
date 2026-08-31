/**
 * 表单上出现哪几个输入素材槽,**由描述符说了算**。
 *
 * 这件事错了不会报错:图片模型上凭空长出「首帧」「尾帧」两个槽,点开是图片选择器,挂上去也
 * 能提交 —— 一直到后端照描述符校验时才拒。而这条错误路径此前正是这么来的:拿 sourceLimit
 * (它对没声明的角色兜底返回 1)当成了「认不认这个角色」的判定,于是每个模型都拿到四个槽。
 */
import { describe, expect, it } from "vitest";

import { durationRangeOptions, sourceSlots } from "./NodeComposer";
import type { GenerationModel } from "@/api/client";

const model = (parameterKeys: string[], sourceLimits: Record<string, number> = {}) =>
  ({ capabilities: { parameter_keys: parameterKeys, source_limits: sourceLimits } }) as unknown as GenerationModel;

describe("输入素材槽照描述符出", () => {
  it("只声明参考图的模型不给首尾帧", () => {
    expect(sourceSlots(model(["reference_image"], { reference_image: 3 }))).toEqual([
      { role: "reference_image", limit: 3 },
    ]);
  });

  it("声明了首尾帧的才给首尾帧", () => {
    expect(sourceSlots(model(["first_frame", "last_frame"]))).toEqual([
      { role: "first_frame", limit: 1 },
      { role: "last_frame", limit: 1 },
    ]);
  });

  it("份数照 source_limits,没写的按一份", () => {
    const slots = sourceSlots(model(["reference_image", "reference_video"], { reference_image: 9 }));
    expect(slots).toEqual([
      { role: "reference_image", limit: 9 },
      { role: "reference_video", limit: 1 },
    ]);
  });

  it("没模型就没槽", () => {
    expect(sourceSlots(null)).toEqual([]);
  });
});

describe("区间时长在紧凑参数行中的呈现", () => {
  it("展开区间内每个合法整数，不退回浏览器原生数字框", () => {
    expect(durationRangeOptions({ min: 4, max: 8 })).toEqual([
      { value: "4", label: "4s" },
      { value: "5", label: "5s" },
      { value: "6", label: "6s" },
      { value: "7", label: "7s" },
      { value: "8", label: "8s" },
    ]);
  });
});

/**
 * 连了线就该把上游的产出**自动挂上**,而且挂进哪一组由「生成方式」定。
 *
 * 连了线还要再挂一遍素材,那条线就只是根装饰;挂错组则更糟 —— 首尾帧和参考素材是厂商的
 * 硬约束(描述符 exclusive_source_groups 里写着),混着发会吃一个说着 content 下标的英文 400。
 */
import { autoAssign, defaultMode, modeLabel, roleAccepts, sourceModes } from "./NodeComposer";

const seedance = () =>
  ({
    capabilities: {
      parameter_keys: ["first_frame", "last_frame", "reference_image", "reference_video"],
      source_limits: { reference_image: 9, reference_video: 3 },
      exclusive_source_groups: [
        ["first_frame", "last_frame"],
        ["reference_image", "reference_video", "reference_audio"],
      ],
    },
  }) as unknown as GenerationModel;

const img = (id: string) => ({ assetId: id, kind: "image" });

describe("生成方式照描述符的互斥分组出", () => {
  it("两组都在就给两种方式,并且只留模型真认的角色", () => {
    // reference_audio 没在 parameter_keys 里 —— 不能因为组里写了就摆出来。
    expect(sourceModes(seedance())).toEqual([
      { key: "first_frame", roles: ["first_frame", "last_frame"] },
      { key: "reference_image", roles: ["reference_image", "reference_video"] },
    ]);
  });

  it("只有一组就没得选,不显示开关", () => {
    const model = {
      capabilities: {
        parameter_keys: ["first_frame"],
        exclusive_source_groups: [["first_frame"], ["reference_image"]],
      },
    } as unknown as GenerationModel;
    expect(sourceModes(model)).toEqual([]);
  });

  it("组名从成员推出来,不另立一张表", () => {
    //: 回的是 i18n 的 key —— 这个名字要出现在参数行的下拉里,写死中文的话英文界面就是半中半英。
    expect(modeLabel(["first_frame", "last_frame"])).toBe("boardModeKeyframes");
    expect(modeLabel(["reference_image"])).toBe("boardModeReference");
  });
});

describe("上游产出自动挂进槽位", () => {
  it("一张图默认当首帧", () => {
    const modes = sourceModes(seedance());
    expect(defaultMode(modes, seedance(), [img("a")])).toBe("first_frame");
    expect(autoAssign(sourceSlots(seedance(), ["first_frame", "last_frame"]), [img("a")])).toEqual([
      { role: "first_frame", assetId: "a" },
    ]);
  });

  it("多张图切到参考,而不是硬塞进首尾帧", () => {
    const modes = sourceModes(seedance());
    expect(defaultMode(modes, seedance(), [img("a"), img("b"), img("c")])).toBe("reference_image");
    expect(
      autoAssign(sourceSlots(seedance(), ["reference_image", "reference_video"]), [img("a"), img("b"), img("c")]),
    ).toEqual([
      { role: "reference_image", assetId: "a" },
      { role: "reference_image", assetId: "b" },
      { role: "reference_image", assetId: "c" },
    ]);
  });

  it("两张图填满首尾帧", () => {
    expect(autoAssign(sourceSlots(seedance(), ["first_frame", "last_frame"]), [img("a"), img("b")])).toEqual([
      { role: "first_frame", assetId: "a" },
      { role: "last_frame", assetId: "b" },
    ]);
  });

  it("类别对不上的不硬塞:视频挂不进首帧", () => {
    const upstream = [{ assetId: "v", kind: "video" }, img("a")];
    expect(autoAssign(sourceSlots(seedance(), ["first_frame", "last_frame"]), upstream)).toEqual([
      { role: "first_frame", assetId: "a" },
    ]);
    // 而在参考那组里,视频有它自己的槽。
    expect(autoAssign(sourceSlots(seedance(), ["reference_image", "reference_video"]), upstream)).toEqual([
      { role: "reference_image", assetId: "a" },
      { role: "reference_video", assetId: "v" },
    ]);
  });

  it("同一份素材不会挂进两个槽", () => {
    expect(autoAssign(sourceSlots(seedance(), ["first_frame", "last_frame"]), [img("a")])).toHaveLength(1);
  });

  it("角色收哪一类只此一处说了算", () => {
    expect(roleAccepts("first_frame")).toBe("image");
    expect(roleAccepts("reference_video")).toBe("video");
    expect(roleAccepts("reference_audio")).toBe("audio");
  });
});

/**
 * 提交时发出去的输入素材 = 槽位上挂的 + 正文里 @ 到的。两条规矩错了都不报错:
 * 重复发一份会被厂商算进份数、挂到上限就整次被拒;而硬塞一个没有槽可落的素材,
 * 会被描述符校验当场拒掉,连带整次生成都发不出去。
 */
import { mergeSourceAssets } from "./NodeComposer";

const lib = [
  { id: "a", kind: "image" },
  { id: "b", kind: "image" },
  { id: "v", kind: "video" },
];

describe("槽位和正文引用合到一起", () => {
  const slots = [{ role: "reference_image", limit: 9 }];

  it("正文里 @ 到的落到第一个收得下它的槽", () => {
    expect(mergeSourceAssets([], ["a"], lib, slots)).toEqual([{ asset_id: "a", role: "reference_image" }]);
  });

  it("同一份不发两遍 —— 槽位上挂过的,正文里再 @ 一次也只算一份", () => {
    expect(mergeSourceAssets([{ role: "first_frame", assetId: "a" }], ["a", "b"], lib, slots)).toEqual([
      { asset_id: "a", role: "first_frame" },
      { asset_id: "b", role: "reference_image" },
    ]);
  });

  it("没有槽收得下就不发 —— 这个模型不认参考视频", () => {
    expect(mergeSourceAssets([], ["v", "a"], lib, slots)).toEqual([{ asset_id: "a", role: "reference_image" }]);
  });

  it("库里查不到的 id 也不发 —— 认不出类别就找不到该落哪儿", () => {
    expect(mergeSourceAssets([], ["幽灵"], lib, slots)).toEqual([]);
  });
});
