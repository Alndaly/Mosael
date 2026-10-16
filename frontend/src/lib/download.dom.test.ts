/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from "vitest";

/**
 * 「保存到本地」落到磁盘上的是**原始文件**,不是预览。
 *
 * 图在界面里显示的是后端转好的预览(HEIC 这类原图浏览器解不了),所以保存绝不能拿界面上的
 * `src` 去下载 —— 那是转码过的 JPEG。这条钉住三件事:
 *
 * - 走 `/assets/{id}/file`(原始字节),不是 `/preview`;
 * - 文件名 `original_filename || name`(跨域时浏览器忽略 `download` 属性,真正生效的是
 *   `/file` 端点响应头里的 Content-Disposition,见后端 assets.py 的 `get_asset_file`;
 *   这里给的属性是同域场景和 Electron 的兜底);
 * - 点完把临时锚点摘掉,不在 DOM 里留一串。
 *
 * 三类媒体(图、视频、音频)在这里是同一条路:素材登记时原文件就在盘上,`/file` 原样发回来。
 *
 * **桌面壳里没有锚点**:跨域时 `download` 属性被忽略,Electron 会先**导航**到那个地址(界面上先冒出一个
 * 空白页)再落下载。有桥时一律走主进程的系统保存框(见 electron/save-file.cjs、lib/download 的那一段说明),
 * 字节从渲染层这边 fetch 出来一块块交过去 —— 这一条钉的是「有桥时不创建锚点、改调桥」。
 */

