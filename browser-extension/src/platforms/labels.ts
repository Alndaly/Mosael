import type { VideoPlatform } from "../shared/types";

const PLATFORM_LABELS: Record<VideoPlatform, string> = {
  youtube: "YouTube",
  bilibili: "Bilibili",
  pornhub: "Pornhub",
};

export function videoPlatformLabel(platform: VideoPlatform): string {
  return PLATFORM_LABELS[platform];
}

export function cleanVideoPageTitle(title: string): string {
  return title
    .replace(/\s*[-_]\s*(?:YouTube|哔哩哔哩(?:_bilibili)?|Pornhub(?:\.com)?).*$/i, "")
    .trim() || title;
}
