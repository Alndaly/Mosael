import { describe, expect, it } from "vitest";

import { assetKindKey, IMPORT_ACCEPT, isDocumentFile, isImportableFile, isMediaAsset } from "./assetKinds";

/** 文档进素材库(ADR 0031):选文件、拖进来都收文档;时间线、生成参考只认媒体。 */
describe("素材种类", () => {
  const file = (name: string, type = "") => new File(["x"], name, { type });

  it("文档按扩展名认(docx、md 的类型各系统报得不一样);压缩包这类不收", () => {
    expect(isDocumentFile(file("方案.PPTX"))).toBe(true);
    expect(isImportableFile(file("readme.md"))).toBe(true);
    expect(isImportableFile(file("clip.mov", "video/quicktime"))).toBe(true);
    expect(isImportableFile(file("工具.zip", "application/zip"))).toBe(false);
    expect(IMPORT_ACCEPT).toContain(".docx");
  });

  it("文档不是媒体;种类名认得文档", () => {
    expect(isMediaAsset({ kind: "document" })).toBe(false);
    expect(isMediaAsset({ kind: "audio" })).toBe(true);
    expect(assetKindKey("document")).toBe("kindDocument");
  });
});
