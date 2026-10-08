/** @vitest-environment jsdom */

/**
 * 改密码是一张真的表单:在任一个密码框里按回车就是「更新密码」;点那颗按钮同样交。此前是一组散的输入框 + 一颗点击的按钮,
 * 回车什么也不做。没填齐(两次不一样、太短)时回车不交。
 */
import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ changePassword: vi.fn(async () => undefined) }));
vi.mock("@/app/auth", () => ({
  useAuth: () => ({
    user: { id: "user-1", username: "demo", display_name: "Demo", signature: "", avatar_key: null },
    updateProfile: vi.fn(),
    changePassword: h.changePassword,
    updateAvatar: vi.fn(),
    logout: vi.fn(),
  }),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ preferences: {}, updatePreferences: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { AccountSection } from "./AccountSection";

beforeEach(() => h.changePassword.mockClear());
afterEach(cleanup);

async function fill(user: ReturnType<typeof userEvent.setup>, current: string, next: string, confirm: string) {
  await user.type(screen.getByLabelText(/currentPassword/), current);
  await user.type(screen.getByLabelText(/^newPassword/), next);
  await user.type(screen.getByLabelText(/confirmPassword/), confirm);
}

describe("改密码", () => {
  it("确认密码那一格里敲回车就是「更新密码」", async () => {
    const user = userEvent.setup();
    render(<AccountSection />);
    await fill(user, "old1", "new-secret", "new-secret{Enter}");
    await waitFor(() => expect(h.changePassword).toHaveBeenCalledWith("old1", "new-secret"));
  });

  it("点「更新密码」同样交", async () => {
    const user = userEvent.setup();
    render(<AccountSection />);
    await fill(user, "old1", "new-secret", "new-secret");
    await user.click(screen.getByRole("button", { name: "updatePassword" }));
    await waitFor(() => expect(h.changePassword).toHaveBeenCalledTimes(1));
  });

  it("两次不一样时回车不交", async () => {
    const user = userEvent.setup();
    render(<AccountSection />);
    await fill(user, "old1", "new-secret", "new-secreX{Enter}");
    expect(h.changePassword).not.toHaveBeenCalled();
  });
});
