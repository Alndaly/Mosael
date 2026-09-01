import { describe, expect, it } from "vitest";

import { detectVideoPlatform } from "../src/platforms/detect";


describe("detectVideoPlatform", () => {
  it.each([
    ["https://www.youtube.com/watch?v=abc", "youtube"],
    ["https://www.youtube.com/shorts/abc", "youtube"],
    ["https://www.bilibili.com/video/BV1xx411c7mD", "bilibili"],
    ["https://www.bilibili.com/bangumi/play/ep123", "bilibili"],
    ["https://www.youtube.com/", null],
    ["https://example.com/video", null],
  ])("classifies %s", (url, expected) => {
    expect(detectVideoPlatform(url)).toBe(expected);
  });
});
