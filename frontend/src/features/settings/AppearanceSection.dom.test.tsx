/**
 * 设置里的那一行:外部打开的文件怎么办。
 *
 * 两件事必须成立 —— 它是**桌面壳才摆**的(浏览器里没有别的程序能把文件交给它,摆一行改了没人读的设置
 * 只会让人以为它有用),以及它点的确实写进了偏好(而不是画了个控件)。
 */
/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const setExternalOpen = vi.fn();
let externalOpen = "import";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({
    theme: "light",
    setTheme: () => {},
    locale: "zh-CN",
    setLocale: () => {},
    font: "default",
    setFont: () => {},
    externalOpen,
    setExternalOpen,
  }),
}));
//: 字体那一块会去取字体文件 —— 测试里不出网,只留住 INTERFACE_FONTS 那张表。
vi.mock("@/app/interfaceFonts", async (original) => ({
  ...(await original<typeof import("@/app/interfaceFonts")>()),
  loadInterfaceFont: vi.fn(() => Promise.resolve()),
}));

import { AppearanceSection } from "./AppearanceSection";

const desktopShell = (present: boolean) => {
  if (present) (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = { platform: "darwin" };
  else delete (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop;
};

beforeEach(() => {
  externalOpen = "import";
  setExternalOpen.mockReset();
  desktopShell(true);
});
afterEach(() => {
  cleanup();
  desktopShell(false);
});

describe("设置里的「打开外部文件」", () => {
  it("桌面壳里摆出这一行,两个选项,点哪个就写哪个", () => {
    render(<AppearanceSection />);
    expect(screen.getByText("settingsExternalOpen")).toBeInTheDocument();
    //: 说明文字必须写清「打开预览」也会入库 —— 渲染层预览不了库外的本地文件(见 lib/openExternalFiles)。
    expect(screen.getByText("settingsExternalOpenDesc")).toBeInTheDocument();

    //: 字体那一块也是一排 radio(它自己一个 radiogroup),所以要在这一行里找。
    const group = screen.getByRole("radiogroup", { name: "settingsExternalOpen" });
    const options = within(group).getAllByRole("radio");
    expect(options.map((one) => one.textContent)).toEqual([
      "settingsExternalOpenImport",
      "settingsExternalOpenPreview",
    ]);
    //: 默认入库(此前的行为),所以第一项是选中的。
    expect(options[0]).toHaveAttribute("aria-checked", "true");

    fireEvent.click(within(group).getByText("settingsExternalOpenPreview"));
    expect(setExternalOpen).toHaveBeenCalledWith("preview");
  });

  it("浏览器里不摆 —— 没有别的程序能把文件交给它,这一行改了也没有东西会读", () => {
    desktopShell(false);
    render(<AppearanceSection />);
    expect(screen.queryByText("settingsExternalOpen")).not.toBeInTheDocument();
    //: 别的几行照旧在(别为了藏一行把整页弄没了)。
    expect(screen.getByText("settingsTheme")).toBeInTheDocument();
  });
});
