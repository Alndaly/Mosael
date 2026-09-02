import { detectVideoPlatform, supportsVideoPage } from "./platforms/detect";
import { cleanVideoPageTitle } from "./platforms/labels";
import { selectPrimaryVideo } from "./platforms/video-element";
import { captureVideoFrame } from "./video-frame";
import {
  PAGE_REQUEST_CHANNEL,
  PAGE_RESOURCE_REQUEST_CHANNEL,
  PAGE_RESOURCE_RESPONSE_CHANNEL,
  PAGE_RESPONSE_CHANNEL,
  type CaptureGeometry,
  type CapturedVideoFrame,
  type ContentRequest,
  type ContentResponse,
  type PageRequest,
  type PageResourceRequest,
  type PageResourceResponse,
  type PageResponse,
  type PlatformResourceRequest,
} from "./shared/protocol";
import type { Transcript, VideoContext } from "./shared/types";

function videoElement(): HTMLVideoElement {
  const video = selectPrimaryVideo(document.querySelectorAll("video"));
  if (!(video instanceof HTMLVideoElement)) throw new Error("页面中没有找到视频播放器");
  return video;
}

function currentContext(): VideoContext {
  const platform = detectVideoPlatform(location.href);
  const video = selectPrimaryVideo(document.querySelectorAll("video"));
  const playable = video instanceof HTMLVideoElement;
  const supported = supportsVideoPage(platform, playable);
  return {
    supported,
    ...(supported && platform ? { platform } : {}),
    playable,
    title: cleanVideoPageTitle(document.title),
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

let restorePreparedCapture: (() => void) | null = null;

function restoreFrameCapture(): void {
  restorePreparedCapture?.();
  restorePreparedCapture = null;
}

function overlappingPlayerElements(video: HTMLVideoElement, rect: DOMRect): HTMLElement[] {
  const found = new Set<HTMLElement>();
  const columns = 8;
  const rows = 5;
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const x = rect.left + rect.width * ((column + 0.5) / columns);
      const y = rect.top + rect.height * ((row + 0.5) / rows);
      const stack = document.elementsFromPoint(x, y);
      const videoIndex = stack.indexOf(video);
      if (videoIndex < 0) continue;
      for (const element of stack.slice(0, videoIndex)) {
        if (element instanceof HTMLElement && !element.contains(video) && !video.contains(element)) found.add(element);
      }
    }
  }
  return [...found];
}

async function prepareFrameCapture(): Promise<CaptureGeometry> {
  restoreFrameCapture();
  const video = videoElement();
  const geometry = captureGeometry();
  const controls = video.controls;
  const hidden = overlappingPlayerElements(video, video.getBoundingClientRect())
    .map((element) => ({ element, visibility: element.style.visibility }));
  video.controls = false;
  hidden.forEach(({ element }) => { element.style.visibility = "hidden"; });
  const timeout = window.setTimeout(restoreFrameCapture, 3_000);
  restorePreparedCapture = () => {
    window.clearTimeout(timeout);
    video.controls = controls;
    hidden.forEach(({ element, visibility }) => { element.style.visibility = visibility; });
  };
  await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  return geometry;
}

function currentVideoFrame(): CapturedVideoFrame {
  const video = videoElement();
  return {
    dataUrl: captureVideoFrame(video),
    currentTime: video.currentTime,
    title: currentContext().title,
  };
}

async function handle(message: ContentRequest): Promise<ContentResponse> {
  try {
    if (message.type === "GET_CONTEXT") return { ok: true, data: currentContext() };
    if (message.type === "GET_TRANSCRIPT") return { ok: true, data: await readTranscript(message.trackId) };
    if (message.type === "CAPTURE_VIDEO_FRAME") return { ok: true, data: currentVideoFrame() };
    if (message.type === "PREPARE_FRAME_CAPTURE") return { ok: true, data: await prepareFrameCapture() };
    if (message.type === "RESTORE_FRAME_CAPTURE") {
      restoreFrameCapture();
      return { ok: true, data: { currentTime: videoElement().currentTime } };
    }
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

window.addEventListener("message", (event: MessageEvent<PageResourceRequest>) => {
  if (event.source !== window || event.data?.channel !== PAGE_RESOURCE_REQUEST_CHANNEL || event.data.type !== "FETCH_PLATFORM_RESOURCE") {
    return;
  }
  const request: PlatformResourceRequest = { type: "FETCH_PLATFORM_RESOURCE", url: event.data.url };
  void chrome.runtime.sendMessage(request)
    .then((result) => {
      const response: PageResourceResponse = {
        ...result,
        channel: PAGE_RESOURCE_RESPONSE_CHANNEL,
        id: event.data.id,
      };
      window.postMessage(response, "*");
    })
    .catch(() => {
      const response: PageResourceResponse = {
        ok: false,
        error: "network_error",
        channel: PAGE_RESOURCE_RESPONSE_CHANNEL,
        id: event.data.id,
      };
      window.postMessage(response, "*");
    });
});
