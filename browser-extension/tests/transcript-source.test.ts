import { describe, expect, it, vi } from "vitest";

import { resolveTranscriptSource } from "../src/transcript-source";

describe("resolveTranscriptSource", () => {
  it("restores an Mosael transcript when the site still has no captions", async () => {
    const readSite = vi.fn().mockRejectedValue(new Error("当前视频没有可用字幕"));
    const readStored = vi.fn().mockResolvedValue({
      assetId: "asset-existing",
      language: "ja",
      cues: [{ start: 1, end: 2, text: "既存の字幕。" }],
    });

    const result = await resolveTranscriptSource(readSite, readStored);

    expect(result.origin).toBe("mosael");
    expect(result.transcript).toEqual({
      trackId: "mosael:asset-existing",
      language: "ja",
      languageLabel: "Mosael · ja",
      cues: [{ start: 1, end: 2, text: "既存の字幕。" }],
      tracks: [],
    });
  });

  it("keeps the site's no-caption result when Mosael has no stored transcript", async () => {
    const siteError = new Error("当前视频没有可用字幕");

    await expect(resolveTranscriptSource(
      () => Promise.reject(siteError),
      () => Promise.resolve(null),
    )).rejects.toBe(siteError);
  });
});
