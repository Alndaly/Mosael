/** @vitest-environment jsdom */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ComfyNavigationSwitch } from "./ComfyNavigationSwitch";

function bridge(outcome: string) {
  const setComfyNavigation = vi.fn().mockResolvedValue({ ok: true, outcome });
  vi.stubGlobal("mosaelBrowser", { setComfyNavigation });
  return setComfyNavigation;
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("画布操控方式的开关", () => {
  it("挂上就按记着的(没记过按平台:Mac 是触控板)交给主进程;换一个就记下、再设", async () => {
    vi.stubGlobal("mosaelDesktop", { platform: "darwin" });
    const set = bridge("applied");
    render(<ComfyNavigationSwitch connectionId="c1" />);
    await waitFor(() => expect(set).toHaveBeenCalledWith({ connectionId: "c1", mode: "trackpad" }));
    expect(screen.getByRole("radio", { name: "comfyNavigationTrackpad" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("radio", { name: "comfyNavigationMouse" }));
    await waitFor(() => expect(set).toHaveBeenLastCalledWith({ connectionId: "c1", mode: "mouse" }));
    expect(window.localStorage.getItem("mosael:comfy-navigation:c1")).toBe("mouse");
    expect(screen.getByRole("radio", { name: "comfyNavigationMouse" }).getAttribute("aria-checked")).toBe("true");
  });

  it("每个连接各记各的", async () => {
    window.localStorage.setItem("mosael:comfy-navigation:c2", "mouse");
    vi.stubGlobal("mosaelDesktop", { platform: "darwin" });
    const set = bridge("applied");
    render(<ComfyNavigationSwitch connectionId="c2" />);
    await waitFor(() => expect(set).toHaveBeenCalledWith({ connectionId: "c2", mode: "mouse" }));
  });

  it("这版前端没有这个设置:开关藏起来,留一个说明为什么的图标", async () => {
    bridge("unsupported");
    render(<ComfyNavigationSwitch connectionId="c1" />);
    expect(await screen.findByRole("note", { name: "comfyNavigationUnsupported" })).toBeTruthy();
    expect(screen.queryByRole("radiogroup")).toBeNull();
  });

  it("没有这座桥(网页版、旧主进程)就什么都不摆", () => {
    const { container } = render(<ComfyNavigationSwitch connectionId="c1" />);
    expect(container.innerHTML).toBe("");
  });
});
