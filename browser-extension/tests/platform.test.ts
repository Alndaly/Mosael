import { describe, expect, it } from "vitest";

import { detectVideoPlatform, mergePolledVideoContext, supportsVideoPage } from "../src/platforms/detect";
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
    ["https://vimeo.com/76979871", "generic"],
    ["https://www.dailymotion.com/video/x84sh87", "generic"],
    ["https://www.tiktok.com/@creator/video/123", "generic"],
    ["https://soundcloud.com/artist/track", "generic"],
    ["https://example.com/video", "generic"],
    ["file:///tmp/video.mp4", null],
  ])("classifies %s", (url, expected) => {
    expect(detectVideoPlatform(url)).toBe(expected);
  });
});

describe("videoPlatformLabel", () => {
  it.each([
    ["youtube", "YouTube"],
    ["bilibili", "Bilibili"],
    ["pornhub", "Pornhub"],
    ["generic", "example.com"],
  ] as const)("labels %s", (platform, expected) => {
    expect(videoPlatformLabel(platform, "https://www.example.com/watch/1")).toBe(expected);
  });
});

describe("supportsVideoPage", () => {
  it("accepts known video routes before their player finishes mounting", () => {
    expect(supportsVideoPage("youtube", false)).toBe(true);
  });

  it("requires a real HTML video for an unclassified website", () => {
    expect(supportsVideoPage("generic", false)).toBe(false);
    expect(supportsVideoPage("generic", true)).toBe(true);
  });
});

describe("mergePolledVideoContext", () => {
  const base = {
    title: "Video",
    url: "https://vimeo.com/76979871",
    currentTime: 0,
    duration: 0,
    playable: false,
  };

  it("keeps a backend yt-dlp match when DOM polling cannot see a custom player", () => {
    expect(mergePolledVideoContext(
      { ...base, supported: true, platform: "generic", extractor: "vimeo" },
      { ...base, supported: false },
    )).toMatchObject({ supported: true, platform: "generic", extractor: "vimeo" });
  });

  it("does not leak a classification across navigation", () => {
    expect(mergePolledVideoContext(
      { ...base, supported: true, platform: "generic", extractor: "vimeo" },
      { ...base, url: "https://example.com/", supported: false },
    ).supported).toBe(false);
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
