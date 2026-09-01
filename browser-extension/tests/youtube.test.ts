import { describe, expect, it } from "vitest";

import {
  listYouTubeTranscriptTracks,
  normalizeYouTubeTranscript,
  parseYouTubeTranscriptBody,
} from "../src/platforms/youtube";


describe("normalizeYouTubeTranscript", () => {
  it("turns timed-text fragments into clean, seekable cues", () => {
    const cues = normalizeYouTubeTranscript({
      events: [
        { tStartMs: 1200, dDurationMs: 2300, segs: [{ utf8: "Hello" }, { utf8: " " }, { utf8: "world" }] },
        { tStartMs: 3500, dDurationMs: 900, segs: [{ utf8: "\n" }] },
      ],
    });

    expect(cues).toEqual([{ start: 1.2, end: 3.5, text: "Hello world" }]);
  });

  it("reports an empty timed-text response instead of leaking JSON.parse errors", () => {
    expect(() => parseYouTubeTranscriptBody("  ")).toThrow("YouTube 没有返回字幕内容");
  });

  it("fills missing cue durations so playback following always has an active interval", () => {
    expect(normalizeYouTubeTranscript({
      events: [
        { tStartMs: 1000, segs: [{ utf8: "one" }] },
        { tStartMs: 3200, segs: [{ utf8: "two" }] },
      ],
    })).toEqual([
      { start: 1, end: 3.2, text: "one" },
      { start: 3.2, end: 5.2, text: "two" },
    ]);
  });

  it("prefers a human source track and exposes YouTube translation tracks", () => {
    const tracks = listYouTubeTranscriptTracks({
      captions: {
        playerCaptionsTracklistRenderer: {
          captionTracks: [
            { vssId: "asr", languageCode: "en", kind: "asr", name: { simpleText: "English (auto)" }, baseUrl: "https://captions.test/asr" },
            { vssId: "manual", languageCode: "en", name: { simpleText: "English" }, baseUrl: "https://captions.test/manual" },
          ],
          translationLanguages: [
            { languageCode: "zh-Hans", languageName: { simpleText: "中文（简体）" } },
          ],
        },
      },
    });

    expect(tracks[0]).toMatchObject({ id: "youtube:source:manual", language: "en", languageLabel: "English" });
    expect(tracks.at(-1)).toMatchObject({
      id: "youtube:translated:zh-Hans",
      language: "zh-Hans",
      languageLabel: "中文（简体）",
      kind: "translated",
    });
    expect(new URL(tracks.at(-1)!.url).searchParams.get("tlang")).toBe("zh-Hans");
  });

  it("builds translation tracks from the first usable caption URL", () => {
    const tracks = listYouTubeTranscriptTracks({
      captions: {
        playerCaptionsTracklistRenderer: {
          captionTracks: [
            { vssId: "manual", languageCode: "en", name: { simpleText: "English" }, baseUrl: "" },
            { vssId: "asr", languageCode: "en", kind: "asr", name: { simpleText: "English (auto)" }, baseUrl: "https://captions.test/asr" },
          ],
          translationLanguages: [{ languageCode: "ja", languageName: { simpleText: "日本語" } }],
        },
      },
    });

    expect(tracks.map((track) => track.id)).toEqual(["youtube:source:asr", "youtube:translated:ja"]);
    expect(new URL(tracks[1].url).searchParams.get("tlang")).toBe("ja");
  });
});
