/**
 * 参数控件由**模型的描述符**决定,不由 kind 写死。
 *
 * 这条防的 bug 很具体:视频那一支此前把参数名写死成 `resolution` / `aspect_ratio` /
 * `first_frame`,于是一个声明了 `size` 的模型 —— 万相就是 —— 在界面上**连尺寸这一栏都不出现**,
 * 发出去的参数里也没有它。描述符说了话而界面没听,而那套描述符存在的全部意义就是让界面照着它渲染。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { describe, expect, it } from "vitest";

import { durationOptions, sizeOptions, supportsParameter, videoResolutionOptions } from "@/lib/generationCapabilities";

type Model = Parameters<typeof sizeOptions>[0];

const wan = {
  kind: "video",
  capabilities: {
    parameter_keys: ["duration_seconds", "size", "first_frame"],
    sizes: ["832*480", "1280*720"],
    duration_seconds: [5],
  },
} as unknown as Model;

const seedance = {
  kind: "video",
  capabilities: {
    parameter_keys: ["duration_seconds", "resolution", "first_frame"],
    resolutions: ["480p", "720p", "1080p"],
    duration_seconds: [5, 10],
  },
} as unknown as Model;

describe("尺寸这一栏跟着描述符走", () => {
  it("声明了 size 的**视频**模型也有尺寸可选", () => {
    expect(supportsParameter(wan, "size")).toBe(true);
    expect(sizeOptions(wan)).toEqual(["832*480", "1280*720"]);
  });

  it("没声明 size 的视频模型不该凭空多出一栏", () => {
    expect(supportsParameter(seedance, "size")).toBe(false);
    expect(sizeOptions(seedance)).toEqual([]);
  });

  it("两家各拿各的那一档,互不干扰", () => {
    expect(videoResolutionOptions(seedance)).toEqual(["480p", "720p", "1080p"]);
    expect(videoResolutionOptions(wan)).toEqual([]);
    expect(durationOptions(wan)).toEqual([5]);
    expect(durationOptions(seedance)).toEqual([5, 10]);
  });

  it("视频模型不给尺寸兜底 —— 猜一个出来比不给更糟", () => {
    /** 图像有一组人人都认的常见尺寸,可以兜底;视频没有 ——
     *  猜出来的档位选中之后会被供应商拒掉,而用户以为那是能用的。 */
    const bare = { kind: "video", capabilities: { parameter_keys: ["size"] } } as unknown as Model;
    expect(sizeOptions(bare)).toEqual([]);
  });

  it("没有 parameter_keys 的模型一律放行(老数据不该因为没填就什么都不能调)", () => {
    const legacy = { kind: "image", capabilities: {} } as unknown as Model;
    expect(supportsParameter(legacy, "size")).toBe(true);
    expect(supportsParameter(legacy, "anything")).toBe(true);
  });
});
