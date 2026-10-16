/**
 * 从系统那边交过来的文件(「打开方式」/ 拖到图标上)按偏好怎么处理。
 *
 * 两条路的前半段**是同一条**:都得先入库。这不是偷懒 —— 渲染层根本没有办法预览一份不在素材库里的
 * 本地文件(证据见 openExternalFiles.ts 头部),预览这一层吃的全是素材行的地址。区别只在后半段:
 * 入库停在那儿,打开预览再多开一次灯箱。
 *
 * 这里钉住四件事:入库路径一字不改、预览路径真的开了预览、多条文件时画廊装什么、以及**偏好改了之后
 * 什么时候生效**(正在跑的那一批按开跑时的值走,下一批才用新值)。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

//: 素材地址在这里只当是个字符串标签用 —— 真正拼地址的是 api 层,这条用例测的是"拿哪一份、按什么顺序"。
vi.mock("@/api/domains/assets", () => ({
  assetPreviewUrl: (id: string) => `preview:${id}`,
  assetFileUrl: (id: string) => `file:${id}`,
}));

import type { Asset } from "@/api/domains/assets";
import type { ImagePreviewItem } from "@/components/app/imagePreviewContext";

import { openExternalFiles, type ExternalOpenDeps } from "./openExternalFiles";

/** 一份素材最小的样子(后端按内容判种类,所以种类看 `kind` 而不是后缀)。 */
const asset = (path: string, kind: string): Asset =>
  ({ id: `id${path}`, name: path.replace(/^.*\//, ""), kind } as unknown as Asset);

type MockImport = ReturnType<typeof vi.fn<(path: string) => Promise<Asset>>>;
type MockPreview = ReturnType<typeof vi.fn<(items: ImagePreviewItem[], startIndex: number) => void>>;
type MockReport = ReturnType<typeof vi.fn<(imported: number, failed: number) => void>>;

type Deps = ExternalOpenDeps & {
  importFile: MockImport;
  preview: MockPreview;
  reportImport: MockReport;
};

/** 按路径给结果:没列出的路径导入失败。 */
function deps(results: Record<string, { kind: string } | "fail">): Deps {
  const importFile = vi.fn<(path: string) => Promise<Asset>>(async (path: string) => {
    const one = results[path];
    if (!one || one === "fail") throw new Error(`could not import ${path}`);
    return asset(path, one.kind);
  });
  return {
    importFile,
    preview: vi.fn<(items: ImagePreviewItem[], startIndex: number) => void>(),
    reportImport: vi.fn<(imported: number, failed: number) => void>(),
  };
}

beforeEach(() => vi.clearAllMocks());

describe("外部打开的文件:入库", () => {
  it("导入每一条、按原顺序,报一次结果,一个预览都不开", async () => {
    const d = deps({ "/a.png": { kind: "image" }, "/b.mp4": { kind: "video" } });
    await openExternalFiles(["/a.png", "/b.mp4"], "import", d);

    expect(d.importFile.mock.calls.map((call) => call[0])).toEqual(["/a.png", "/b.mp4"]);
    expect(d.reportImport).toHaveBeenCalledTimes(1);
    expect(d.reportImport).toHaveBeenCalledWith(2, 0);
    //: 入库 = 现状。多开一个灯箱就改了维护者要保住的那个行为。
    expect(d.preview).not.toHaveBeenCalled();
  });
});

describe("外部打开的文件:打开预览", () => {
  it("先照样入库,再立刻开灯箱 —— 拿的是那条素材的**预览**地址", async () => {
    const d = deps({ "/a.png": { kind: "image" } });
    await openExternalFiles(["/a.png"], "preview", d);

    //: 「打开预览」也入库:文件在素材库里,不是只看一眼就丢。
    expect(d.importFile).toHaveBeenCalledWith("/a.png");
    expect(d.reportImport).toHaveBeenCalledWith(1, 0);
    expect(d.preview).toHaveBeenCalledTimes(1);
    const [items, start] = d.preview.mock.calls[0];
    //: 图给派生预览(HEIC 之类原图浏览器解不了),并且带上 assetId —— 灯箱顶上那颗「保存到本地」按它取原始文件。
    expect(items).toEqual([{ src: "preview:id/a.png", title: "a.png", assetId: "id/a.png" }]);
    expect(start).toBe(0);
  });

  it("视频走同一个灯箱的另一副渲染(原文件地址 + video 标记)", async () => {
    const d = deps({ "/b.mp4": { kind: "video" } });
    await openExternalFiles(["/b.mp4"], "preview", d);

    expect(d.preview.mock.calls[0][0]).toEqual([
      { src: "file:id/b.mp4", title: "b.mp4", video: true, assetId: "id/b.mp4" },
    ]);
  });

  it("多条一起:画廊按来的顺序只装能预览的;音频没有预览,只入库;失败的照旧报出来", async () => {
    const d = deps({
      "/a.png": { kind: "image" },
      "/b.mp3": { kind: "audio" },
      "/c.mp4": { kind: "video" },
      "/d.png": "fail",
    });
    await openExternalFiles(["/a.png", "/b.mp3", "/c.mp4", "/d.png"], "preview", d);

    expect(d.reportImport).toHaveBeenCalledWith(3, 1);
    expect(d.preview).toHaveBeenCalledTimes(1);
    const [items, start] = d.preview.mock.calls[0];
    //: 音频**不进画廊**:灯箱只画图和视频,塞一个音频地址进去会得到一张裂图。
    expect(items).toEqual([
      { src: "preview:id/a.png", title: "a.png", assetId: "id/a.png" },
      { src: "file:id/c.mp4", title: "c.mp4", video: true, assetId: "id/c.mp4" },
    ]);
    expect(start).toBe(0);
  });

  it("一条能预览的都没有(只有音频、或者全失败)时不开灯箱 —— 空灯箱比不开更糟", async () => {
    const only = deps({ "/a.mp3": { kind: "audio" } });
    await openExternalFiles(["/a.mp3"], "preview", only);
    expect(only.preview).not.toHaveBeenCalled();
    expect(only.reportImport).toHaveBeenCalledWith(1, 0);

    const broken = deps({ "/a.png": "fail" });
    await openExternalFiles(["/a.png"], "preview", broken);
    expect(broken.preview).not.toHaveBeenCalled();
    expect(broken.reportImport).toHaveBeenCalledWith(0, 1);
  });

  it("偏好改了:正在跑的那一批按开跑时的值走,接下来那一批才用新值", async () => {
    let land: (value: Asset) => void = () => {};
    const slow = new Promise<Asset>((resolve) => { land = resolve; });
    const d: Deps = { importFile: vi.fn(() => slow), preview: vi.fn(), reportImport: vi.fn() };

    //: 这一批是"入库"时开跑的 —— 用户随后在设置里改成了"打开预览"。
    const inFlight = openExternalFiles(["/a.png"], "import", d);
    const next = deps({ "/b.png": { kind: "image" } });
    await openExternalFiles(["/b.png"], "preview", next);

    expect(next.preview).toHaveBeenCalledTimes(1); // 下一批用新值
    land(asset("/a.png", "image"));
    await inFlight;
    //: 正在跑的那批**不**因为它后来变了而补开一个灯箱 —— 这就是"改完从下一个文件起生效"。
    expect(d.preview).not.toHaveBeenCalled();
    expect(d.reportImport).toHaveBeenCalledWith(1, 0);
  });
});
