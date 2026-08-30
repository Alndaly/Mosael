/**
 * 正文里 `@` 到的素材,提交时落到哪个槽。
 *
 * **@ 的不一定是图片。** 八个角色里有三个收的是整段素材:源视频、首段(视频)、驱动音频。
 * 判错类型的后果是静默的 —— 那份素材根本没发出去,而提示词里还写着它的名字。
 */
import { describe, expect, it } from "vitest";

import { mergeSourceAssets, roleAccepts, sourceSlots } from "./NodeComposer";
import type { GenerationModel } from "@/api/client";

const model = (keys: string[], limits: Record<string, number> = {}): GenerationModel =>
  ({
    provider: "p",
    model: "m",
    capabilities: { parameter_keys: keys, source_limits: limits },
  }) as unknown as GenerationModel;

describe("角色收哪一类素材", () => {
  it("八个角色都判对 —— 兜底成图片会把源视频/首段/驱动音频判错三个", () => {
    expect(roleAccepts("first_frame")).toBe("image");
    expect(roleAccepts("last_frame")).toBe("image");
    expect(roleAccepts("reference_image")).toBe("image");
    expect(roleAccepts("reference_video")).toBe("video");
    expect(roleAccepts("source_video")).toBe("video");
    expect(roleAccepts("first_clip")).toBe("video");
    expect(roleAccepts("reference_audio")).toBe("audio");
    expect(roleAccepts("driving_audio")).toBe("audio");
  });
});

describe("画板上出哪些槽", () => {
  it("整段素材那三种也要出格子 —— 只列前五个的话,声明了它们的模型在画板上用不了", () => {
    const roles = sourceSlots(model(["source_video", "driving_audio", "first_clip"])).map((one) => one.role);
    expect(roles).toEqual(["source_video", "first_clip", "driving_audio"]);
  });
});

describe("@ 到的素材落到哪个槽", () => {
  const library = [
    { id: "img1", kind: "image" },
    { id: "img2", kind: "image" },
    { id: "vid1", kind: "video" },
    { id: "aud1", kind: "audio" },
  ];

  it("视频落到收视频的槽,不会被当成图片", () => {
    const slots = [
      { role: "reference_image", limit: 4 },
      { role: "reference_video", limit: 1 },
    ];
    expect(mergeSourceAssets([], ["vid1"], library, slots)).toEqual([
      { asset_id: "vid1", role: "reference_video" },
    ]);
  });

  it("音频同理", () => {
    const slots = [{ role: "reference_image", limit: 4 }, { role: "driving_audio", limit: 1 }];
    expect(mergeSourceAssets([], ["aud1"], library, slots)).toEqual([
      { asset_id: "aud1", role: "driving_audio" },
    ]);
  });

  it("**装满了就换一个槽** —— 首帧只收一份,第二张图不该也变成首帧", () => {
    const slots = [
      { role: "first_frame", limit: 1 },
      { role: "reference_image", limit: 4 },
    ];
    expect(mergeSourceAssets([], ["img1", "img2"], library, slots)).toEqual([
      { asset_id: "img1", role: "first_frame" },
      { asset_id: "img2", role: "reference_image" },
    ]);
  });

  it("槽位里已经挂着的先算进份数 —— 否则 @ 一张图会顶掉已经设好的首帧", () => {
    const slots = [
      { role: "first_frame", limit: 1 },
      { role: "reference_image", limit: 4 },
    ];
    const out = mergeSourceAssets([{ role: "first_frame", assetId: "img1" }], ["img2"], library, slots);
    expect(out).toEqual([
      { asset_id: "img1", role: "first_frame" },
      { asset_id: "img2", role: "reference_image" },
    ]);
  });

  it("一个装得下的槽都没有就不发 —— 硬塞会被描述符校验把整次生成拒掉", () => {
    const slots = [{ role: "first_frame", limit: 1 }];
    expect(mergeSourceAssets([], ["img1", "img2"], library, slots)).toEqual([
      { asset_id: "img1", role: "first_frame" },
    ]);
  });
});
