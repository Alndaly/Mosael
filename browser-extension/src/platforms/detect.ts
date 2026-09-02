import type { VideoPlatform } from "../shared/types";


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
  return null;
}
