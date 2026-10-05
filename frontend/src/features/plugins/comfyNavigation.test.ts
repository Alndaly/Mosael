/** @vitest-environment jsdom */

import { beforeEach, describe, expect, it } from "vitest";

import { comfyConnectionOf, defaultNavigation, readNavigation, writeNavigation } from "./comfyNavigation";

beforeEach(() => window.localStorage.clear());

describe("画布操控方式(渲染层)", () => {
  it("只认 ComfyUI 连接的视图分区", () => {
    expect(comfyConnectionOf("persist:pool-comfyui-c0ffee-1")).toBe("c0ffee-1");
    expect(comfyConnectionOf("persist:pool-3f2a")).toBeNull();
    expect(comfyConnectionOf("persist:mosael-account")).toBeNull();
    expect(comfyConnectionOf("persist:pool-comfyui-../x")).toBeNull();
    expect(comfyConnectionOf(null)).toBeNull();
  });

  it("缺省看平台:Mac 是触控板,别处是鼠标", () => {
    expect(defaultNavigation("darwin")).toBe("trackpad");
    expect(defaultNavigation("win32")).toBe("mouse");
    expect(defaultNavigation("linux")).toBe("mouse");
    expect(defaultNavigation("")).toBe("mouse");
  });

  it("按连接记在这台电脑上:两个连接各记各的,没记过的用缺省", () => {
    expect(readNavigation("a", "darwin")).toBe("trackpad");
    writeNavigation("a", "mouse");
    writeNavigation("b", "trackpad");
    expect(readNavigation("a", "darwin")).toBe("mouse");
    expect(readNavigation("b", "win32")).toBe("trackpad");
    expect(readNavigation("c", "win32")).toBe("mouse");
    window.localStorage.setItem("mosael:comfy-navigation:d", "standard");
    expect(readNavigation("d", "darwin"), "认不出的值当没记过").toBe("trackpad");
  });
});
