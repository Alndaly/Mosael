/** @vitest-environment jsdom */
/**
 * 「绑定 MosaelCloud」入口。桌面端这一期只做**能绑、能看、能解绑**:
 *
 * - 未绑定时只有一颗「绑定」按钮;
 * - 点它之后把 `user_code` 和官网地址给出来,用户去官网确认,回来说一声;
 * - 绑定后显示云端邮箱,并给「解除绑定」;
 * - 本地接口从不下发 token,所以界面上也不该出现它。
 */
import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  status: vi.fn(),
  start: vi.fn(),
  complete: vi.fn(),
  unbind: vi.fn(),
  copy: {
    cloudBindingTitle: "MosaelCloud",
    cloudBindingIntro: "Bound cloud accounts are separate from local ones.",
    cloudBindingBind: "Bind MosaelCloud",
    cloudBindingChecking: "Checking the binding…",
    cloudBindingBoundTo: "Bound to {email}",
    cloudBindingUnbind: "Unbind",
    cloudBindingCodeTitle: "Confirm this code on the signed-in website",
    cloudBindingCodeHint: "Open the page below, approve it, then come back.",
    cloudBindingOpen: "Open the Mosael account page",
    cloudBindingApproved: "I've approved it",
    cloudBindingCancel: "Cancel",
    cloudBindingStarting: "Requesting a confirmation code…",
    cloudBindingCompleting: "Waiting for MosaelCloud…",
    cloudBindingPending: "Not approved yet.",
    cloudBindingGranted: "Bound.",
    cloudBindingRemoved: "Local binding removed.",
  } as Record<string, string>,
}));

vi.mock("@/api/domains/cloud", () => ({
  getCloudBinding: h.status,
  startCloudBinding: h.start,
  completeCloudBinding: h.complete,
  unbindCloudBinding: h.unbind,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => h.copy[key] ?? key,
}));

import { CloudBindingSection } from "./CloudBindingSection";

const code = {
  status: "pending_authorization",
  device_code: "desktop-device-code",
  user_code: "ABCD-EFGH",
  verification_uri: "https://mosael.com/en/account",
  verification_uri_complete: "https://mosael.com/en/account?user_code=ABCD-EFGH",
  expires_in: 600,
  interval: 5,
};

beforeEach(() => {
  h.status.mockReset();
  h.start.mockReset();
  h.complete.mockReset();
  h.unbind.mockReset();
});
afterEach(cleanup);

function route(overrides: { bound?: boolean } = {}) {
  h.status.mockResolvedValue(
    (overrides.bound ?? false)
      ? { bound: true, email: "alice@example.com", device_id: "cloud-device-1", created_at: "2026-10-20T00:00:00" }
      : { bound: false, email: null, device_id: null, created_at: null },
  );
  h.start.mockResolvedValue(code);
  h.complete.mockResolvedValue({ status: "approved", email: "alice@example.com", device_id: "cloud-device-1" });
  h.unbind.mockResolvedValue({ removed: true });
}

describe("绑定 MosaelCloud", () => {
  it("未绑定时只摆绑定入口,点完给出确认码和官网地址", async () => {
    route();
    const user = userEvent.setup();
    render(<CloudBindingSection />);

    const bind = await screen.findByRole("button", { name: "Bind MosaelCloud" });
    expect(screen.queryByText("alice@example.com")).toBeNull();

    await user.click(bind);
    expect(await screen.findByText("ABCD-EFGH")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the Mosael account page" }).getAttribute("href")).toBe(
      "https://mosael.com/en/account?user_code=ABCD-EFGH",
    );
    await waitFor(() => expect(h.start).toHaveBeenCalledTimes(1));
  });

  it("在官网确认后回到这里,显示云端邮箱并可以解绑", async () => {
    route();
    const user = userEvent.setup();
    render(<CloudBindingSection />);

    await user.click(await screen.findByRole("button", { name: "Bind MosaelCloud" }));
    await user.click(await screen.findByRole("button", { name: "I've approved it" }));

    expect(await screen.findByText(/alice@example\.com/)).toBeTruthy();
    expect(screen.queryByText(/ABCD-EFGH/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Unbind" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Bind MosaelCloud" })).toBeTruthy());
    expect(h.complete).toHaveBeenCalledWith("desktop-device-code");
    expect(h.unbind).toHaveBeenCalledTimes(1);
  });

  it("已绑定时直接显示邮箱,不摆绑定按钮", async () => {
    route({ bound: true });
    render(<CloudBindingSection />);
    expect(await screen.findByText(/alice@example\.com/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Bind MosaelCloud" })).toBeNull();
  });
});
