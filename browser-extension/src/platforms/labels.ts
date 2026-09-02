import type { VideoPlatform } from "../shared/types";

const PLATFORM_LABELS: Record<VideoPlatform, string> = {
  youtube: "YouTube",
  bilibili: "Bilibili",
  pornhub: "Pornhub",
  generic: "",
};

export function videoPlatformLabel(platform: VideoPlatform, rawUrl = ""): string {
  if (platform !== "generic") return PLATFORM_LABELS[platform];
  try {
    return new URL(rawUrl).hostname.replace(/^www\./i, "") || "Web video";
  } catch {
    return "Web video";
  }
}

export function cleanVideoPageTitle(title: string): string {
  return title
    .replace(/\s*[-_]\s*(?:YouTube|哔哩哔哩(?:_bilibili)?|Pornhub(?:\.com)?).*$/i, "")
    .trim() || title;
}
