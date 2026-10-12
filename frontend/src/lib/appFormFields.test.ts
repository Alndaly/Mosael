/**
 * 「表上的一项用哪一格画」只有一处判据 —— 这条防的 bug 很具体:表单项的归类此前写在生成面板里,预览那一栏自己又
 * 排了一套顺序(提示词 → 反向提示词 → 素材槽 → 尺寸 → 张数 → 种子 → 参数),于是作者在中间把「参考图」拖到
 * 「放大倍数」下面,预览里看不出任何变化 —— 而用的人看到的偏偏是面板那一份。
 *
 * 顺带钉住两条容易被改错的老规矩:表上那一格可以写成角色,也可以写成 `<节点>.<输入名>`(按 `source_keys` 认);
 * 视频模型上首帧、尾帧在生成面板里是一个控件里的两格 —— 两格**都留在表上**、各盖一枚配对标记,由面板按它只画一次
 * (预览没有那个控件,它照表画两格;此前这里把尾帧那一项整个丢掉,预览里就少了一格)。
 */

import { describe, expect, it } from "vitest";

import { appFormFields } from "@/lib/appFormFields";

type Model = Parameters<typeof appFormFields>[0];
/** 一份描述符(不是「还没到清单」的那种 null) */
type Descriptor = NonNullable<Model>;

/** 一张 ComfyUI 视频工作流的描述符:宿主键、角色 + `source_keys`(槽位在表上叫什么)、两个声明参数。 */
const video = {
  kind: "video",
  capabilities: {
    parameter_keys: ["prompt", "first_frame", "last_frame", "reference_image", "size", "num_images", "3.steps", "13.strength_model"],
    source_limits: { first_frame: 1, last_frame: 1, reference_image: 2 },
    source_keys: { first_frame: ["49.image"], last_frame: ["50.image"], reference_image: ["10.image", "14.image"] },
    parameter_schema: {
      "3.steps": { type: "integer", title: "步数" },
      "13.strength_model": { type: "number", title: "放大倍数" },
    },
  },
} as unknown as Descriptor;

const kinds = (model: Model, items: { key: string; label?: string }[]) =>
  appFormFields(model, items).map((one) => [one.key, one.kind]);

describe("表上的一项用哪一格画", () => {
  it("顺序原样保留:跨类混排也是 [参数, 参考图, 参数]", () => {
    const items = [{ key: "13.strength_model" }, { key: "10.image" }, { key: "3.steps" }];
    expect(kinds(video, items)).toEqual([
      ["13.strength_model", "parameter"],
      ["10.image", "source"],
      ["3.steps", "parameter"],
    ]);
    //: 表上怎么写就怎么算:参数那一项的 key 留在 parameterKey 上,素材那一项留下它算出来的角色。
    expect(appFormFields(video, items)).toEqual([
      { key: "13.strength_model", label: "", kind: "parameter", parameterKey: "13.strength_model" },
      { key: "10.image", label: "", kind: "source", role: "reference_image" },
      { key: "3.steps", label: "", kind: "parameter", parameterKey: "3.steps" },
    ]);
  });

  it("宿主自己的那几格:prompt / negative_prompt / seed / size / num_images", () => {
    const items = [
      { key: "prompt", label: "描述" },
      { key: "negative_prompt", label: "不要什么" },
      { key: "seed", label: "" },
      { key: "size", label: "画幅" },
      { key: "num_images", label: "几张" },
    ];
    expect(kinds(video, items)).toEqual([
      ["prompt", "prompt"],
      ["negative_prompt", "negative_prompt"],
      ["seed", "seed"],
      ["size", "size"],
      ["num_images", "num_images"],
    ]);
    expect(appFormFields(video, items).map((one) => one.label)).toEqual(["描述", "不要什么", "", "画幅", "几张"]);
  });

  it("key 本身就是角色,和按 source_keys 算出来的角色,都算这一格的槽位", () => {
    const fields = appFormFields(video, [
      { key: "reference_image", label: "参考图" },
      { key: "49.image", label: "首帧" },
      { key: "14.image", label: "" },
    ]);
    expect(fields).toEqual([
      { key: "reference_image", label: "参考图", kind: "source", role: "reference_image" },
      { key: "49.image", label: "首帧", kind: "source", role: "first_frame" },
      //: `source_keys` 认出来的角色:key 保留表上的写法,parameterKey 空着
      { key: "14.image", label: "", kind: "source", role: "reference_image" },
    ]);
  });

  it("认不出的键算描述符声明的参数:parameterKey 就是表上的 key(认不认得出由调用方查 parameter_schema)", () => {
    expect(appFormFields(video, [{ key: "9.unknown" }])).toEqual([
      { key: "9.unknown", label: "", kind: "parameter", parameterKey: "9.unknown" },
    ]);
    //: 没有描述符(清单还没到)时也一样:归类不靠 model,只有角色那一支要问它
    expect(appFormFields(null, [{ key: "3.steps" }])).toEqual([
      { key: "3.steps", label: "", kind: "parameter", parameterKey: "3.steps" },
    ]);
  });
});

describe("视频模型上的首帧、尾帧", () => {
  it("两格都在表上:两格都留下,各盖一枚配对标记(面板按它画一个控件,预览照表画两格)", () => {
    const items = [{ key: "prompt" }, { key: "49.image" }, { key: "50.image" }];
    expect(appFormFields(video, items)).toEqual([
      { key: "prompt", label: "", kind: "prompt" },
      { key: "49.image", label: "", kind: "source", role: "first_frame", pair: "keyframes" },
      { key: "50.image", label: "", kind: "source", role: "last_frame", pair: "keyframes" },
    ]);
    //: 表上写的是角色也一样 —— 这是维护者那张表(`video_minimax_h3_i2v` 的「首尾帧生成视频」):两格都在,谁也不少
    expect(appFormFields(video, [{ key: "first_frame" }, { key: "last_frame" }]).map((one) => [one.key, one.role, one.pair]))
      .toEqual([["first_frame", "first_frame", "keyframes"], ["last_frame", "last_frame", "keyframes"]]);
  });

  it("只有一格就没有配对标记:它自己就是一个控件", () => {
    expect(appFormFields(video, [{ key: "50.image" }, { key: "prompt" }])).toEqual([
      { key: "50.image", label: "", kind: "source", role: "last_frame" },
      { key: "prompt", label: "", kind: "prompt" },
    ]);
    expect(appFormFields(video, [{ key: "49.image" }])).toEqual([
      { key: "49.image", label: "", kind: "source", role: "first_frame" },
    ]);
  });

  it("尾帧排在首帧前面时两个都在,顺序照样是表上的顺序(作者就是那么排的)", () => {
    expect(appFormFields(video, [{ key: "50.image" }, { key: "49.image" }]).map((one) => [one.role, one.pair])).toEqual([
      ["last_frame", "keyframes"],
      ["first_frame", "keyframes"],
    ]);
  });

  it("不是视频就没有配对标记(图像工作流里首尾帧只是两个槽位)", () => {
    const image = { kind: "image", capabilities: video.capabilities } as unknown as Descriptor;
    expect(appFormFields(image, [{ key: "49.image" }, { key: "50.image" }]).map((one) => [one.role, one.pair])).toEqual([
      ["first_frame", undefined],
      ["last_frame", undefined],
    ]);
  });
});
