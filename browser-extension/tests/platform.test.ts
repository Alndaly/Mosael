import { describe, expect, it } from "vitest";

import { detectVideoPlatform } from "../src/platforms/detect";
import { cleanVideoPageTitle, videoPlatformLabel } from "../src/platforms/labels";


describe("detectVideoPlatform", () => {
  it.each([
    ["https://www.youtube.com/watch?v=abc", "youtube"],
    ["https://www.youtube.com/shorts/abc", "youtube"],
    ["https://www.bilibili.com/video/BV1xx411c7mD", "bilibili"],
    ["https://www.bilibili.com/bangumi/play/ep123", "bilibili"],
    ["https://www.pornhub.com/view_video.php?viewkey=abc123", "pornhub"],
    ["https://cn.pornhub.com/view_video.php?viewkey=abc123", "pornhub"],
    ["https://www.youtube.com/", null],
    ["https://www.pornhub.com/", null],
    ["https://www.pornhub.com/view_video.php", null],
    ["https://example.com/video", null],
  ])("classifies %s", (url, expected) => {
    expect(detectVideoPlatform(url)).toBe(expected);
  });
});

describe("videoPlatformLabel", () => {
  it.each([
    ["youtube", "YouTube"],
    ["bilibili", "Bilibili"],
    ["pornhub", "Pornhub"],
  ] as const)("labels %s", (platform, expected) => {
    expect(videoPlatformLabel(platform)).toBe(expected);
  });
});

describe("cleanVideoPageTitle", () => {
  it.each([
    ["A video - YouTube", "A video"],
    ["一段视频_哔哩哔哩_bilibili", "一段视频"],
    ["A video - Pornhub.com", "A video"],
  ])("removes the site suffix from %s", (title, expected) => {
    expect(cleanVideoPageTitle(title)).toBe(expected);
  });
});
