/**
 * 素材那一格的标题跟着内容类型走(维护者 2026-10-24:「对于图文类型单纯是素材吧,也没有成片的说法」)。
 *
 * 这条钉的是**映射本身**,不是某个 DOM 位置 —— 三种形状各有一个标题、且互不相同,
 * 以后再加一种形状时这里会提醒你给它想个合适的词。
 */
import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";
import { ASSET_LABEL_KEY, COVER_HINT_KEY } from "@/features/publish/PublishView";

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

describe("文章封面的提示是**声明式**的", () => {
  /**
   * 以前这句是写死在通用表单里的「抖音的文章必须有一张」—— 平台名进通用表单,
   * 第二个平台要封面时只能往句子里再加一个名字。现在三档声明对三句文案,平台名只在后端声明里。
   */
  for (const locale of ["zh-CN", "en-US"] as const) {
    const table = messages[locale] as Record<string, string>;

    it(`${locale}:required / optional / none 各有自己的说法`, () => {
      const keys = [COVER_HINT_KEY.required, COVER_HINT_KEY.optional, COVER_HINT_KEY.none];
      const labels = keys.map((key) => table[key]);
      for (const label of labels) expect(typeof label).toBe("string");
      expect(new Set(labels).size).toBe(3);
    });

    it(`${locale}:只有 required 那句说"必填",只有 none 那句说"平台生成"`, () => {
      expect(table[COVER_HINT_KEY.required]).toMatch(/必填|Required/);
      expect(table[COVER_HINT_KEY.none]).toMatch(/生成|builds|auto/i);
      expect(table[COVER_HINT_KEY.optional]).not.toMatch(/必填|Required/);
    });

    it(`${locale}:提示里**不出现平台名**(平台是声明,不该写进句子)`, () => {
      for (const key of Object.values(COVER_HINT_KEY)) {
        expect(table[key]).not.toMatch(/抖音|小红书|Douyin|Xiaohongshu/i);
      }
    });
  }
});
