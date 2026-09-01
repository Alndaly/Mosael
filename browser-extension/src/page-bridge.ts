import { listBilibiliTranscriptTracks, normalizeBilibiliTranscript } from "./platforms/bilibili";
import { detectVideoPlatform } from "./platforms/detect";
import { listYouTubeTranscriptTracks, parseYouTubeTranscriptBody } from "./platforms/youtube";
import {
  PAGE_REQUEST_CHANNEL,
  PAGE_RESPONSE_CHANNEL,
  type PageRequest,
  type PageResponse,
} from "./shared/protocol";
import type { Transcript } from "./shared/types";

type LooseRecord = Record<string, any>;

declare global {
  interface Window {
    ytInitialPlayerResponse?: LooseRecord;
    __INITIAL_STATE__?: LooseRecord;
    __playinfo__?: LooseRecord;
  }
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
  const response = await fetch(endpoint.toString(), { credentials: "include" });
  if (!response.ok) throw new Error(`字幕读取失败（${response.status}）`);
  const cues = parseYouTubeTranscriptBody(await response.text());
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
  let tracks = window.__playinfo__?.data?.subtitle?.subtitles;
  if (!Array.isArray(tracks) || tracks.length === 0) {
    const response = await fetch(
      `https://api.bilibili.com/x/player/v2?bvid=${encodeURIComponent(bvid)}&cid=${encodeURIComponent(cid)}`,
      { credentials: "include" },
    );
    if (!response.ok) throw new Error(`字幕清单读取失败（${response.status}）`);
    const listing = await response.json();
    tracks = listing?.data?.subtitle?.subtitles;
  }
  if (!Array.isArray(tracks) || tracks.length === 0) throw new Error("当前视频没有可用字幕");
  const candidates = listBilibiliTranscriptTracks(tracks);
  const track = candidates.find((item) => item.id === trackId) || candidates[0];
  const rawUrl = track.url;
  const subtitleUrl = rawUrl.startsWith("//") ? `https:${rawUrl}` : rawUrl;
  if (!subtitleUrl) throw new Error("字幕地址为空");
  const response = await fetch(subtitleUrl, { credentials: "include" });
  if (!response.ok) throw new Error(`字幕读取失败（${response.status}）`);
  const cues = normalizeBilibiliTranscript(await response.json());
  if (cues.length === 0) throw new Error("字幕内容为空");
  return {
    trackId: track.id,
    language: track.language,
    languageLabel: track.languageLabel,
    cues,
    tracks: candidates.map(({ url: _url, ...candidate }) => candidate),
  };
}

async function readTranscript(trackId?: string): Promise<Transcript> {
  const platform = detectVideoPlatform(location.href);
  if (platform === "youtube") return readYouTubeTranscript(trackId);
  if (platform === "bilibili") return readBilibiliTranscript(trackId);
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
