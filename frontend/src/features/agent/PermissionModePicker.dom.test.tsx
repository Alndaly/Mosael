/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));
vi.mock("@/app/auth", () => ({
  useAuth: () => ({ user: { id: "u1" } }),
}));
vi.mock("@/features/agent/currentAgentSession", () => ({
  useSessionSettings: () => ({ settings: { permission_mode: "manual" }, update: { mutate: vi.fn() } }),
}));

import { PermissionModePicker } from "./PermissionModePicker";

describe("全部放行的二次确认", () => {
  it("从会话设置浮层里打开时压在 popper 之上", async () => {
    render(
      <PermissionModePicker
        workspaceId="w1"
        place={{ kind: "studio", id: "" }}
        session={null}
      />,
    );
    fireEvent.click(screen.getByRole("combobox", { name: "permModeLabel" }));
    fireEvent.click(await screen.findByText("permModeBypass"));

    const dialog = await screen.findByRole("dialog");
    const overlay = document.querySelector(".modal-overlay");
    //: popper 包装层是全局 z 120(styles.css);确认框必须压过它。
    expect(dialog.className).toContain("z-[130]");
    expect(overlay?.className).toContain("z-[130]");

    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
