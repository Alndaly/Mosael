// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

import { panelMediaScript } from "./panelAudio";

function media(paused: boolean, muted = true, volume = 0) {
  const element = document.createElement("video");
  Object.defineProperty(element, "paused", { configurable: true, value: paused });
  Object.defineProperty(element, "volume", { configurable: true, writable: true, value: volume });
  element.muted = muted;
  element.defaultMuted = muted;
  element.pause = vi.fn();
  element.play = vi.fn(async () => undefined);
  document.body.append(element);
  return element;
}

describe("embedded browser media audio", () => {
  it("marks only media paused by Mosael and resumes that media when audio is enabled", async () => {
    const playing = media(false);
    const alreadyPaused = media(true);

    window.eval(panelMediaScript(false));
    expect(playing.dataset.mosaelPausedByHost).toBe("1");
    expect(alreadyPaused.dataset.mosaelPausedByHost).toBeUndefined();

    window.eval(panelMediaScript(true));
    expect(playing.muted).toBe(false);
    expect(playing.volume).toBe(1);
    expect(playing.play).toHaveBeenCalledOnce();
    expect(alreadyPaused.play).not.toHaveBeenCalled();
  });
});
