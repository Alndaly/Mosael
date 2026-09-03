import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import displayMedia from "./display-media.cjs";

describe("createDisplayMediaGrant", () => {
  it("grants Windows loopback audio when screen audio was requested", () => {
    const source = { id: "screen:1:0", name: "Screen 1" };

    expect(displayMedia.createDisplayMediaGrant(source, { audioRequested: true, platform: "win32" })).toEqual({
      video: source,
      audio: "loopback",
    });
  });

  it("declares the macOS system-audio capture permission in the packaged app", () => {
    const manifest = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../package.json"), "utf8"));

    expect(manifest.build.mac.extendInfo.NSAudioCaptureUsageDescription).toBeTruthy();
  });
});
