/**
 * 「下载页面里的视频」里不碰 Electron 的那一半:一条地址算不算视频、算哪一种(直链 / HLS / DASH)、
 * 清单有没有加密,以及把播放器上看见的和网络上看见的合成一份候选。
 *
 * **加密的不碰**:HLS 带 `#EXT-X-KEY`、DASH 带 `<ContentProtection>`、播放器挂着 EME 的 MediaKeys ——
 * 一律标成受保护,界面如实说「这段视频受保护,无法下载」,不尝试取钥匙、不尝试绕过。
 */
import type { PageInfo } from "./pageToolsCore";

/** direct = 一个完整的媒体文件(mp4/webm…);hls / dash = 分段流的清单。 */
export type MediaKind = "direct" | "hls" | "dash";

const HLS_TYPES = ["application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "audio/x-mpegurl"];
const DASH_TYPES = ["application/dash+xml"];
const DIRECT_SUFFIX = /\.(mp4|m4v|webm|mov|mkv|ogv)$/i;
/**
 * 分段流的**分段**:它们单独拿出来只是几秒钟的一截(还可能没有初始化段),不是一条视频。
 * MSE 播放器按片取 fMP4 时,响应头照样写 video/mp4,只能靠地址认。
 */
const SEGMENT_SUFFIX = /\.(m4s|ts|aac|m4a|cmfv|cmfa|vtt|webvtt)$/i;
const SEGMENT_QUERY = /(^|[?&])(range|bytes|bytestart|byteend|segment|seg|frag(ment)?)=/i;

function pathOf(url: string): string {
  try {
    return new URL(url).pathname;
  } catch {
    return "";
  }
}

/** 这个地址 + 响应类型是不是一条可以拿来下载的视频;不是返回 null。 */
export function classifyMedia(url: string, mime = ""): MediaKind | null {
  if (!/^https?:\/\//i.test(url)) return null;
  const path = pathOf(url);
  if (SEGMENT_SUFFIX.test(path)) return null;
  const type = mime.split(";")[0].trim().toLowerCase();
  if (HLS_TYPES.includes(type) || /\.m3u8$/i.test(path)) return "hls";
  if (DASH_TYPES.includes(type) || /\.mpd$/i.test(path)) return "dash";
  if (type.startsWith("video/") || DIRECT_SUFFIX.test(path)) {
    let query = "";
    try {
      query = new URL(url).search;
    } catch {
      /* 上面已判过 http(s),不会到这里 */
    }
    return SEGMENT_QUERY.test(query) ? null : "direct";
  }
  return null;
}

/**
 * 同一条视频的不同请求合成一条:`<video>` 按 Range 分段取同一个 mp4,地址上可能带着各自的
 * 字节范围参数。去掉 hash 和这些参数,剩下的才是「这条视频」。
 */
export function mediaIdentity(url: string): string {
  try {
    const parsed = new URL(url);
    parsed.hash = "";
    for (const key of [...parsed.searchParams.keys()]) {
      if (/^(range|bytes|bytestart|byteend)$/i.test(key)) parsed.searchParams.delete(key);
    }
    return parsed.href;
  } catch {
    return url;
  }
}

/**
 * HLS 清单有没有加密。
 *
 * `#EXT-X-KEY` / `#EXT-X-SESSION-KEY` 的 METHOD 不是 NONE 就是加密流 —— 不分 AES-128 还是
 * SAMPLE-AES / FairPlay / Widevine:**内容方给它上了锁,我们就不去开锁**,如实说「受保护」。
 */
export function hlsIsEncrypted(manifest: string): boolean {
  for (const line of manifest.split(/\r?\n/)) {
    const match = /^#EXT-X-(?:SESSION-)?KEY:(.*)$/i.exec(line.trim());
    if (!match) continue;
    const method = /METHOD=([^,\s]+)/i.exec(match[1]);
    if (!method || method[1].toUpperCase() !== "NONE") return true;
  }
  return false;
}

/** 主清单(多码率)里的第一条媒体清单地址:加密信息常常只写在媒体清单里。不是主清单返回 null。 */
export function hlsFirstVariant(manifest: string, base: string): string | null {
  const lines = manifest.split(/\r?\n/).map((line) => line.trim());
  for (let index = 0; index < lines.length; index += 1) {
    if (!/^#EXT-X-STREAM-INF/i.test(lines[index])) continue;
    const next = lines.slice(index + 1).find((line) => line && !line.startsWith("#"));
    if (!next) return null;
    try {
      return new URL(next, base).href;
    } catch {
      return null;
    }
  }
  return null;
}

/** DASH 清单带 `<ContentProtection>` 就是 DRM(Widevine / PlayReady / ClearKey 都这么写)。 */
export function dashIsProtected(manifest: string): boolean {
  return /<(\w+:)?ContentProtection[\s/>]/i.test(manifest);
}

/** 页面里一个 `<video>` 的样子(探测脚本交回来的)。 */
export interface PageVideoElement {
  srcs: string[];
  width: number;
  height: number;
  duration: number | null;
  /** 这个播放器挂了 EME 的 MediaKeys:正在放 DRM 内容。 */
  encrypted: boolean;
}

export interface PageVideoScan {
  videos: PageVideoElement[];
  /** og:video 之类的元信息里声明的视频地址。 */
  meta: string[];
}

/** 网络上看见的一条媒体响应(见 mediaRecorder)。 */
export interface MediaResponse {
  url: string;
  mime: string;
  bytes: number | null;
}

export type VideoProtection = "drm" | "encrypted";

export interface VideoCandidate {
  url: string;
  kind: MediaKind;
  /** 从哪儿看见的:播放器元素、网络响应、页面元信息。 */
  from: "element" | "network" | "meta";
  mime: string;
  bytes: number | null;
  width: number;
  height: number;
  duration: number | null;
  /** 受保护(DRM / 加密流)就不给下载,界面如实说。 */
  protection: VideoProtection | null;
}

export interface VideoProbe {
  page: PageInfo;
  candidates: VideoCandidate[];
  /** 页面上有播放器正在放 DRM 内容(EME)。 */
  drm: boolean;
  /** 播放器用的是 blob:(MSE 分段流)而网络里没看到能下载的清单 —— 「有视频但拿不到地址」。 */
  streamOnly: boolean;
}

/**
 * 把页面上看见的(播放器、元信息)和网络上看见的(媒体响应)合成一份候选清单。
 *
 * 播放器给的地址最可信(它正在放的就是这条),排前面;网络响应补上 MSE 播放器背后的清单。
 * 同一条视频只留一条(见 mediaIdentity)。播放器挂着 MediaKeys 时,它的每一条地址都标成 DRM。
 */
export function mergeVideoCandidates(page: PageInfo, scans: PageVideoScan[], responses: MediaResponse[]): VideoProbe {
  const byIdentity = new Map<string, VideoCandidate>();
  const typeOf = new Map(responses.map((one) => [mediaIdentity(one.url), one]));
  let drm = false;
  let blobPlayers = 0;
  const add = (candidate: VideoCandidate) => {
    const key = mediaIdentity(candidate.url);
    const existing = byIdentity.get(key);
    if (!existing) {
      byIdentity.set(key, { ...candidate, url: key });
      return;
    }
    // 同一条又从别处看见了:补上缺的尺寸 / 大小,保护标记只增不减。
    byIdentity.set(key, {
      ...existing,
      width: existing.width || candidate.width,
      height: existing.height || candidate.height,
      duration: existing.duration ?? candidate.duration,
      bytes: existing.bytes ?? candidate.bytes,
      mime: existing.mime || candidate.mime,
      protection: existing.protection ?? candidate.protection,
    });
  };
  for (const scan of scans) {
    for (const video of scan.videos) {
      if (video.encrypted) drm = true;
      for (const src of video.srcs) {
        if (src.startsWith("blob:")) {
          blobPlayers += 1;
          continue;
        }
        const seen = typeOf.get(mediaIdentity(src));
        // 播放器在放的东西就是媒体:地址看不出类型时按直链算(没有扩展名的 CDN 地址很常见)。
        const kind = classifyMedia(src, seen?.mime) ?? (/^https?:\/\//i.test(src) ? "direct" : null);
        if (!kind) continue;
        add({
          url: src, kind, from: "element", mime: seen?.mime ?? "", bytes: seen?.bytes ?? null,
          width: video.width, height: video.height, duration: video.duration,
          protection: video.encrypted ? "drm" : null,
        });
      }
    }
    for (const url of scan.meta) {
      const kind = classifyMedia(url);
      if (kind) add({ url, kind, from: "meta", mime: "", bytes: null, width: 0, height: 0, duration: null, protection: null });
    }
  }
  for (const response of responses) {
    const kind = classifyMedia(response.url, response.mime);
    if (!kind) continue;
    add({
      url: response.url, kind, from: "network", mime: response.mime, bytes: response.bytes,
      width: 0, height: 0, duration: null, protection: null,
    });
  }
  const candidates = [...byIdentity.values()];
  return { page, candidates, drm, streamOnly: blobPlayers > 0 && candidates.length === 0 };
}

// 注进页面的脚本是**只读**的:不改 DOM、不触发事件、不发请求,交回可结构化克隆的普通对象。
// 以字符串形式交给 executeJavaScript,所以脚本里不能引用外部变量。

/** 播放器与 og:video。`mediaKeys` 不为空 = 这个播放器正在放 EME(DRM)内容。 */
export const VIDEO_SCAN_SCRIPT = `(() => {
  const abs = (value) => { try { return value ? new URL(value, document.baseURI).href : ""; } catch { return ""; } };
  const videos = [...document.querySelectorAll("video")].map((video) => {
    const srcs = [video.currentSrc, video.getAttribute("src") ? video.src : "",
      ...[...video.querySelectorAll("source")].map((source) => abs(source.getAttribute("src")))]
      .map(abs).filter(Boolean);
    return {
      srcs: [...new Set(srcs)],
      width: video.videoWidth || 0,
      height: video.videoHeight || 0,
      duration: Number.isFinite(video.duration) ? video.duration : null,
      encrypted: Boolean(video.mediaKeys),
    };
  });
  const meta = [...document.querySelectorAll('meta[property="og:video"], meta[property="og:video:url"], meta[property="og:video:secure_url"], meta[name="twitter:player:stream"]')]
    .map((tag) => abs(tag.getAttribute("content"))).filter(Boolean);
  return { videos, meta: [...new Set(meta)] };
})()`;
