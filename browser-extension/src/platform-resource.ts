export type PlatformResourceResponse =
  | { ok: true; status: number; body: string }
  | { ok: false; error: "unsupported_url" | "network_error" | "http_error"; status?: number };

export function isAllowedPlatformResource(rawUrl: string): boolean {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return false;
  }
  if (url.protocol !== "https:") return false;

  if (url.hostname === "api.bilibili.com") {
    return url.pathname === "/x/player/v2";
  }
  if (url.hostname === "www.youtube.com" || url.hostname.endsWith(".youtube.com")) {
    return url.pathname === "/api/timedtext";
  }
  if (url.hostname === "hdslb.com" || url.hostname.endsWith(".hdslb.com")) {
    return /^\/bfs\/(?:ai_subtitle|subtitle)\//.test(url.pathname);
  }
  return false;
}

export async function fetchPlatformResource(
  url: string,
  fetcher: typeof fetch = fetch,
): Promise<PlatformResourceResponse> {
  if (!isAllowedPlatformResource(url)) return { ok: false, error: "unsupported_url" };
  try {
    const response = await fetcher(url, { credentials: "include" });
    if (!response.ok) return { ok: false, error: "http_error", status: response.status };
    return { ok: true, status: response.status, body: await response.text() };
  } catch {
    return { ok: false, error: "network_error" };
  }
}
