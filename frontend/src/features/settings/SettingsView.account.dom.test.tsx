/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AccountSection } from "./AccountSection";

vi.mock("@/app/auth", () => ({
  useAuth: () => ({
    user: {
      id: "user-1",
      username: "demo",
      display_name: "Demo",
      signature: "",
      avatar_key: null,
    },
    updateProfile: vi.fn(),
    changePassword: vi.fn(),
    updateAvatar: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ preferences: {}, updatePreferences: vi.fn() }),
}));

describe("account settings layout", () => {
  it("uses full-width profile rows and keeps the current password on its own row", () => {
    const { container } = render(<AccountSection />);

    const username = screen.getByLabelText(/settingsUsername/).closest('[data-slot="settings-field"]');
    const displayName = screen.getByLabelText(/displayName/).closest('[data-slot="settings-field"]');
    const signature = screen.getByLabelText(/signature/).closest('[data-slot="settings-field"]');
    const profileForm = username?.parentElement;

    expect(profileForm).toHaveAttribute("data-slot", "settings-form");
    expect(profileForm).toHaveClass("w-full");
    expect(displayName?.parentElement).toBe(profileForm);
    expect(signature?.parentElement).toBe(profileForm);

    const currentPassword = screen.getByLabelText(/currentPassword/).closest('[data-slot="settings-field"]');
    const newPassword = screen.getByLabelText(/^newPassword$/).closest('[data-slot="settings-field"]');
    const confirmPassword = screen.getByLabelText(/confirmPassword/).closest('[data-slot="settings-field"]');
    const passwordForm = currentPassword?.parentElement;

    expect(passwordForm).toHaveAttribute("data-slot", "settings-form");
    expect(passwordForm).toHaveClass("w-full");
    expect(newPassword?.parentElement).toHaveAttribute("data-slot", "password-pair");
    expect(confirmPassword?.parentElement).toBe(newPassword?.parentElement);
    expect(currentPassword?.parentElement).not.toBe(newPassword?.parentElement);
    expect(container.querySelector('[data-slot="password-pair"]')).toHaveClass("grid-cols-2");
  });
});
