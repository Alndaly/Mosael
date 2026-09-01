import { detectVideoPlatform } from "./platforms/detect";
import {
  PAGE_REQUEST_CHANNEL,
  PAGE_RESPONSE_CHANNEL,
  type CaptureGeometry,
  type ContentRequest,
  type ContentResponse,
  type PageRequest,
  type PageResponse,
} from "./shared/protocol";
import type { Transcript, VideoContext } from "./shared/types";

function videoElement(): HTMLVideoElement {
  const video = document.querySelector("video");
  if (!(video instanceof HTMLVideoElement)) throw new Error("页面中没有找到视频播放器");
  return video;
}

function currentContext(): VideoContext {
  const platform = detectVideoPlatform(location.href);
  const video = document.querySelector("video");
  return {
    supported: platform !== null,
    ...(platform ? { platform } : {}),
    title: document.title.replace(/\s*[-_]\s*(YouTube|哔哩哔哩).*$/i, "").trim() || document.title,
    url: location.href,
    currentTime: video instanceof HTMLVideoElement && Number.isFinite(video.currentTime) ? video.currentTime : 0,
    duration: video instanceof HTMLVideoElement && Number.isFinite(video.duration) ? video.duration : 0,
  };
}

function readTranscript(trackId?: string): Promise<Transcript> {
  const id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      window.removeEventListener("message", receive);
      reject(new Error("字幕读取超时，请刷新视频页面后重试"));
    }, 15_000);
    const receive = (event: MessageEvent<PageResponse>) => {
      if (event.source !== window || event.data?.channel !== PAGE_RESPONSE_CHANNEL || event.data.id !== id) return;
      window.clearTimeout(timeout);
      window.removeEventListener("message", receive);
      if (event.data.ok && event.data.data) resolve(event.data.data);
      else reject(new Error(event.data.error || "字幕读取失败"));
    };
    window.addEventListener("message", receive);
    const request: PageRequest = { channel: PAGE_REQUEST_CHANNEL, id, type: "READ_TRANSCRIPT", trackId };
    window.postMessage(request, "*");
  });
}

function captureGeometry(): CaptureGeometry {
  const video = videoElement();
  const rect = video.getBoundingClientRect();
  const left = Math.max(0, rect.left);
  const top = Math.max(0, rect.top);
  const right = Math.min(innerWidth, rect.right);
  const bottom = Math.min(innerHeight, rect.bottom);
  if (right <= left || bottom <= top) throw new Error("视频当前不在可见区域，无法截帧");
  return {
    left,
    top,
    width: right - left,
    height: bottom - top,
    viewportWidth: innerWidth,
    viewportHeight: innerHeight,
    currentTime: video.currentTime,
    title: currentContext().title,
  };
}

async function handle(message: ContentRequest): Promise<ContentResponse> {
  try {
    if (message.type === "GET_CONTEXT") return { ok: true, data: currentContext() };
    if (message.type === "GET_TRANSCRIPT") return { ok: true, data: await readTranscript(message.trackId) };
    if (message.type === "GET_CAPTURE_GEOMETRY") return { ok: true, data: captureGeometry() };
    const video = videoElement();
    video.currentTime = Math.max(0, Math.min(Number.isFinite(video.duration) ? video.duration : message.seconds, message.seconds));
    return { ok: true, data: { currentTime: video.currentTime } };
  } catch (cause) {
    return { ok: false, error: cause instanceof Error ? cause.message : String(cause) };
  }
}

chrome.runtime.onMessage.addListener((message: ContentRequest, _sender, sendResponse) => {
  void handle(message).then(sendResponse);
  return true;
});
