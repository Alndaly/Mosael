/** @vitest-environment jsdom */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { readHint } from "@/test/hint";

import { ComfyNavigationSwitch } from "./ComfyNavigationSwitch";

function bridge(outcome: string) {
  const setComfyNavigation = vi.fn().mockResolvedValue({ ok: true, outcome });
  vi.stubGlobal("mosaelBrowser", { setComfyNavigation });
  return setComfyNavigation;
}

const trigger = () => document.querySelector<HTMLButtonElement>("[data-canvas-input-trigger]")!;

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("按钮外观跟着挨着的那一排走", () => {
  it("默认 ghost(画布工具条、浏览器顶栏);工作台顶栏那颗传 outline,和「保存」「运行」同有边框", () => {
    vi.stubGlobal("mosaelDesktop", { platform: "darwin" });
    bridge("applied");
    const { rerender } = render(<ComfyNavigationSwitch connectionId="c1" />);
    expect(trigger().className, "默认是 ghost(无框)").toContain("border-transparent");
    rerender(<ComfyNavigationSwitch connectionId="c1" variant="outline" />);
    expect(trigger().className, "outline 有边框").toContain("border-field-border");
  });
});

describe("工作台的画布操控方式(样子是画布那一份,存储只对这个连接)", () => {
  it("挂上就按记着的(没记过按平台:Mac 是触控板)交给主进程;从菜单换一个就记下、再设", async () => {
    vi.stubGlobal("mosaelDesktop", { platform: "darwin" });
    const set = bridge("applied");
    render(<ComfyNavigationSwitch connectionId="c1" />);
    await waitFor(() => expect(set).toHaveBeenCalledWith({ connectionId: "c1", mode: "trackpad" }));
    expect(trigger().getAttribute("data-canvas-input-mode")).toBe("trackpad");
    fireEvent.click(trigger());
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "canvasInputMouse" }));
    await waitFor(() => expect(set).toHaveBeenLastCalledWith({ connectionId: "c1", mode: "mouse" }));
    expect(window.localStorage.getItem("mosael:comfy-navigation:c1")).toBe("mouse");
    expect(trigger().getAttribute("data-canvas-input-mode")).toBe("mouse");
    expect(window.localStorage.getItem("mosael.canvas.input-mode"), "不动全局那一份").toBeNull();
  });

  it("每个连接各记各的", async () => {
    window.localStorage.setItem("mosael:comfy-navigation:c2", "mouse");
    vi.stubGlobal("mosaelDesktop", { platform: "darwin" });
    const set = bridge("applied");
    render(<ComfyNavigationSwitch connectionId="c2" />);
    await waitFor(() => expect(set).toHaveBeenCalledWith({ connectionId: "c2", mode: "mouse" }));
  });

  it("这版前端没有这个设置:按钮禁用,说明里写为什么", async () => {
    bridge("unsupported");
    render(<ComfyNavigationSwitch connectionId="c1" />);
    await waitFor(() => expect(trigger().disabled).toBe(true));
    expect(trigger().getAttribute("aria-label")).toBe("canvasInputMode");
    expect(await readHint(trigger())).toContain("comfyNavigationUnsupported");
    fireEvent.click(trigger());
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("菜单落在原生网页视图上:开着时请视图让开,关了放回", async () => {
    bridge("applied");
    const setOverlay = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("mosaelPublish", { setOverlay });
    render(<ComfyNavigationSwitch connectionId="c1" />);
    fireEvent.click(trigger());
    await screen.findByRole("menu");
    await waitFor(() => expect(setOverlay).toHaveBeenCalledWith(true));
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await waitFor(() => expect(setOverlay).toHaveBeenLastCalledWith(false));
  });

  it("没有这座桥(网页版、旧主进程)就什么都不摆", () => {
    const { container } = render(<ComfyNavigationSwitch connectionId="c1" />);
    expect(container.innerHTML).toBe("");
  });
});
