/**
 * 记下每个视图**收到过哪些媒体响应**:视频直链、HLS / DASH 清单。
 *
 * 「下载这个页面里的视频」的难处在于:现在的播放器大多是 MSE —— `<video>` 上挂的是一个 blob: 地址,
 * 真正的视频地址(m3u8 / mpd / mp4)只在网络请求里出现过一次。等用户点「下载」时再去看已经晚了,
 * 所以视图一亮到前台就开始记(只记媒体类的响应、每个视图只留最近的若干条)。
 *
 * **只看不改**:onResponseStarted 是观察型钩子,不拦请求、不改响应头,页面感觉不到。
 * 记的只有地址、类型和大小 —— 不记请求头,所以 cookie 不会落进这里,更不会进日志。
 *
 * 一个会话(分区)只能挂一个 onResponseStarted 监听器(Electron 的 webRequest 是「后挂的覆盖先挂的」),
 * 所以按分区挂一次、按 webContentsId 分桶。同一分区的其它视图(比如工作流借这个档案开的会话)
 * 的响应进各自的桶,互不相干。
 */
import type { Session } from "electron";

import { classifyMedia, type MediaResponse } from "./videoProbe";

/** 每个视图留多少条。一个页面看完几个视频也到不了这个数;信息流刷久了旧的自然被挤掉。 */
export const MAX_RESPONSES_PER_VIEW = 80;

export class MediaRecorder {
  private sessions = new WeakSet<Session>();
  private buckets = new Map<number, MediaResponse[]>();

  /** 给这个会话挂上记录器(幂等)。 */
  watch(session: Session): void {
    if (this.sessions.has(session)) return;
    this.sessions.add(session);
    // 只要 media(<video> 直接取的)和 xhr(MSE 播放器 / hls.js 用 fetch、XHR 取清单)两类。
    session.webRequest.onResponseStarted({ urls: ["<all_urls>"], types: ["media", "xhr"] }, (details) => {
      if (details.webContentsId === undefined || details.statusCode >= 400) return;
      const mime = header(details.responseHeaders, "content-type");
      if (!classifyMedia(details.url, mime)) return;
      const length = Number(header(details.responseHeaders, "content-length"));
      this.record(details.webContentsId, {
        url: details.url,
        mime,
        bytes: Number.isFinite(length) && length > 0 ? length : null,
      });
    });
  }

  record(webContentsId: number, response: MediaResponse): void {
    const bucket = (this.buckets.get(webContentsId) ?? []).filter((one) => one.url !== response.url);
    bucket.push(response);
    this.buckets.set(webContentsId, bucket.slice(-MAX_RESPONSES_PER_VIEW));
  }

  /** 这个视图看见过的媒体响应,旧的在前。 */
  responses(webContentsId: number): MediaResponse[] {
    return [...(this.buckets.get(webContentsId) ?? [])];
  }

  /** 视图没了:桶一起扔掉。 */
  forget(webContentsId: number): void {
    this.buckets.delete(webContentsId);
  }
}

function header(headers: Record<string, string[]> | undefined, name: string): string {
  if (!headers) return "";
  for (const [key, values] of Object.entries(headers)) {
    if (key.toLowerCase() === name) return String(values?.[0] ?? "");
  }
  return "";
}
