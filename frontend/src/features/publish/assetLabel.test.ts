/**
 * 素材那一格的标题跟着内容类型走(维护者 2026-10-24:「对于图文类型单纯是素材吧,也没有成片的说法」)。
 *
 * 这条钉的是**映射本身**,不是某个 DOM 位置 —— 三种形状各有一个标题、且互不相同,
 * 以后再加一种形状时这里会提醒你给它想个合适的词。
 */
import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";
import { ASSET_LABEL_KEY } from "@/features/publish/PublishView";

for (const locale of ["zh-CN", "en-US"] as const) {
  describe(locale, () => {
    const table = messages[locale] as Record<string, string>;

    it("视频 / 图文 / 文章各有一句自己的标题,而且互不相同", () => {
      const keys = [ASSET_LABEL_KEY.video, ASSET_LABEL_KEY["image-text"], ASSET_LABEL_KEY.article];
      const labels = keys.map((key) => table[key]);
      for (const [index, label] of labels.entries()) {
        expect(typeof label, `${keys[index]} 缺文案`).toBe("string");
        expect(label.trim().length).toBeGreaterThan(0);
      }
      expect(new Set(labels).size).toBe(3);
    });

    it("只有视频那格说「成片」—— 图文与文章说的是图片 / 封面", () => {
      expect(table[ASSET_LABEL_KEY.video]).toMatch(/成片|Finished video|video/i);
      expect(table[ASSET_LABEL_KEY["image-text"]]).toMatch(/图片|Images|photo/i);
      expect(table[ASSET_LABEL_KEY.article]).toMatch(/封面|Cover/i);
      expect(table[ASSET_LABEL_KEY["image-text"]]).not.toMatch(/成片|Finished/);
      expect(table[ASSET_LABEL_KEY.article]).not.toMatch(/成片|Finished/);
    });
  });
}
