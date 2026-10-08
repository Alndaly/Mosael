/** @vitest-environment jsdom */

/**
 * 「暂时无法加载 · 重试」在桌面版里要真能重试。
 *
 * 内置后端连崩几次之后主进程会认输、不再自己重拉(electron/backend-lifecycle.cjs)。此前这个「重试」只是 react-query 的
 * refetch —— 后端都没了,怎么点都还是「连不上」,只能退出重开。现在先请主进程重拉它、等它就绪,再 refetch。
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => {
  const text: Record<string, string> = { pageLoadError: "暂时无法加载", retry: "重试", errorDetails: "详情" };
  return { useI18n: () => (key: string) => text[key] ?? key, translateNow: (key: string) => text[key] ?? key };
});

import { PageLoadError } from "./EmptyState";

afterEach(() => {
  delete (window as { mosaelDesktop?: unknown }).mosaelDesktop;
});

describe("「暂时无法加载」的重试", () => {
  it("桌面版:先请主进程把后端拉回来、等它回话,再重新取数据", async () => {
    const calls: string[] = [];
    let revived!: () => void;
    const retry = vi.fn(
      () =>
        new Promise<{ status: "ready" }>((resolve) => {
          calls.push("revive");
          revived = () => resolve({ status: "ready" });
        }),
    );
    (window as { mosaelDesktop?: unknown }).mosaelDesktop = { backend: { retry } };
    const onRetry = vi.fn(() => calls.push("refetch"));
    render(<PageLoadError icon={null} error={new Error("http://127.0.0.1:8800 连不上")} onRetry={onRetry} />);

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(retry).toHaveBeenCalledOnce();
    expect(onRetry, "后端还没回来时不急着重取").not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "重试" }).getAttribute("aria-busy"), "等后端的这段时间按钮转圈").toBe("true");

    await act(async () => revived());
    expect(calls).toEqual(["revive", "refetch"]);
  });

  it("重拉没成也照常重取(界面接着说连不上),不卡在转圈上", async () => {
    (window as { mosaelDesktop?: unknown }).mosaelDesktop = { backend: { retry: vi.fn(async () => Promise.reject(new Error("exited"))) } };
    const onRetry = vi.fn();
    render(<PageLoadError icon={null} error={new Error("连不上")} onRetry={onRetry} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "重试" }));
    });
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("网页版(没有桌面桥):直接重取", async () => {
    const onRetry = vi.fn();
    render(<PageLoadError icon={null} error={new Error("连不上")} onRetry={onRetry} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "重试" }));
    });
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
