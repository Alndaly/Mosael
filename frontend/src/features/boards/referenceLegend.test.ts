/**
 * 提示词末尾那段「谁是第几张」。
 *
 * 模型收到的是一串**没有名字**的图。用户在正文里写「把 创作者.png 里的人放到 街景.jpg」,
 * 那两个名字对他有意义,对模型只是两个词 —— 它拿到的是 `image: [url, url]`。一两张时还能
 * 靠顺序猜,而这个界面本来就是让人 @ 很多张的。
 */
import { describe, expect, it } from "vitest";

import { referenceLegend } from "./NodeComposer";

const label = (role: string) => (role === "first_frame" ? "首帧" : "参考图");

const library = [
  { id: "a", name: "创作者.png" },
  { id: "b", name: "街景.jpg" },
  { id: "c", name: "" as string | null, original_filename: "开场.png" },
  { id: "dup", name: "创作者.png" },
  { id: "none", name: "" as string | null, original_filename: "" as string | null },
];

describe("参考素材对应关系", () => {
  it("按出现顺序编号", () => {
    const out = referenceLegend(
      [{ asset_id: "a", role: "reference_image" }, { asset_id: "b", role: "reference_image" }],
      library,
      label,
    );
    expect(out).toBe("参考图 1 = 创作者.png; 参考图 2 = 街景.jpg");
  });

  it("**每个角色各数各的** —— 适配器是按角色过滤成一串的,跨角色连着数会把首帧算成参考图第一张", () => {
    const out = referenceLegend(
      [
        { asset_id: "c", role: "first_frame" },
        { asset_id: "a", role: "reference_image" },
        { asset_id: "b", role: "reference_image" },
      ],
      library,
      label,
    );
    expect(out).toBe("首帧 1 = 开场.png\n参考图 1 = 创作者.png; 参考图 2 = 街景.jpg");
  });

  it("名字为空的那份不写进来 —— 「参考图 2 = 」比不写更糟", () => {
    const out = referenceLegend(
      [{ asset_id: "a", role: "reference_image" }, { asset_id: "none", role: "reference_image" }],
      library,
      label,
    );
    expect(out).toBe("参考图 1 = 创作者.png");
  });

  it("没有素材就不出这一段 —— 一句空说明会白占提示词", () => {
    expect(referenceLegend([], library, label)).toBe("");
  });

  it("重名也分得开:说明里带着序号", () => {
    const out = referenceLegend(
      [{ asset_id: "a", role: "reference_image" }, { asset_id: "dup", role: "reference_image" }],
      library,
      label,
    );
    expect(out).toBe("参考图 1 = 创作者.png; 参考图 2 = 创作者.png");
  });
});
