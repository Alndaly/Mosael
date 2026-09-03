import { EventEmitter } from "node:events";
import { createRequire } from "node:module";

import { describe, expect, it, vi } from "vitest";

const require = createRequire(import.meta.url);
const { bindFullscreenState } = require("./window-state.cjs") as {
  bindFullscreenState: (
    win: EventEmitter & {
      isDestroyed: () => boolean;
      isFullScreen: () => boolean;
      webContents: EventEmitter & { send: (channel: string, value: boolean) => void };
    },
    channel: string,
  ) => void;
};

describe("desktop fullscreen state", () => {
  it("uses event truth instead of a transitional isFullScreen snapshot", () => {
    const webContents = Object.assign(new EventEmitter(), {
      send: vi.fn(),
    });
    const win = Object.assign(new EventEmitter(), {
      isDestroyed: () => false,
      // Electron may still expose the previous value while leave-full-screen is dispatched.
      isFullScreen: () => true,
      webContents,
    });

    bindFullscreenState(win, "window:fullscreen");
    win.emit("leave-full-screen");

    expect(webContents.send).toHaveBeenLastCalledWith("window:fullscreen", false);
  });
});
