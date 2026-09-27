/** @vitest-environment jsdom */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ModalShell } from "@/components/app/modals";

afterEach(cleanup);

/**
 * 弹窗的宽度由调用方的 `w-[…]` 定;底层只用 max-w 保证不出屏幕。此前默认宽写成了 max-w(32rem),
 * 调用方给得再宽也被压回 512px,而 jsdom 里没有布局,只能按类名守着这条。
 */
describe("弹窗宽度", () => {
  it("调用方给的宽度不会被一个更窄的 max-w 压住", () => {
    render(
      <ModalShell open onOpenChange={() => {}} title="宽弹窗" className="w-[min(1040px,calc(100vw-48px))]">
        正文
      </ModalShell>,
    );
    const classes = screen.getByRole("dialog").className.split(/\s+/);
    expect(classes).toContain("w-[min(1040px,calc(100vw-48px))]");
    //: 上限只能是「屏幕宽减边距」,不能是一个固定的宽度。
    expect(classes.filter((one) => one.startsWith("max-w-"))).toEqual(["max-w-[calc(100vw-2rem)]"]);
  });

  it("不给宽度的弹窗照旧是 32rem", () => {
    render(
      <ModalShell open onOpenChange={() => {}} title="默认">
        正文
      </ModalShell>,
    );
    expect(screen.getByRole("dialog").className).toContain("w-[min(32rem,calc(100vw-2rem))]");
  });
});
