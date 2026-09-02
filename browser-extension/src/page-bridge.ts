import { readBilibiliTranscript as readFreshBilibiliTranscript } from "./platforms/bilibili";
import { detectVideoPlatform } from "./platforms/detect";
import { listYouTubeTranscriptTracks, parseYouTubeTranscriptBody } from "./platforms/youtube";
import {
  PAGE_REQUEST_CHANNEL,
  PAGE_RESOURCE_REQUEST_CHANNEL,
  PAGE_RESOURCE_RESPONSE_CHANNEL,
  PAGE_RESPONSE_CHANNEL,
  type PageRequest,
  type PageResourceRequest,
  type PageResourceResponse,
  type PageResponse,
} from "./shared/protocol";
import type { Transcript } from "./shared/types";

type LooseRecord = Record<string, any>;

declare global {
  interface Window {
    ytInitialPlayerResponse?: LooseRecord;
    __INITIAL_STATE__?: LooseRecord;
  }
}

function fetchPlatformText(url: string): Promise<string> {
  const id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      window.removeEventListener("message", receive);
      reject(new Error("字幕服务响应超时，请稍后重试"));
    }, 15_000);
    const receive = (event: MessageEvent<PageResourceResponse>) => {
      if (event.source !== window || event.data?.channel !== PAGE_RESOURCE_RESPONSE_CHANNEL || event.data.id !== id) return;
      window.clearTimeout(timeout);
      window.removeEventListener("message", receive);
      if (event.data.ok) resolve(event.data.body);
      else if (event.data.error === "http_error") reject(new Error(`字幕服务请求失败（${event.data.status || 0}）`));
      else reject(new Error("字幕服务暂时无法连接，请检查网络后重试"));
    };
    window.addEventListener("message", receive);
    const request: PageResourceRequest = {
      channel: PAGE_RESOURCE_REQUEST_CHANNEL,
      id,
      type: "FETCH_PLATFORM_RESOURCE",
      url,
    };
    window.postMessage(request, "*");
  });
}

async function readYouTubeTranscript(trackId?: string): Promise<Transcript> {
  // YouTube is a SPA. The global value can still describe the previous watch page after an
  // in-place navigation, while the watch element is updated for the current URL first.
  const player = (document.querySelector("ytd-watch-flexy") as any)?.playerData || window.ytInitialPlayerResponse;
  const candidates = listYouTubeTranscriptTracks(player || {});
  if (candidates.length === 0) {
    throw new Error("当前视频没有可用字幕");
  }
  const track = candidates.find((item) => item.id === trackId)
    || candidates.find((item) => item.kind === "source")
    || candidates[0];
  const endpoint = new URL(track.url);
  endpoint.searchParams.set("fmt", "json3");
  const cues = parseYouTubeTranscriptBody(await fetchPlatformText(endpoint.toString()));
  return {
    trackId: track.id,
    language: track.language,
    languageLabel: track.languageLabel,
    cues,
    tracks: candidates.map(({ url: _url, ...candidate }) => candidate),
  };
}

function bilibiliIdentity(): { bvid: string; cid: string } {
  const state = window.__INITIAL_STATE__ || {};
  const video = state.videoData || state.epInfo || {};
  const bvid = String(video.bvid || state.bvid || "");
  const cid = String(video.cid || state.cid || "");
  if (!bvid || !cid) throw new Error("无法识别当前 B 站视频");
  return { bvid, cid };
}

async function readBilibiliTranscript(trackId?: string): Promise<Transcript> {
  const { bvid, cid } = bilibiliIdentity();
  return readFreshBilibiliTranscript({ bvid, cid, trackId, fetchText: fetchPlatformText });
}

async function readTranscript(trackId?: string): Promise<Transcript> {
  const platform = detectVideoPlatform(location.href);
  if (platform === "youtube") return readYouTubeTranscript(trackId);
  if (platform === "bilibili") return readBilibiliTranscript(trackId);
  if (platform === "pornhub") throw new Error("当前视频没有可用字幕");
  throw new Error("当前页面暂不支持逐字稿");
}

window.addEventListener("message", (event: MessageEvent<PageRequest>) => {
  if (event.source !== window || event.data?.channel !== PAGE_REQUEST_CHANNEL || event.data.type !== "READ_TRANSCRIPT") {
    return;
  }
  const id = event.data.id;
  void readTranscript(event.data.trackId)
    .then((data) => {
      const response: PageResponse = { channel: PAGE_RESPONSE_CHANNEL, id, ok: true, data };
      window.postMessage(response, "*");
    })
    .catch((cause) => {
      const response: PageResponse = {
        channel: PAGE_RESPONSE_CHANNEL,
        id,
        ok: false,
        error: cause instanceof Error ? cause.message : String(cause),
      };
      window.postMessage(response, "*");
    });
});
