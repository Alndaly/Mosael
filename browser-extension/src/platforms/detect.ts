import type { VideoContext, VideoPlatform } from "../shared/types";


export function detectVideoPlatform(rawUrl: string): VideoPlatform | null {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return null;
  }
  const host = url.hostname.toLowerCase();
  if ((host === "youtube.com" || host.endsWith(".youtube.com")) && /^\/(watch|shorts\/)/.test(url.pathname + url.search)) {
    if (url.pathname === "/watch" && !url.searchParams.get("v")) return null;
    return "youtube";
  }
  if ((host === "bilibili.com" || host.endsWith(".bilibili.com")) && /^\/(video|bangumi\/play)\//.test(url.pathname)) {
    return "bilibili";
  }
  if (
    (host === "pornhub.com" || host.endsWith(".pornhub.com"))
    && url.pathname === "/view_video.php"
    && Boolean(url.searchParams.get("viewkey"))
  ) {
    return "pornhub";
  }
  // Known sites have many non-video pages. Do not mistake a homepage preview for the item the
  // user intends to import. Other HTTP(S) origins use the generic HTML-video adapter; the backend
  // independently verifies non-HTML players against yt-dlp's extractor registry.
  if (
    host === "youtube.com" || host.endsWith(".youtube.com")
    || host === "bilibili.com" || host.endsWith(".bilibili.com")
    || host === "pornhub.com" || host.endsWith(".pornhub.com")
  ) return null;
  return url.protocol === "http:" || url.protocol === "https:" ? "generic" : null;
}

export function supportsVideoPage(platform: VideoPlatform | null, hasVideo: boolean): boolean {
  return platform !== null && (platform !== "generic" || hasVideo);
}

export function mergePolledVideoContext(current: VideoContext | null, polled: VideoContext): VideoContext {
  // The content script can only classify what exists in the DOM. Keep a same-page decision made
  // by the backend yt-dlp registry (or by an HTML player seen on an earlier poll), otherwise a
  // custom player flips back to "unsupported" every 600 ms after the side panel resolves it.
  if (
    polled.supported
    || !current?.supported
    || current.platform !== "generic"
    || current.url !== polled.url
  ) return polled;
  return {
    ...polled,
    supported: true,
    platform: "generic",
    ...(current.extractor ? { extractor: current.extractor } : {}),
  };
}
