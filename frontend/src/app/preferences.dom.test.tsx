/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PreferencesProvider, usePreferences } from "./preferences";
import { INTERFACE_FONTS } from "./interfaceFonts";

vi.mock("@/api/client", () => ({ configureApiLocale: vi.fn() }));
vi.mock("./interfaceFonts", async (original) => ({ ...await original<typeof import("./interfaceFonts")>(), loadInterfaceFont: vi.fn(() => Promise.resolve()) }));
afterEach(() => { cleanup(); localStorage.clear(); document.documentElement.style.removeProperty("--font-sans"); });
function Controls() {
  const { font, setFont, setTheme, setLocale, externalOpen, setExternalOpen } = usePreferences();
  return <><output>{font}</output><span data-testid="external-open">{externalOpen}</span><button onClick={() => setFont("noto-serif")}>Serif</button><button onClick={() => setTheme("dark")}>Dark</button><button onClick={() => setLocale("en-US")}>English</button><button onClick={() => setExternalOpen("preview")}>Preview files</button></>;
}
//: Provider 现在要在语言变化时作废查询缓存(后端翻译的内容得重新取),所以得有 QueryClient。
const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PreferencesProvider>
        <Controls />
      </PreferencesProvider>
    </QueryClientProvider>,
  );

it("applies a global font, keeps it across theme/locale changes, and restores it on restart", () => {
  localStorage.setItem("mosael.preferences", JSON.stringify({ theme: "light", locale: "zh-CN", voiceDock: true }));
  const view = mount();
  expect(screen.getByRole("status")).toHaveTextContent("default");
  fireEvent.click(screen.getByText("Serif"));
  fireEvent.click(screen.getByText("Dark"));
  fireEvent.click(screen.getByText("English"));
  expect(document.documentElement.style.getPropertyValue("--font-sans")).toBe(INTERFACE_FONTS.find(font => font.id === "noto-serif")!.family);
  expect(JSON.parse(localStorage.getItem("mosael.preferences")!)).toEqual({ theme: "dark", locale: "en-US", voiceDock: true, font: "noto-serif", externalOpen: "import" });
  view.unmount();
  mount();
  expect(screen.getByRole("status")).toHaveTextContent("noto-serif");
});

/**
 * 外部打开的文件怎么处理。**默认必须是「入库」** —— 那是这个偏好出现之前唯一的行为,
 * 老用户升级上来不改设置就该还是老样子。
 */
it("外部打开的文件默认入库", () => {
  mount();
  expect(screen.getByTestId("external-open")).toHaveTextContent("import");
});

it("改成打开预览之后存下来,重开还在", () => {
  const view = mount();
  fireEvent.click(screen.getByText("Preview files"));
  expect(JSON.parse(localStorage.getItem("mosael.preferences")!)).toMatchObject({ externalOpen: "preview" });
  view.unmount();

  cleanup();
  mount();
  expect(screen.getByTestId("external-open")).toHaveTextContent("preview");
});

it("存着的值是坏的(手改过、老版本写的)就回到入库,而不是拿它去分支", () => {
  localStorage.setItem("mosael.preferences", JSON.stringify({ externalOpen: "delete-everything" }));
  mount();
  expect(screen.getByTestId("external-open")).toHaveTextContent("import");
});

it("falls back safely when a saved font is unavailable", () => {
  localStorage.setItem("mosael.preferences", JSON.stringify({ font: "removed-font" }));
  mount();
  expect(screen.getByRole("status")).toHaveTextContent("default");
  expect(document.documentElement.style.getPropertyValue("--font-sans")).toContain("Inter Variable");
});

/**
 * 切语言要作废查询缓存 —— 后端也有自己要翻的文案。
 *
 * 漏了这一步不会报错,只会让页面留着上一种语言:插件那几个查询是 `staleTime: Infinity`,
 * 不手动刷新就永远不再问一次。实测切到英文再切回中文,插件详情仍写着 `Blender host`,
 * 而后端对 `Accept-Language: zh-CN` 返回的明明是「Blender 主机」。
 *
 * 这条钉的是"切语言 → 作废"这件事本身,而不是某一个 queryKey 有没有带 locale ——
 * 后者要求每个调用点都记得,正是会漏的那种写法。
 */
it("换语言时作废查询缓存,首次挂载不白跑一趟", () => {
  localStorage.setItem("mosael.preferences", JSON.stringify({ theme: "light", locale: "zh-CN", voiceDock: true }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <PreferencesProvider>
        <Controls />
      </PreferencesProvider>
    </QueryClientProvider>,
  );
  expect(invalidate).not.toHaveBeenCalled(); // 首屏缓存本来就是空的

  fireEvent.click(screen.getByText("English"));
  expect(invalidate).toHaveBeenCalledTimes(1);
});
