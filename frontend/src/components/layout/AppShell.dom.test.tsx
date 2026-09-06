/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppShell } from "./AppShell";
import { NAV_ITEMS } from "./navLabels";

const state = vi.hoisted(() => ({ admin: false }));
vi.mock("@/api/client", async (original) => ({ ...await original<typeof import("@/api/client")>(), api: async () => ({ is_deployment_admin: state.admin }) }));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { username: "studio" }, logout: vi.fn() }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ theme: "light", locale: "zh-CN", setTheme: vi.fn(), setLocale: vi.fn() }),
}));

beforeEach(() => { state.admin = false; localStorage.clear(); });

function mount(overrides: Partial<React.ComponentProps<typeof AppShell>> = {}) {
  const navigate = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <TooltipProvider><AppShell view="home" onViewChange={navigate} workspaceName="Studio" projectName={null} {...overrides}>
      <button>Existing workspace content</button>
    </AppShell></TooltipProvider>
  </QueryClientProvider>);
  return navigate;
}

it("keeps every regular view reachable when navigation is expanded or collapsed", () => {
  const navigate = mount();
  for (const collapse of [false, true]) {
    if (collapse) fireEvent.click(screen.getByRole("button", { name: "navCollapse" }));
    for (const item of NAV_ITEMS.filter(item => item.view !== "admin")) {
      fireEvent.click(screen.getByRole("button", { name: item.labelKey }));
      expect(navigate).toHaveBeenLastCalledWith(item.view);
    }
    expect(screen.getByRole("button", { name: "Existing workspace content" })).toBeVisible();
  }
  expect(localStorage.getItem("mosael.sidebar.collapsed")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "navExpand" }));
  expect(screen.getByRole("button", { name: "navCollapse" })).toHaveAttribute("aria-expanded", "true");
});

it("does not expose deployment administration to ordinary users", async () => {
  mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "navHome" })).toBeVisible());
  expect(screen.queryByRole("button", { name: "navAdmin" })).not.toBeInTheDocument();
});

it("preserves administration for deployment admins and restores compact navigation", async () => {
  state.admin = true;
  localStorage.setItem("mosael.sidebar.collapsed", "true");
  const navigate = mount();
  fireEvent.click(await screen.findByRole("button", { name: "navAdmin" }));
  expect(navigate).toHaveBeenLastCalledWith("admin");
  expect(screen.getByRole("button", { name: "navExpand" })).toHaveAttribute("aria-expanded", "false");
});

it("keeps workspace switching and management reachable from both sidebar sizes", async () => {
  const select = vi.fn();
  mount({ workspaces: [
    { id: "a", name: "Studio", role: "owner" },
    { id: "b", name: "Second studio", role: "viewer" },
  ] as React.ComponentProps<typeof AppShell>["workspaces"], onSelectWorkspace: select });
  for (const compact of [false, true]) {
    if (compact) fireEvent.click(screen.getByRole("button", { name: "navCollapse" }));
    fireEvent.click(screen.getByRole("button", { name: "workspaceSwitch" }));
    const popup = await screen.findByRole("dialog");
    expect(within(popup).getByRole("button", { name: "rename: Studio" })).toBeEnabled();
    expect(within(popup).getByRole("button", { name: "rename: Second studio" })).toBeDisabled();
    expect(within(popup).getByRole("button", { name: "delete: Second studio" })).toBeDisabled();
    expect(within(popup).getByRole("button", { name: "workspaceNew" })).toBeEnabled();
    fireEvent.change(within(popup).getByRole("textbox", { name: "workspaceSearch" }), { target: { value: "Second" } });
    expect(within(popup).queryByRole("button", { name: "rename: Studio" })).not.toBeInTheDocument();
    fireEvent.click(within(popup).getByRole("button", { name: "Second studio" }));
    expect(select).toHaveBeenLastCalledWith("b");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  }
});
