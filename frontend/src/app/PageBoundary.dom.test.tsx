/** @vitest-environment jsdom */

/**
 * 这一页没加载出来时那一屏 —— **要撑满页面再居中**。
 *
 * 此前是 `grid min-h-0 place-items-center`:`place-items-center` 只在格子里居中,而格子本身
 * 没有高度,于是整块缩成内容高、贴在页面最顶上 —— 一屏几乎全空,错误挤在顶边那一行。
 *
 * 顺带钉住它本来的职责:按需加载的那一块没取到时,`React.lazy` 会**往上抛**,而 Suspense
 * 不接错误。没有这层边界的话整棵树卸掉,用户拿到一个永久白屏。
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => {
  const text: Record<string, string> = {
    pageLoadFailed: "这一页没能加载出来。",
    pageCrashed: "这一页出错了。",
    retry: "重试",
    appCrashed: "Mosael 出错了。",
    appReload: "重新加载",
  };
  return { useI18n: () => (key: string) => text[key] ?? key, translateNow: (key: string) => text[key] ?? key };
});

import { AppBoundary, PageBoundary } from "./PageBoundary";

function Boom({ message }: { message: string }): React.ReactElement {
  throw new Error(message);
}

describe("页面错误边界", () => {
  it("撑满页面并把内容放正中,而不是贴在顶上", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <PageBoundary resetKey="scenes">
        <Boom message="lookAlongAxis is not defined" />
      </PageBoundary>,
    );
    const alert = screen.getByRole("alert");
    expect(alert.className).toContain("h-full");
    // 内容块靠 m-auto 落在正中 —— 只有外层撑满时它才有意义。
    expect(alert.firstElementChild?.className).toContain("m-auto");
    spy.mockRestore();
  });

  it("原始错误留着 —— 它是「这一块没取到」和「这一页自己崩了」的唯一区别", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <PageBoundary resetKey="scenes">
        <Boom message="lookAlongAxis is not defined" />
      </PageBoundary>,
    );
    expect(screen.getByText("lookAlongAxis is not defined")).toBeTruthy();
    expect(screen.getByRole("button", { name: /重试/ })).toBeTruthy();
    spy.mockRestore();
  });

  it("代码块没取到和页面自己出错,说的不是一回事", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(
      <PageBoundary resetKey="editor">
        <Boom message="Failed to fetch dynamically imported module: http://x/EditorView.js" />
      </PageBoundary>,
    );
    expect(screen.getByText("这一页没能加载出来。")).toBeTruthy();
    unmount();
    // 页面自己抛的错重试照样抛:不能说「断了一下、重试就好」。
    render(
      <PageBoundary resetKey="editor">
        <Boom message="useRecorder must be used within RecordingProvider" />
      </PageBoundary>,
    );
    expect(screen.getByText("这一页出错了。")).toBeTruthy();
    expect(screen.queryByText("这一页没能加载出来。")).toBeNull();
    spy.mockRestore();
  });

  it("换了一页就自动复位,不把人锁在这一屏", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(
      <PageBoundary resetKey="scenes">
        <Boom message="boom" />
      </PageBoundary>,
    );
    expect(screen.getByRole("alert")).toBeTruthy();
    rerender(
      <PageBoundary resetKey="media">
        <div>素材库</div>
      </PageBoundary>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("素材库")).toBeTruthy();
    spy.mockRestore();
  });
});

describe("整个窗口的错误边界", () => {
  it("外壳出错时不白屏:写明出错了、留着原始报错,「重新加载」整页", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const reload = vi.fn();
    const original = window.location;
    Object.defineProperty(window, "location", { configurable: true, value: { ...original, reload } });
    try {
      render(
        <AppBoundary>
          <Boom message="useWorkspace must be used within WorkspaceProvider" />
        </AppBoundary>,
      );
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(screen.getByText("Mosael 出错了。")).toBeTruthy();
      expect(screen.getByText("useWorkspace must be used within WorkspaceProvider")).toBeTruthy();
      screen.getByRole("button", { name: /重新加载/ }).click();
      expect(reload).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: original });
      spy.mockRestore();
    }
  });

  it("亮着的原生网页视图(内嵌浏览器、工作台)跟着收起:它的顶栏没了,不能让一块光秃秃的网页盖在报错上", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const hideView = vi.fn(async () => undefined);
    vi.stubGlobal("mosaelPublish", { hideView });
    try {
      render(<AppBoundary><p>好好的</p></AppBoundary>);
      expect(hideView, "没出错不动它").not.toHaveBeenCalled();
      render(
        <AppBoundary>
          <Boom message="usePreferences must be used inside PreferencesProvider" />
        </AppBoundary>,
      );
      expect(hideView).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
      spy.mockRestore();
    }
  });
});
