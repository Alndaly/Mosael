/**
 * 用前台视图的会话去取一个资源(视频清单、页面图片)。
 */
import type { WebContents } from "electron";

const FETCH_TIMEOUT_MS = 15_000;

/**
 * 用**这个档案的会话**去取(带它的 cookie、代理),Referer 是当前页面 —— 和页面自己取这个资源时
 * 一样。很多站点的图片与清单防盗链,不带 Referer 只回 403。请求头只在这里组,不落日志。
 */
export async function fetchBytes(
  wc: WebContents,
  url: string,
  referer: string,
  limit: number,
): Promise<{ ok: true; bytes: Uint8Array } | { ok: false; reason: "failed" | "too_large" }> {
  try {
    const response = await wc.session.fetch(url, {
      headers: referer ? { Referer: referer } : {},
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    if (!response.ok || !response.body) return { ok: false, reason: "failed" };
    const declared = Number(response.headers.get("content-length"));
    if (Number.isFinite(declared) && declared > limit) return { ok: false, reason: "too_large" };
    // 边读边数:不信 content-length(可能没有、可能撒谎)。
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel().catch(() => undefined);
        return { ok: false, reason: "too_large" };
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return { ok: true, bytes };
  } catch {
    return { ok: false, reason: "failed" };
  }
}
