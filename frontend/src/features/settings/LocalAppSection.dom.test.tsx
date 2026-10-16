/** @vitest-environment jsdom */
/**
 * 「本机应用」这一页上的「打开外部文件」怎么处理。
 *
 * 这一行**原来钉在「外观」页**(老的 AppearanceSection.dom.test.tsx),后来挪到「后端」页和
 * StartupRow 挨着 —— 而「后端」的说明只讲连着的后端与工作区标识,这两行配的却是**这台机器上的
 * 桌面壳**行为,是两件事。现在它们一起有了自己的页(features/settings/LocalAppSection),测试跟着走。
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
import { ExternalOpenRow, LocalAppSection } from "./LocalAppSection";

//: 版本那一行读的是构建期注入的 __APP_VERSION__。测试跑在 vite 的转换里,真机上有的这里也可能没有 ——
//: 兜一个,免得为了那串数字把整页挂不上。
vi.stubGlobal("__APP_VERSION__", "0.0.0-test");

const desktopShell = (present: boolean) => {
  if (present)
    (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = {
      platform: "darwin",
      //: 登录项那座桥在不在,决定了 StartupRow 摆不摆 —— 要和「桌面壳在不在」一致,否则整页挂上时
      //: 那一行会静静地不出现,看着像回归。
      getOpenAtLogin: vi.fn(async () => ({ enabled: true, needsApproval: false })),
      setOpenAtLogin: vi.fn(async () => ({ enabled: true, needsApproval: false })),
    };
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

/** 整页挂上 —— 判据是「桌面壳不在时,桌面才有的那两行不摆」,单看一行证明不了这件事。 */
const mountSection = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PreferencesProvider>
        <LocalAppSection />
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

describe("「本机应用」页上的「打开外部文件」", () => {
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

  it("整页看:桌面壳里三行都在,浏览器里只剩版本那一行", async () => {
    mountSection();
    //: 开机自启那一行要等系统回读,是异步出现的。
    expect(await screen.findByText("settingsStartup")).toBeInTheDocument();
    expect(screen.getByText("settingsExternalOpen")).toBeInTheDocument();
    expect(screen.getByText("settingsVersion")).toBeInTheDocument();

    cleanup();
    desktopShell(false);
    mountSection();
    //: 那两行说的是桌面壳行为,浏览器里没有东西会读它们;版本不是 —— 浏览器里也看得到。
    expect(screen.queryByText("settingsStartup")).toBeNull();
    expect(screen.queryByText("settingsExternalOpen")).toBeNull();
    expect(screen.getByText("settingsVersion")).toBeInTheDocument();
  });
});
