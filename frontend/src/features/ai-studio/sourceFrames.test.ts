/**
 * 参考素材和首尾帧的账要算对:**份数**和**分组**。
 *
 * 这两件事在界面上都看不出错。挂了九张参考图只发出去一张,画面照样出得来,只是不像;
 * 首帧配参考图会被接口拒,而拒的话是一句说着 `content` 数组下标的英文。
 */
import { describe, expect, it } from "vitest";

import { exclusiveSourceGroups, sourceLimit } from "@/lib/generationCapabilities";
import {
  emptyFrames,
  filledCount,
  frameUrlParameters,
  sourceAssetsFrom,
  withSlot,
  type SourceRole,
} from "@/features/ai-studio/sourceFrames";

const anyRole = () => true;
const model = (capabilities: Record<string, unknown>) =>
  ({ capabilities } as unknown as Parameters<typeof sourceLimit>[0]);

const slot = (assetId: string) => ({ url: "", assetId, assetName: assetId });

describe("参考素材可以挂多份", () => {
  it("每一份都进 source_assets,不是只发第一份", () => {
    const frames = emptyFrames();
    frames.reference_image = [slot("a"), slot("b"), slot("c")];
    expect(sourceAssetsFrom(frames, anyRole)).toEqual([
      { asset_id: "a", role: "reference_image" },
      { asset_id: "b", role: "reference_image" },
      { asset_id: "c", role: "reference_image" },
    ]);
  });

  it("多条外链发数组而不是拼成一条", () => {
    // 拼成逗号分隔的字符串的话,供应商会把它当成一条打不开的地址 —— 而那时任务已经提交了。
    const frames = emptyFrames();
    frames.reference_image = [
      { url: "https://x/a.png", assetId: "", assetName: "" },
      { url: "https://x/b.png", assetId: "", assetName: "" },
    ];
    expect(frameUrlParameters(frames, anyRole).reference_image_url).toEqual([
      "https://x/a.png",
      "https://x/b.png",
    ]);
  });

  it("只有一条外链时还是发字符串", () => {
    const frames = emptyFrames();
    frames.reference_image = [{ url: "https://x/a.png", assetId: "", assetName: "" }];
    expect(frameUrlParameters(frames, anyRole).reference_image_url).toBe("https://x/a.png");
  });

  it("模型不认的角色一份都不发", () => {
    const frames = emptyFrames();
    frames.reference_video = [slot("v")];
    expect(sourceAssetsFrom(frames, (role: SourceRole) => role !== "reference_video")).toEqual([]);
  });

  it("填满不会自己长出槽位 —— 加一份是按钮说了算", () => {
    // 自动续一个空的会让「还能加几份」变得含糊:那个空槽到底算不算已用的一份?
    // 加号是显式的,旁边的 3/9 计数说的就是真的填了几份。
    expect(withSlot([slot("a")], 0, slot("b"))).toEqual([slot("b")]);
  });

  it("清空中间一个槽位不会留下空洞", () => {
    const after = withSlot([slot("a"), slot("b")], 0, { url: "", assetId: "", assetName: "" });
    expect(after.filter((one) => one.assetId)).toEqual([slot("b")]);
  });
});

describe("上限和分组读的是描述符,不是我们写死的", () => {
  it("描述符给几就是几", () => {
    const m = model({ source_limits: { reference_image: 9, reference_video: 3 } });
    expect(sourceLimit(m, "reference_image")).toBe(9);
    expect(sourceLimit(m, "reference_video")).toBe(3);
  });

  it("没声明就当 1 —— 保守的那一边", () => {
    // 多挂一份的下场是提交被拒;少挂一份只是少一张参考图。
    expect(sourceLimit(model({}), "reference_image")).toBe(1);
    expect(sourceLimit(null, "reference_image")).toBe(1);
  });

  it("互斥分组原样读出来", () => {
    const m = model({
      exclusive_source_groups: [
        ["first_frame", "last_frame"],
        ["reference_image", "reference_video", "reference_audio"],
      ],
    });
    expect(exclusiveSourceGroups(m)).toEqual([
      ["first_frame", "last_frame"],
      ["reference_image", "reference_video", "reference_audio"],
    ]);
  });

  it("没声明就是不互斥,不要替模型编一条规矩", () => {
    expect(exclusiveSourceGroups(model({}))).toEqual([]);
  });
});

describe("filledCount 只数真的填了东西的槽位", () => {
  it("空槽位不算 —— 界面上永远留着一个空的等着填", () => {
    const frames = emptyFrames();
    expect(filledCount(frames, "reference_image")).toBe(0);
    frames.reference_image = [slot("a"), { url: "", assetId: "", assetName: "" }];
    expect(filledCount(frames, "reference_image")).toBe(1);
  });

  it("只填了外链也算", () => {
    const frames = emptyFrames();
    frames.reference_image = [{ url: "https://x/a.png", assetId: "", assetName: "" }];
    expect(filledCount(frames, "reference_image")).toBe(1);
  });
});