const assetClient = vi.hoisted(() => ({ openAssetFile: vi.fn() }));
vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/api/assets/${id}/file`,
  openAssetFile: assetClient.openAssetFile,
}));

import { saveAssetToDisk, saveBlobToDisk, saveJsonToDisk } from "@/lib/download";

/** 在 `click()` 的那一刻把锚点抓下来 —— 它随即就被摘掉了。 */
function clickAnchor(asset: { id: string; name: string; original_filename: string }): HTMLAnchorElement {
  const clicked: HTMLAnchorElement[] = [];
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push(this);
  });
  saveAssetToDisk(asset);
  click.mockRestore();
  expect(clicked).toHaveLength(1);
  expect(document.querySelectorAll("a")).toHaveLength(0);
  return clicked[0];
}

/** 一个最小的读者(jsdom 没有 ReadableStream):一次给一块,完了说 done。 */
function readerOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  const queue = [...chunks];
  return {
    getReader: () => ({
      read: async () => (queue.length ? { done: false, value: queue.shift() } : { done: true, value: undefined }),
      cancel: async () => undefined,
    }),
  } as unknown as ReadableStream<Uint8Array>;
}

/** 桥上的那一小块(和 lib/download 里认的是同一个契约,见 electron/preload-api.d.ts)。 */
type SaveFileBridge = NonNullable<Window["mosaelPublish"]>["saveFile"];

/** 假桥:记下每一次调用,回一个能走完的结果。 */
function fakeBridge() {
  const bridge = {
    begin: vi.fn<SaveFileBridge["begin"]>(async () => ({ status: "ready", id: "save-1" })),
    write: vi.fn<SaveFileBridge["write"]>(async () => ({ status: "writing", received: 0 })),
    end: vi.fn<SaveFileBridge["end"]>(async () => ({ status: "saved", path: "/Users/me/Downloads/thing" })),
    abort: vi.fn<SaveFileBridge["abort"]>(async () => undefined),
  };
  vi.stubGlobal("mosaelPublish", { saveFile: bridge });
  return bridge;
}

/**
 * jsdom 的 Blob 没有 `stream()`(桌面壳里是真 Chromium,有)。这里补一个最小的:一次把 Blob 自己的字节交出去 ——
 * 量的还是「交给桥的是不是那些字节」。
 */
let blobStreamStubbed = false;
function stubBlobStream(): void {
  blobStreamStubbed = true;
  Object.defineProperty(Blob.prototype, "stream", {
    configurable: true,
    writable: true,
    value: function (this: Blob) {
      const bytes = this.arrayBuffer();
      let sent = false;
      return {
        getReader: () => ({
          read: async () => (sent ? { done: true, value: undefined } : ((sent = true), { done: false, value: new Uint8Array(await bytes) })),
          cancel: async () => undefined,
        }),
      } as unknown as ReadableStream<Uint8Array>;
    },
  });
}

/** 交给桥的字节拼起来(一块块 write 的 `bytes`)。 */function written(bridge: { write: { mock: { calls: unknown[][] } } }): Uint8Array {
  const chunks = bridge.write.mock.calls.map((call) => (call[0] as { bytes: Uint8Array }).bytes);
  expect(chunks.length, "至少交了一块").toBeGreaterThan(0);
  const total = chunks.reduce((sum, one) => sum + one.byteLength, 0);
  const all = new Uint8Array(total);
  let at = 0;
  for (const one of chunks) {
    all.set(one, at);
    at += one.byteLength;
  }
  return all;
}

/**
 * 等桥那条路走完:它整条都是 `await`(没有计时器),把微任务队列让空就到位了 —— 不等时间,所以不会因机器忙而红。
 * 让不出结果来说明有别的东西把它挂住了,那正是该红的时候。
 */
async function settleBridge(): Promise<void> {
  for (let index = 0; index < 20; index += 1) await Promise.resolve();
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  assetClient.openAssetFile.mockReset();
  if (blobStreamStubbed) {
    delete (Blob.prototype as { stream?: unknown }).stream;
    blobStreamStubbed = false;
  }
});

it("图片:取原文件端点,文件名优先用 original_filename(存下来的是 HEIC,不是转好的预览)", () => {
  const anchor = clickAnchor({ id: "a1", name: "IMG_0665", original_filename: "IMG_0665.HEIC" });

  expect(anchor.getAttribute("href")).toBe("/api/assets/a1/file");
  expect(anchor.getAttribute("href")).not.toContain("preview");
  expect(anchor.download).toBe("IMG_0665.HEIC");
});

it("视频:同一个端点,original_filename 给了就用它(没有才退回 name)", () => {
  expect(clickAnchor({ id: "v1", name: "片头", original_filename: "opening.mp4" }).download).toBe("opening.mp4");
  expect(clickAnchor({ id: "v1", name: "片头", original_filename: "" }).download).toBe("片头");
});

it("音频:同一个端点、同一套文件名规则", () => {
  const anchor = clickAnchor({ id: "s1", name: "配音", original_filename: "speech.wav" });

  expect(anchor.getAttribute("href")).toBe("/api/assets/s1/file");
  expect(anchor.download).toBe("speech.wav");
});

it("有桥时:一个锚点都不建,改走系统保存框那条路 —— 原文件流一块块交给主进程,建议名是 original_filename", async () => {
  const bridge = fakeBridge();
  assetClient.openAssetFile.mockResolvedValue(readerOf([new Uint8Array([1, 2]), new Uint8Array([3])]));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click");

  saveAssetToDisk({ id: "a1", name: "IMG_0665", original_filename: "IMG_0665.HEIC" });
  await settleBridge();

  expect(click, "桌面壳里绝不再点锚点(跨域时那是导航)").not.toHaveBeenCalled();
  expect(document.querySelectorAll("a")).toHaveLength(0);
  expect(assetClient.openAssetFile).toHaveBeenCalledWith("a1");
  expect(bridge.begin).toHaveBeenCalledWith({ name: "IMG_0665.HEIC" });
  expect(bridge.end).toHaveBeenCalledWith({ id: "save-1" });
  expect(bridge.abort).not.toHaveBeenCalled();
  expect([...written(bridge)]).toEqual([1, 2, 3]);
});

it("有桥时取消:静默收场 —— 不写字、不收尾、不撤(主进程那边根本没开工),也不建锚点", async () => {
  const bridge = fakeBridge();
  bridge.begin.mockResolvedValue({ status: "cancelled" });
  const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click");

  saveAssetToDisk({ id: "a1", name: "IMG_0665", original_filename: "IMG_0665.HEIC" });
  await settleBridge();

  expect(click).not.toHaveBeenCalled();
  expect(assetClient.openAssetFile, "用户没选路径,一个字节都不去取").not.toHaveBeenCalled();
  expect(bridge.write).not.toHaveBeenCalled();
  expect(bridge.end).not.toHaveBeenCalled();
  expect(bridge.abort).not.toHaveBeenCalled();
  expect(warn, "取消不是错误").not.toHaveBeenCalled();
});

it("有桥时取字节失败(断网 / 401):撤掉那次保存,不建锚点,也不把异常抛给点按钮的人", async () => {
  const bridge = fakeBridge();
  assetClient.openAssetFile.mockRejectedValue(new Error("Not authenticated"));
  const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click");

  expect(() => saveAssetToDisk({ id: "a1", name: "图", original_filename: "" })).not.toThrow();
  await settleBridge();

  expect(click).not.toHaveBeenCalled();
  expect(bridge.abort).toHaveBeenCalledWith({ id: "save-1" });
  expect(bridge.end).not.toHaveBeenCalled();
  expect(warn).toHaveBeenCalled();
});

it("有桥时写失败:撤掉那次保存(用户原来那个文件一个字节没动)", async () => {
  const bridge = fakeBridge();
  bridge.write.mockResolvedValue({ status: "failed", error: "ENOSPC: no space left on device" });
  assetClient.openAssetFile.mockResolvedValue(readerOf([new Uint8Array([9])]));
  const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

  saveAssetToDisk({ id: "a1", name: "图", original_filename: "" });
  await settleBridge();

  expect(bridge.abort).toHaveBeenCalledWith({ id: "save-1" });
  expect(bridge.end).not.toHaveBeenCalled();
  expect(warn).toHaveBeenCalledWith("[download] could not save to disk:", "ENOSPC: no space left on device");
});

it("有桥时 Blob 也走桥:字节就是那份数据,文件名原样交上去(场景 .glb、笔记 .md、导出包)", async () => {
  const bridge = fakeBridge();
  stubBlobStream();

  saveBlobToDisk(new Blob([new Uint8Array([7, 8, 9])]), "场景.glb");
  await settleBridge();

  expect(document.querySelectorAll("a")).toHaveLength(0);
  expect(bridge.begin).toHaveBeenCalledWith({ name: "场景.glb" });
  expect([...written(bridge)]).toEqual([7, 8, 9]);
});

it("有桥时 JSON 也走桥(saveJsonToDisk 的调用方一行都不用改)", async () => {
  const bridge = fakeBridge();
  stubBlobStream();

  saveJsonToDisk("工作流.json", { nodes: [] });
  await settleBridge();

  expect(bridge.begin).toHaveBeenCalledWith({ name: "工作流.json" });
  expect(new TextDecoder().decode(written(bridge))).toBe(JSON.stringify({ nodes: [] }, null, 2));
});
