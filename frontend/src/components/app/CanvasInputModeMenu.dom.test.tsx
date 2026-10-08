/** @vitest-environment jsdom */

/**
 * 画布操控方式的那一个样子:小图标按钮(现在那一种的图标 + 小下拉箭头),菜单两项各带图标、名字、一句说明,现在那一项打勾;
 * 按钮上的说明写「画布操控方式:现在是 X」。此前画板上那颗点一下就切换的按钮看不出现在是哪种、点了会变成哪种。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => {
  const text: Record<string, string> = {
    canvasInputMode: "画布操控方式",
    canvasInputCurrent: "画布操控方式:现在是{mode}",
    canvasInputTrackpad: "触控板",
    canvasInputTrackpadDesc: "双指滑动平移、捏合缩放",
    canvasInputMouse: "鼠标",
    canvasInputMouseDesc: "滚轮缩放、拖动空白处平移",
    canvasInputMouseSceneDesc: "拖动旋转视角、滚轮缩放",
    canvasInputGlobalScope: "画板、工作流和 3D 场景都按这一个来",
  };
  return { useI18n: () => (key: string) => text[key] ?? key };
});

import { readHint } from "@/test/hint";

import { CanvasInputModeSwitch } from "./CanvasInputModeSwitch";
import { setCanvasInputMode } from "./canvasInputMode";

const trigger = () => document.querySelector<HTMLButtonElement>("[data-canvas-input-trigger]")!;

afterEach(() => {
  setCanvasInputMode("trackpad");
  localStorage.clear();
});

describe("画布操控方式", () => {
  it("按钮说清楚现在是哪种;点开的菜单两项各带说明,现在那一项打勾;选了就换", async () => {
    render(<CanvasInputModeSwitch />);
    expect(trigger().getAttribute("aria-label")).toBe("画布操控方式:现在是触控板");
    expect(trigger().getAttribute("aria-haspopup")).toBe("menu");
    expect(trigger().className, "在画布上点它不拖动、不平移、不缩放画布").toMatch(/\bnodrag\b.*\bnopan\b.*\bnowheel\b/);
    fireEvent.click(trigger());
    const menu = await screen.findByRole("menu", { name: "画布操控方式" });
    expect(menu.className).toMatch(/\bnodrag\b/);
    const trackpad = screen.getByRole("menuitemradio", { name: "触控板" });
    const mouse = screen.getByRole("menuitemradio", { name: "鼠标" });
    expect(trackpad.getAttribute("aria-checked")).toBe("true");
    expect(mouse.getAttribute("aria-checked")).toBe("false");
    expect(mouse.textContent).toContain("滚轮缩放、拖动空白处平移");
    fireEvent.click(mouse);
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(trigger().getAttribute("data-canvas-input-mode")).toBe("mouse");
    expect(trigger().getAttribute("aria-label")).toBe("画布操控方式:现在是鼠标");
    expect(localStorage.getItem("mosael.canvas.input-mode")).toBe("mouse");
  });

  it("悬停说明:第一行是现在是哪种,第二行是这个设置管到哪", async () => {
    render(<CanvasInputModeSwitch />);
    const tip = await readHint(trigger());
    expect(tip).toContain("画布操控方式:现在是触控板");
    expect(tip).toContain("画板、工作流和 3D 场景都按这一个来");
  });

  it("键盘:回车打开、方向键走、回车选、Esc 关", async () => {
    render(<CanvasInputModeSwitch />);
    trigger().focus();
    fireEvent.keyDown(trigger(), { key: "Enter" });
    fireEvent.click(trigger());
    const menu = await screen.findByRole("menu");
    const first = screen.getByRole("menuitemradio", { name: "触控板" });
    first.focus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("menuitemradio", { name: "鼠标" }));
    fireEvent.keyDown(menu, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(trigger().getAttribute("data-canvas-input-mode"), "Esc 不改").toBe("trackpad");
  });

  it("3D 场景:鼠标那一项说的是拖动旋转视角", async () => {
    render(<CanvasInputModeSwitch scene />);
    fireEvent.click(trigger());
    expect((await screen.findByRole("menuitemradio", { name: "鼠标" })).textContent).toContain("拖动旋转视角、滚轮缩放");
  });
});
