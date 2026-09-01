import { describe, expect, it } from "vitest";

import { normalizeYouTubeTranscript } from "../src/platforms/youtube";


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
});
