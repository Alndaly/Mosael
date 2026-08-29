/**
 * 表单上出现哪几个输入素材槽,**由描述符说了算**。
 *
 * 这件事错了不会报错:图片模型上凭空长出「首帧」「尾帧」两个槽,点开是图片选择器,挂上去也
 * 能提交 —— 一直到后端照描述符校验时才拒。而这条错误路径此前正是这么来的:拿 sourceLimit
 * (它对没声明的角色兜底返回 1)当成了「认不认这个角色」的判定,于是每个模型都拿到四个槽。
 */
import { describe, expect, it } from "vitest";

import { sourceSlots } from "./NodeComposer";
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
    expect(modeLabel(["first_frame", "last_frame"])).toBe("首尾帧");
    expect(modeLabel(["reference_image"])).toBe("全能参考");
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
