// 把一份文件交给后端入库。下载有两条路:用户点的走用户会话(/api/assets/web-download),自动化里的走执行器通道
// (/api/browser/worker/actions/{id}/artifact);「截图」节点截的图也走执行器通道(见 actionCapture)。
//
// **边读边传**:下载的文件可能有两个 G,fs.openAsBlob 给的是一个指着磁盘文件的 Blob,FormData 发的时候才去读,
// 不先整个读进内存。照主进程的规矩走 net.fetch(为什么不用 Node 的全局 fetch 见 mainProcessHttp.test.ts):
// 它把 FormData 编成 multipart 流,一块一块写出去。
import fs from "node:fs";

import { net } from "electron";

import type { FinishedDownload } from "./downloads";

/** 后端说了「不收」:状态码 + 它那句(已按请求的语言翻好的)话。 */
export class UploadRefused extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "UploadRefused";
  }
}

/** 出处字段:两条路一样。 */
export function provenanceFields(file: FinishedDownload): Record<string, string> {
  return {
    filename: file.name,
    source_url: file.sourceUrl,
    page_url: file.pageUrl,
    page_title: file.pageTitle,
    captured_at: file.startedAt,
  };
}

/** 下好的一份文件(临时目录里的)。 */
export async function uploadDownload<T>(
  url: string,
  headers: Record<string, string>,
  fields: Record<string, string>,
  file: FinishedDownload,
): Promise<T> {
  return postFile<T>(url, headers, fields, await fs.openAsBlob(file.path), file.name);
}

/** multipart 发一份文件和几个表单字段;后端拒了就抛 UploadRefused(带着它那句话)。 */
export async function postFile<T>(
  url: string,
  headers: Record<string, string>,
  fields: Record<string, string>,
  body: Blob,
  filename: string,
): Promise<T> {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  form.append("file", body, filename);
  const response = await net.fetch(url, { method: "POST", headers, body: form });
  const text = await response.text();
  if (!response.ok) throw new UploadRefused(response.status, detailOf(text) || `HTTP ${response.status}`);
  return (text ? JSON.parse(text) : {}) as T;
}

/** FastAPI 的错误体:`{"detail": "人话"}`,校验失败时 detail 是一张列表。 */
function detailOf(text: string): string {
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail.slice(0, 500);
    if (Array.isArray(detail)) {
      return detail
        .map((one) => (one && typeof one === "object" && "msg" in one ? String((one as { msg: unknown }).msg) : ""))
        .filter(Boolean)
        .join("; ")
        .slice(0, 500);
    }
  } catch {
    // 不是 JSON:原样截一段
  }
  return text.slice(0, 200);
}
