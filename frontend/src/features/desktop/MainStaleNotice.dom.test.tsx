/** @vitest-environment jsdom */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 开发时主进程过期的提示:主进程的产物(main.cjs、几个 bundle)变了、正在跑的还是旧的,界面上给一条不打扰的提示,
 * 带「重启」;页面工具这类调主进程的报错也直接引导重启。正式打包的应用没有这条(桥上没有 devMain)。
 */
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "mainStaleFiles" ? "files: {files}" : key),
}));

type Status = { files: string[]; canRestart: boolean };
let push: (status: Status) => void;
const restart = vi.fn(async () => undefined);

function installBridge(initial: Status) {
  Object.defineProperty(window, "mosaelDesktop", {
    configurable: true,
    value: {
      devMain: {
        status: vi.fn(async () => initial),
        onStale: (callback: (status: Status) => void) => {
          push = callback;
          return () => undefined;
        },
        restart,
      },
    },
  });
}

const { MainStaleNotice } = await import("./MainStaleNotice");
const { mainStale, restartForStaleMain } = await import("./mainStale");

beforeEach(() => {
  restart.mockClear();
  mainStale.reset();
});

describe("开发时主进程过期", () => {
  it("没过期不出声;产物变了出一条提示,点「重启」交给主进程", async () => {
    installBridge({ files: [], canRestart: true });
    render(<MainStaleNotice />);
    await act(async () => undefined);
    expect(screen.queryByRole("status")).toBeNull();
    act(() => push({ files: ["publish.bundle.cjs"], canRestart: true }));
    const notice = screen.getByRole("status");
    expect(notice.textContent).toContain("mainStaleText");
    fireEvent.click(screen.getByRole("button", { name: "mainStaleRestart" }));
    expect(restart).toHaveBeenCalled();
  });

  it("挂上时已经过期(界面刷新过)也出", async () => {
    installBridge({ files: ["main.cjs"], canRestart: true });
    render(<MainStaleNotice />);
    expect(await screen.findByRole("status")).toBeTruthy();
  });

  it("没法替你重启(不是经 pnpm dev 拉起的)时只说要重启,不给按钮", async () => {
    installBridge({ files: ["main.cjs"], canRestart: false });
    render(<MainStaleNotice />);
    const notice = await screen.findByRole("status");
    expect(notice.textContent).toContain("mainStaleManual");
    expect(screen.queryByRole("button", { name: "mainStaleRestart" })).toBeNull();
  });

  it("先不重启:收起这一条;之后又有产物变了再出", async () => {
    installBridge({ files: ["main.cjs"], canRestart: true });
    render(<MainStaleNotice />);
    await screen.findByRole("status");
    fireEvent.click(screen.getByRole("button", { name: "mainStaleDismiss" }));
    expect(screen.queryByRole("status")).toBeNull();
    act(() => push({ files: ["main.cjs", "system.bundle.cjs"], canRestart: true }));
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("正式打包的应用(桥上没有 devMain)什么都不出", () => {
    Object.defineProperty(window, "mosaelDesktop", { configurable: true, value: {} });
    const { container } = render(<MainStaleNotice />);
    expect(container.textContent).toBe("");
    expect(restartForStaleMain()).toBe(false);
  });

  it("过期且能重启时,调主进程的报错可以直接引导重启", async () => {
    installBridge({ files: ["main.cjs"], canRestart: true });
    render(<MainStaleNotice />);
    await screen.findByRole("status");
    expect(restartForStaleMain()).toBe(true);
    expect(restart).toHaveBeenCalled();
  });
});
