/** @vitest-environment jsdom */
/**
 * 登录名不跟着自动保存(体检 UM-19):此前用户名、昵称、签名一起 650ms 防抖自动存,停顿一下就把登录名改成了半截,
 * 下次登录用不上。昵称、签名照旧边打边存;登录名改成显式的「修改登录名」+ 确认。
 * 一打开账户页什么都没改,不说「资料已保存」(体检 UM-27)。
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ updateProfile: vi.fn() }));
vi.mock("@/app/auth", () => ({
  useAuth: () => ({
    user: { id: "user-1", username: "demo", display_name: "Demo", signature: "", avatar_key: null },
    updateProfile: h.updateProfile,
    changePassword: vi.fn(),
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

beforeEach(() => {
  vi.useFakeTimers();
  h.updateProfile.mockReset();
  h.updateProfile.mockImplementation(async (profile: { username: string; display_name: string; signature: string }) => ({ id: "user-1", ...profile }));
});
afterEach(() => vi.useRealTimers());

it("打开账户页时什么都没改,不说「资料已保存」", () => {
  render(<AccountSection />);
  expect(screen.queryByText("profileSaved")).toBeNull();
});

it("改登录名停顿再久也不自动存;点「修改登录名」、确认之后才存", async () => {
  render(<AccountSection />);
  fireEvent.change(screen.getByLabelText(/settingsUsername/), { target: { value: "ui" } });
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  expect(h.updateProfile).not.toHaveBeenCalled();

  fireEvent.change(screen.getByLabelText(/settingsUsername/), { target: { value: "Demo2026" } });
  fireEvent.click(screen.getByRole("button", { name: "usernameChange" }));
  const confirm = screen.getByRole("alertdialog");
  expect(confirm.textContent).toContain("usernameChangeConfirm");
  vi.useRealTimers();
  fireEvent.click(within(confirm).getByRole("button", { name: "usernameChange" }));
  await waitFor(() => expect(h.updateProfile).toHaveBeenCalledWith({ username: "demo2026", display_name: "Demo", signature: "" }));
});

it("登录名太短时不给改,说要几个字", () => {
  render(<AccountSection />);
  fireEvent.change(screen.getByLabelText(/settingsUsername/), { target: { value: "x" } });
  expect(screen.getByRole("button", { name: "usernameChange" })).toBeDisabled();
  expect(screen.getByText("teamUsernameShort")).toBeInTheDocument();
});

it("昵称照旧边打边存,存的时候带的是原来的登录名", async () => {
  render(<AccountSection />);
  fireEvent.change(screen.getByLabelText(/settingsUsername/), { target: { value: "half" } });
  fireEvent.change(screen.getByLabelText(/displayName/), { target: { value: "New Name" } });
  await act(async () => {
    vi.advanceTimersByTime(700);
  });
  expect(h.updateProfile).toHaveBeenCalledWith({ username: "demo", display_name: "New Name", signature: "" });
});
