/** @vitest-environment jsdom */

/**
 * 一块界面的错误边界:**出错只换掉自己**。
 *
 * 此前只有整页和整窗两层:嵌在画板里的助手面板出错,整页被换掉;常驻的确认中心出错,整个窗口换成「Mosael 出错了」。
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));
vi.mock("@/app/preferences", () => {
  const text: Record<string, string> = {
    sectionCrashed: "这一块出错了。",
    sectionCrashedQuiet: "有一块界面出错了,已先收起。",
    pageLoadFailed: "这一页没能加载出来。",
    retry: "重试",
    appReload: "重新加载",
    close: "关闭",
  };
  return { useI18n: () => (key: string) => text[key] ?? key };
});

import { SectionBoundary } from "./errorBoundary";

function Boom({ message }: { message: string }): React.ReactElement {
  throw new Error(message);
}

afterEach(() => toastError.mockClear());

describe("一块界面的错误边界", () => {
  it("助手面板出错,旁边的画布照常在", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <div>
        <p>画布</p>
        <SectionBoundary>
          <Boom message="Cannot read properties of undefined (reading 'timeline')" />
        </SectionBoundary>
      </div>,
    );
    expect(screen.getByText("画布")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("这一块出错了。");
    expect(screen.getByText("Cannot read properties of undefined (reading 'timeline')")).toBeTruthy();
    spy.mockRestore();
  });

  it("「重试」原地复位;给了 onClose 就能直接收起", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    let fail = true;
    const onClose = vi.fn();
    function Flaky() {
      if (fail) throw new Error("boom");
      return <p>面板</p>;
    }
    render(
      <SectionBoundary onClose={onClose}>
        <Flaky />
      </SectionBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: /关闭/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /重试/ }));
    expect(screen.getByText("面板")).toBeTruthy();
    spy.mockRestore();
  });

  it("浮在窗口上的那些(quiet):不占地方,弹一条提示带原始报错;resetKey 一变就重新挂上", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    let fail = true;
    function Overlay() {
      if (fail) throw new Error("confirmation payload is not an object");
      return <p>确认中心</p>;
    }
    const onCatch = vi.fn();
    const { rerender } = render(
      <div>
        <p>页面</p>
        <SectionBoundary mode="quiet" resetKey="home" onCatch={onCatch}>
          <Overlay />
        </SectionBoundary>
      </div>,
    );
    expect(screen.getByText("页面")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(toastError).toHaveBeenCalledWith("有一块界面出错了,已先收起。", { description: "confirmation payload is not an object" });
    expect(onCatch).toHaveBeenCalledTimes(1);
    fail = false;
    rerender(
      <div>
        <p>页面</p>
        <SectionBoundary mode="quiet" resetKey="media" onCatch={onCatch}>
          <Overlay />
        </SectionBoundary>
      </div>,
    );
    expect(screen.getByText("确认中心")).toBeTruthy();
    spy.mockRestore();
  });

  it("这一块的代码没取到:按钮是「重新加载」,点了整窗重新加载", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const reload = vi.fn();
    const original = window.location;
    Object.defineProperty(window, "location", { configurable: true, value: { ...original, reload } });
    try {
      render(
        <SectionBoundary>
          <Boom message="Failed to fetch dynamically imported module: http://x/ComfyWorkbench.js" />
        </SectionBoundary>,
      );
      expect(screen.getByText("这一页没能加载出来。")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: /重新加载/ }));
      expect(reload).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: original });
      spy.mockRestore();
    }
  });
});
