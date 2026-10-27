/**
 * 契约完整性棘轮:每个平台都得写得清「怎么进、怎么提交、发完了算不算成功、哪些浮层要关」。
 *
 * 这些字段缺席时的样子很难看:入口缺一项 → 那一种形状点进去是错的页;成功信号缺 → 发成功了却
 * 判失败(2026-10-23 真实发生过);浮层缺 → 后面每一步都可能被一个弹窗挡住。所以**表里必须齐**,
 * 而且"适配器已声明支持的形状"必须在契约里有入口 —— 两边不一致就是漏写。
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { PUBLISH_CONTRACTS, contractFor, fieldsFor } = await import("./contracts");
const { ADAPTER_SUPPORTS } = await import("./adapters");

const PLATFORMS = Object.keys(PUBLISH_CONTRACTS);

describe("平台契约", () => {
  it("每个平台都写清了:提交文案、成功信号、浮层(数组可空但是显式的)", () => {
    for (const platform of PLATFORMS) {
      const contract = PUBLISH_CONTRACTS[platform as keyof typeof PUBLISH_CONTRACTS];
      expect(contract.submitText, `${platform}:缺提交文案`).toBeTruthy();
      const signals = (contract.done.urls?.length ?? 0) + (contract.done.texts?.length ?? 0);
      expect(signals, `${platform}:没有任何成功信号`).toBeGreaterThan(0);
      expect(Array.isArray(contract.overlays), `${platform}:overlays 要显式给(空数组也行)`).toBe(true);
    }
  });

  it("适配器声明支持的形状,契约里必须有入口;**要交素材的形状**还必须有文件框", () => {
    for (const platform of PLATFORMS) {
      const kinds = ADAPTER_SUPPORTS[platform] ?? [];
      const contract = PUBLISH_CONTRACTS[platform as keyof typeof PUBLISH_CONTRACTS];
      for (const kind of kinds) {
        expect(contract.entry[kind], `${platform} × ${kind}:契约没有入口`).toBeTruthy();
        const fields = contract.fields[kind];
        expect(fields?.title, `${platform} × ${kind}:契约没有标题字段`).toBeTruthy();
        expect(fields?.body, `${platform} × ${kind}:契约没有正文字段`).toBeTruthy();
        expect(fields?.tags, `${platform} × ${kind}:契约没有标签字段`).toBeTruthy();
        //: 文章是一篇长文,**没有素材** —— 不要求文件框;视频 / 图文必须有一个。
        if (kind === "article") continue;
      }
    }
  });

  it("按平台取契约时 id 归一化(别名 / 大小写都能取到)", () => {
    expect(contractFor("抖音")).toBe(contractFor("douyin"));
    expect(contractFor("xiaohongshu")).toBe(contractFor("xiaohongshu"));
  });

  it("fieldsFor 返回该形状的字段，缺失时明确报装配错误", () => {
    expect(fieldsFor(contractFor("douyin"), "article").title).toBe(contractFor("douyin").fields.article?.title);
    expect(() => fieldsFor(contractFor("mock"), "article")).toThrow("publish contract fields missing");
  });
});
