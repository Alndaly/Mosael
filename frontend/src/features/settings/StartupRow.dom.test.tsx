/** @vitest-environment jsdom */
/**
 * 「开机时启动」点了没反应。
 *
 * macOS 13 起这件事走 SMAppService:写进去之后系统会把它挂成**等用户批准**(系统设置 →
 * 通用 → 登录项),而在批准之前回读到的 `openAtLogin` 仍是 false。此前主进程只回一个
 * boolean,界面据此把开关弹回去 —— 用户看到的就是「点击无效」,而系统设置里其实已经躺着
 * 一条待批准的记录。
 *
 * 「要你去批准」和「没开成」是两件事。这条钉的就是这个区分。
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
const toasts = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("sonner", () => ({ toast: toasts }));

import { StartupRow } from "@/features/settings/BackendSection";

type State = { enabled: boolean; needsApproval: boolean } | null;

function desktop(get: State, set: State = get) {
  (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = {
    getOpenAtLogin: vi.fn(async () => get),
    setOpenAtLogin: vi.fn(async () => set),
  };
}

beforeEach(() => {
  toasts.error.mockReset();
});
afterEach(() => {
  delete (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop;
});

describe("开机时启动", () => {
  it("系统说「等你批准」时,开关是开着的,并告诉你去哪儿批准", async () => {
    desktop({ enabled: true, needsApproval: true });
    render(<StartupRow />);

    const toggle = await screen.findByRole("switch");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByText(/settingsStartupNeedsApproval/)).toBeTruthy();
  });

  it("真的开成了就正常显示开,不提批准的事", async () => {
    desktop({ enabled: true, needsApproval: false });
    render(<StartupRow />);

    const toggle = await screen.findByRole("switch");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(screen.queryByText(/settingsStartupNeedsApproval/)).toBeNull();
  });

  it("系统真的拒绝时,开关弹回去**并说一声** —— 静静地弹回去就是「点了没反应」", async () => {
    desktop({ enabled: false, needsApproval: false });
    render(<StartupRow />);

    const toggle = await screen.findByRole("switch");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    await userEvent.click(toggle);

    await waitFor(() => expect(toasts.error).toHaveBeenCalled());
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("开发模式(主进程不提供)时整行不渲染,而不是显示一个点不动的开关", async () => {
    desktop(null);
    const { container } = render(<StartupRow />);
    await waitFor(() => expect(container.querySelector("[role=switch]")).toBeNull());
  });
});
