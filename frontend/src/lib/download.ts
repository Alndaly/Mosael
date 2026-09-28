import { assetFileUrl, type Asset } from "@/api/client";

/** 把素材原文件保存到本地磁盘。
 *  文件端点带 `Content-Disposition: attachment` + 原始文件名:浏览器直接落
 *  下载,Electron 无 will-download 拦截时弹系统「另存为」对话框。锚点的
 *  download 属性在跨域(5173→8800)会被忽略,文件名由响应头决定 — 属性只
 *  作为同域场景的兜底。 */
export function saveAssetToDisk(asset: Pick<Asset, "id" | "name" | "original_filename">): void {
  const anchor = document.createElement("a");
  anchor.href = assetFileUrl(asset.id);
  anchor.download = asset.original_filename || asset.name;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

/** 把前端手里的一块数据落成本地文件(场景 .glb、笔记 .md、工作流 JSON 等)。走 Blob object
 *  URL,同域 download 属性生效,文件名可控。URL 晚一拍再回收:点击只是发起下载,有的浏览器
 *  要在这之后才去读 Blob,当场回收会拿到一个空文件。 */
export function saveBlobToDisk(blob: Blob, filename: string): void {
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
