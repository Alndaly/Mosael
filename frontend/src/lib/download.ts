import { assetFileUrl, openAssetFile, type Asset } from "@/api/client";

/**
 * 「保存到本地」。
 *
 * 在桌面壳里走**主进程的系统保存框**(见 electron/save-file.cjs):渲染层先 fetch 出字节(登录态本来就在它手里,
 * 不必让主进程自己带 cookie),一块块交给主进程,主进程写到**用户当场选的那个位置**。
 *
 * 为什么不接着用锚点:跨域时锚点的 `download` 属性会被忽略(界面在 5173,文件端点在 8800),Electron 于是把
 * 那个地址当一次**导航** —— 界面上先冒出一个空白页,下载才落下来。所以**桌面壳里绝不再点锚点**。
 *
 * 没有那座桥(纯浏览器、或者还没重建 preload 的旧壳)才回落到锚点 —— 那是原来那条路,这次不改它:文件端点带
 * `Content-Disposition: attachment`,浏览器照旧落下载;`download` 属性只在同域时管用,跨域时真正定文件名的是
 * 响应头。
 */

/** 桥上的那一小块(见 electron/preload-api.d.ts 的 MosaelSaveFileBridge)。 */
type SaveFileBridge = NonNullable<Window["mosaelPublish"]>["saveFile"];

/** 桌面壳里的保存桥;没有(纯浏览器 / dev)是 undefined —— 调用方据此回落锚点。 */
function saveFileBridge(): SaveFileBridge | undefined {
  if (typeof window === "undefined") return undefined;
  const bridge = window.mosaelPublish?.saveFile;
  return typeof bridge?.begin === "function" ? bridge : undefined;
}

/** 一块最多攒到多大再交给主进程。主进程那边一块的上限是 8 MiB(见 ipc-contract 的 MAX_SAVE_CHUNK);
 *  攒块是为了少跑几趟 IPC:fetch 和 Blob 的流给的都是几十 KB 的碎块,一个 1 GiB 的文件那样就是几万趟。 */
const CHUNK_BYTES = 4 * 1024 * 1024;

function reason(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** 把一条字节流写进已经开好的保存会话(攒成块,一块块交)。 */
async function writeStream(bridge: SaveFileBridge, id: string, stream: ReadableStream<Uint8Array>): Promise<void> {
  const reader = stream.getReader();
  try {
    let parts: Uint8Array[] = [];
    let held = 0;
    const flush = async () => {
      if (held === 0) return;
      const block = new Uint8Array(held);
      let at = 0;
      for (const part of parts) {
        block.set(part, at);
        at += part.byteLength;
      }
      parts = [];
      held = 0;
      const written = await bridge.write({ id, bytes: block });
      if (written.status === "failed") throw new Error(written.error);
    };
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value?.byteLength) continue;
      parts.push(value);
      held += value.byteLength;
      if (held >= CHUNK_BYTES) await flush();
    }
    await flush();
  } finally {
    // 出错时把流掐掉(还在等网络的那一半不必再拉了);已经读完的流再 cancel 是空操作。
    await reader.cancel().catch(() => undefined);
  }
}

/**
 * 走桥存一份字节。`open` 是**推迟到用户选好路径之后**才拉的那条字节流:用户在保存框里点了取消,就一个字节都不取。
 * 取消、失败都不往外抛 —— 调用方是各个界面上的按钮,该收场的是这里(失败只在控制台留一句)。
 */
async function saveViaBridge(
  bridge: SaveFileBridge,
  name: string,
  open: () => Promise<ReadableStream<Uint8Array>>,
): Promise<void> {
  let begun;
  try {
    begun = await bridge.begin({ name });
  } catch (error) {
    console.warn("[download] could not save to disk:", reason(error));
    return;
  }
  // 用户取消:静默。不是错误,不弹提示、不留临时文件(主进程那边根本没开工)。
  if (begun.status === "cancelled") return;
  if (begun.status === "failed") {
    console.warn("[download] could not save to disk:", begun.error);
    return;
  }
  const id = begun.id;
  try {
    await writeStream(bridge, id, await open());
    const ended = await bridge.end({ id });
    if (ended.status === "failed") throw new Error(ended.error);
  } catch (error) {
    // 写到一半断了:撤掉,用户原来那个文件一个字节没动(见 save-file.cjs 的 abort)。
    await bridge.abort({ id }).catch(() => undefined);
    console.warn("[download] could not save to disk:", reason(error));
  }
}

/**
 * 把素材原文件保存到本地磁盘。桌面壳里经主进程写(上面那条路);纯浏览器回落锚点。
 *
 * 锚点这条路取的是 `/file`(原始字节,不是预览);文件名优先 `original_filename`。跨域时浏览器忽略
 * `download` 属性,真正生效的是 `/file` 端点响应头里的 Content-Disposition(见后端 assets.py 的
 * `get_asset_file`),属性只算同域场景的兜底。
 */
export function saveAssetToDisk(asset: Pick<Asset, "id" | "name" | "original_filename">): void {
  const name = asset.original_filename || asset.name;
  const bridge = saveFileBridge();
  if (bridge) {
    void saveViaBridge(bridge, name, () => openAssetFile(asset.id));
    return;
  }
  const anchor = document.createElement("a");
  anchor.href = assetFileUrl(asset.id);
  anchor.download = name;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

/** 把前端手里的一块数据落成本地文件(场景 .glb、笔记 .md、工作流 JSON 等)。路由同上:有桥走桥,没桥回落锚点。
 *  没有桥时走 Blob object URL,同域 download 属性生效,文件名可控。URL 晚一拍再回收:点击只是发起下载,
 *  有的浏览器要在这之后才去读 Blob,当场回收会拿到一个空文件。 */
export function saveBlobToDisk(blob: Blob, filename: string): void {
  const bridge = saveFileBridge();
  if (bridge) {
    void saveViaBridge(bridge, filename, async () => blob.stream());
    return;
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function saveJsonToDisk(filename: string, data: unknown): void {
  saveBlobToDisk(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }), filename);
}
