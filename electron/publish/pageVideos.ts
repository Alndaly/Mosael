/**
 * 下载页面里的视频 —— 主进程这一半:找出页面里的视频、看清单有没有加密(判断在 videoProbe)。
 * 下载本身不在这里:交给后端「从链接导入」那个任务(后台跑、有进度、能取消),见渲染层的 pageActions。
 */
import type { WebContents } from "electron";

import { sharedViews } from "./accountViews";
import { fetchBytes } from "./pageFetch";
import { foreground, pageOf } from "./pageTarget";
import {
  VIDEO_SCAN_SCRIPT,
  dashIsProtected,
  hlsFirstVariant,
  hlsIsEncrypted,
  mergeVideoCandidates,
  type PageVideoScan,
  type VideoProbe,
} from "./videoProbe";

/** 清单最多读多大。正常的 m3u8 / mpd 几 KB 到几百 KB。 */
const MAX_MANIFEST_BYTES = 2_000_000;

function frames(wc: WebContents) {
  const root = wc.mainFrame;
  const seen = new Set<string>();
  return [root, ...root.framesInSubtree].filter((frame) => {
    const key = `${frame.processId}:${frame.routingId}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * 这个页面里有哪些视频:每个 frame 的播放器 + 网络上看见过的媒体响应,合成一份候选;
 * HLS / DASH 再把清单取来看一眼有没有加密 —— 有就标成受保护,界面不给下载。
 */
export async function probeVideos(): Promise<VideoProbe> {
  const { webContents: wc } = foreground();
  const page = pageOf(wc);
  const scans = (
    await Promise.all(
      frames(wc).map((frame) =>
        (frame.executeJavaScript(VIDEO_SCAN_SCRIPT) as Promise<PageVideoScan>).catch(() => null),
      ),
    )
  ).filter((scan): scan is PageVideoScan => Boolean(scan && Array.isArray(scan.videos)));
  const probe = mergeVideoCandidates(page, scans, sharedViews()?.media.responses(wc.id) ?? []);
  await Promise.all(
    probe.candidates
      .filter((candidate) => candidate.kind !== "direct" && candidate.protection === null)
      .slice(0, 8)
      .map(async (candidate) => {
        candidate.protection = await manifestProtection(wc, candidate.url, candidate.kind, page.url);
      }),
  );
  return probe;
}

async function manifestProtection(
  wc: WebContents,
  url: string,
  kind: "hls" | "dash" | "direct",
  referer: string,
): Promise<"drm" | "encrypted" | null> {
  const text = await fetchText(wc, url, referer);
  if (text === null) return null; // 取不到就不下结论:下载那一步自己会如实失败
  if (kind === "dash") return dashIsProtected(text) ? "drm" : null;
  if (hlsIsEncrypted(text)) return "encrypted";
  const variant = hlsFirstVariant(text, url);
  if (!variant) return null;
  const media = await fetchText(wc, variant, referer);
  return media !== null && hlsIsEncrypted(media) ? "encrypted" : null;
}

async function fetchText(wc: WebContents, url: string, referer: string): Promise<string | null> {
  const bytes = await fetchBytes(wc, url, referer, MAX_MANIFEST_BYTES);
  return bytes.ok ? new TextDecoder().decode(bytes.bytes) : null;
}
