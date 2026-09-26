import { describe, expect, it } from "vitest";

import { assetItem, clipboardContent } from "./boardPlacement";

function clipboard(files: File[], text = ""): Pick<DataTransfer, "files" | "getData"> {
  return { files: files as unknown as FileList, getData: (type: string) => (type === "text/plain" ? text : "") };
}

describe("素材和粘贴板落到画板上", () => {
  it("每种媒体素材各落成同名的一格:图片、视频、音频都放得下", () => {
    for (const kind of ["image", "video", "audio"] as const) {
      const item = assetItem({ id: `a-${kind}`, name: `${kind}.bin`, kind }, { x: 10.4, y: 20.6 });
      expect(item).toMatchObject({ kind, asset_id: `a-${kind}`, text: `${kind}.bin`, x: 10, y: 21 });
      //: 已经有产出的格子不挂面板,所以不补产出者。
      expect(item.form).toBeUndefined();
      expect(item.width).toBeGreaterThan(0);
    }
  });

  it("几份一起放时斜着摞开,不精确重叠", () => {
    const at = { x: 0, y: 0 };
    const [first, second] = [0, 1].map((index) => assetItem({ id: `a${index}`, name: "n", kind: "image" }, at, index));
    expect([second.x - first.x, second.y - first.y]).toEqual([24, 24]);
    expect(first.id).not.toBe(second.id);
  });

  it("粘贴板:文件优先,没有文件时一段文字落成便签;空的交给默认行为", () => {
    const shot = new File([new Uint8Array([1])], "", { type: "image/png" });
    const got = clipboardContent(clipboard([shot], "<img src=…>"));
    expect(got && "files" in got ? got.files.map((file) => file.name) : null).toEqual([expect.stringMatching(/^pasted-\d+\.png$/)]);

    expect(clipboardContent(clipboard([], "  一段想法  "))).toEqual({ text: "一段想法" });
    //: 不是媒体的文件(文档)不当素材放;有文字就落文字。
    const pdf = new File(["x"], "a.pdf", { type: "application/pdf" });
    expect(clipboardContent(clipboard([pdf], "说明"))).toEqual({ text: "说明" });
    expect(clipboardContent(clipboard([], "   "))).toBeNull();
    expect(clipboardContent(null)).toBeNull();
  });

  it("超长的文字截到便签能存下的长度", () => {
    const got = clipboardContent(clipboard([], "字".repeat(30_000)));
    expect(got && "text" in got ? got.text.length : 0).toBe(20_000);
  });
});
