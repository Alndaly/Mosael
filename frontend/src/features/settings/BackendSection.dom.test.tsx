/** @vitest-environment jsdom */
/**
 * 「后端」这一页上的「打开外部文件」怎么处理。
 *
 * 这一行**原来钉在「外观」页**(老的 AppearanceSection.dom.test.tsx),而主题 / 语言 / 字体是"看着是什么样",
 * 「别的程序交来的文件怎么办」是"这台机器上的桌面壳怎么反应" —— 两件事。现在它和 StartupRow 挨着:
 * 两行配的都是本机桌面行为,判据也一样(`window.mosaelDesktop` 不在就不摆)。测试跟着这一行走。
 *
 * 三件事必须成立 —— 它是**桌面壳才摆**的(浏览器里没有别的程序能把文件交给它,摆一行改了没人读的设置
 * 只会让人以为它有用)、**默认是入库**(这个偏好出现之前唯一的行为,老用户升级上来不改设置还是老样子),
 * 以及它点的确实**落盘**了(不是画了个控件)。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

//: 字体那一块会去取字体文件 —— 测试里不出网,只留住 INTERFACE_FONTS 那张表。
vi.mock("@/app/interfaceFonts", async (original) => ({
  ...(await original<typeof import("@/app/interfaceFonts")>()),
  loadInterfaceFont: vi.fn(() => Promise.resolve()),
}));
//: Provider 与 usePreferences 都**用真的**(落盘那件事就住在里面);只把 t 换成键名:断言好读,
//: 也不必先把文案表取出来。
vi.mock("@/app/preferences", async (original) => ({
  ...(await original<typeof import("@/app/preferences")>()),
  useI18n: () => (key: string) => key,
}));

import { PreferencesProvider } from "@/app/preferences";
import { ExternalOpenRow } from "./BackendSection";

const desktopShell = (present: boolean) => {
  if (present) (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = { platform: "darwin" };
  else delete (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop;
};

/** 盘上存着的那份偏好 —— 这条偏好的"生效"就是它,所以断言写在这里而不是断言某个函数被调过。 */
const saved = () => JSON.parse(localStorage.getItem("mosael.preferences") ?? "{}") as Record<string, unknown>;

//: Provider 在语言变化时作废查询缓存,所以得有 QueryClient。
const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PreferencesProvider>
        <ExternalOpenRow />
      </PreferencesProvider>
    </QueryClientProvider>,
  );

const group = () => screen.getByRole("radiogroup", { name: "settingsExternalOpen" });

beforeEach(() => {
  localStorage.clear();
  desktopShell(true);
});
afterEach(() => {
  cleanup();
  desktopShell(false);
});

describe("「后端」页上的「打开外部文件」", () => {
  it("桌面壳里摆出这一行,两个选项,默认入库", () => {
    mount();
    expect(screen.getByText("settingsExternalOpen")).toBeInTheDocument();
    //: 说明文字必须写清「打开预览」也会入库 —— 渲染层预览不了库外的本地文件(见 lib/openExternalFiles)。
    expect(screen.getByText("settingsExternalOpenDesc")).toBeInTheDocument();

    const options = within(group()).getAllByRole("radio");
    expect(options.map((one) => one.textContent)).toEqual([
      "settingsExternalOpenImport",
      "settingsExternalOpenPreview",
    ]);
    //: 默认入库(此前的行为),所以第一项是选中的 —— 没选过的人盘上存的也是它。
    expect(options[0]).toHaveAttribute("aria-checked", "true");
    expect(saved()).toMatchObject({ externalOpen: "import" });
  });

  it("点「打开预览」当场落盘,重开还在", () => {
    const view = mount();
    fireEvent.click(within(group()).getByText("settingsExternalOpenPreview"));
    expect(saved()).toMatchObject({ externalOpen: "preview" });

    view.unmount();
    cleanup();
    mount();
    const options = within(group()).getAllByRole("radio");
    expect(options[1]).toHaveAttribute("aria-checked", "true");
    expect(options[0]).toHaveAttribute("aria-checked", "false");
  });

  it("浏览器里不摆 —— 没有别的程序能把文件交给它,这一行改了也没有东西会读", () => {
    desktopShell(false);
    const { container } = mount();
    expect(container).toBeEmptyDOMElement();
  });
});
