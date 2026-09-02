import { describe, expect, it, vi } from "vitest";

import { fetchPlatformResource, isAllowedPlatformResource } from "../src/platform-resource";

describe("platform resource proxy", () => {
  it("only permits the subtitle endpoints required by supported video sites", () => {
    expect(isAllowedPlatformResource("https://api.bilibili.com/x/player/v2?bvid=BV1&cid=2")).toBe(true);
    expect(isAllowedPlatformResource("https://aisubtitle.hdslb.com/bfs/ai_subtitle/prod/a.json")).toBe(true);
    expect(isAllowedPlatformResource("https://www.youtube.com/api/timedtext?v=1")).toBe(true);
    expect(isAllowedPlatformResource("https://api.bilibili.com/x/web-interface/nav")).toBe(false);
    expect(isAllowedPlatformResource("https://example.com/private")).toBe(false);
  });

  it("turns browser fetch rejection into a stable error code", async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(fetchPlatformResource(
      "https://aisubtitle.hdslb.com/bfs/ai_subtitle/prod/a.json",
      fetcher,
    )).resolves.toMatchObject({ ok: false, error: "network_error" });
  });
});
