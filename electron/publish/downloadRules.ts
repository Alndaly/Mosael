// 内嵌浏览器里的下载收不收:纯函数,不碰 Electron(下载怎么接、交给谁见 downloads.ts)。
//
// 后端入库时同一道闸再过一次(backend/app/domain/assets/web_download.py)。这边先拦,是为了不把一个
// 收不了的文件整个下完再被拒:类型不对的当场取消,大小一过上限就停。两边的数要一致 —— 上限钉在
// contracts/shared-constants.json,扩展名清单由 downloadRules.test.ts 对着后端源码比。

/** 单个下载文件的上限(2 GiB)。与后端 web_download.MAX_DOWNLOAD_BYTES 相等(共享常量契约)。 */
export const MAX_DOWNLOAD_BYTES = 2_147_483_648;

const VIDEO = [".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".flv", ".wmv", ".mpg", ".mpeg", ".3gp"];
const IMAGE = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".heic", ".heif", ".tif", ".tiff"];
const AUDIO = [".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma"];
const DOCUMENT = [
  ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".csv",
  ".md", ".markdown", ".txt", ".html", ".htm", ".epub",
];

/** 素材库认得的扩展名:视频、图片、音频、常见文档。与后端 web_download.DOWNLOAD_SUFFIXES 同一份。 */
export const DOWNLOAD_SUFFIXES: ReadonlySet<string> = new Set([...VIDEO, ...IMAGE, ...AUDIO, ...DOCUMENT]);

// 路径分隔与控制字符,以及 Windows 上不能进文件名的那几个。
// eslint-disable-next-line no-control-regex
const UNSAFE = /[\x00-\x1f\x7f/\\:*?"<>|]+/g;

/** 只取文件名本身,清掉分隔符与控制字符,太长就截(保留扩展名)。与后端 safe_filename 同一个规则。 */
export function safeDownloadName(name: string): string {
  const base = String(name || "").replace(/\\/g, "/").split("/").pop() ?? "";
  const cleaned = base.replace(UNSAFE, "_").replace(/^[ .]+|[ .]+$/g, "") || "download";
  const dot = cleaned.lastIndexOf(".");
  if (dot <= 0) return cleaned.slice(0, 120);
  return `${cleaned.slice(0, dot).slice(0, 110) || "download"}.${cleaned.slice(dot + 1).slice(0, 10)}`;
}

export function downloadSuffix(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot).toLowerCase();
}

export type DownloadRefusal =
  | { key: "downloadErr_type"; params: { name: string } }
  | { key: "downloadErr_tooLarge"; params: { maxGb: number } };

export const MAX_DOWNLOAD_GB = Math.round((MAX_DOWNLOAD_BYTES / 1024 ** 3) * 10) / 10;

/**
 * 一份刚开始的下载收不收。`totalBytes` 是服务端报的总长(不知道就是 0 —— 那就边下边数,见 tooLarge)。
 * 收就返回 null。
 */
export function refuseDownload(name: string, totalBytes: number): DownloadRefusal | null {
  if (!DOWNLOAD_SUFFIXES.has(downloadSuffix(name))) return { key: "downloadErr_type", params: { name } };
  if (totalBytes > MAX_DOWNLOAD_BYTES) return tooLarge();
  return null;
}

export function tooLarge(): DownloadRefusal {
  return { key: "downloadErr_tooLarge", params: { maxGb: MAX_DOWNLOAD_GB } };
}

/** 出处里能记的地址只有 http(s) 的:页面脚本拼出来的 blob: / data: 下载没有可记的来源地址。 */
export function httpUrlOrEmpty(url: string): string {
  return /^https?:\/\//i.test(url) && url.length <= 2000 ? url : "";
}
