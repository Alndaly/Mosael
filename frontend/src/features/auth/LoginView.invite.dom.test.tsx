/** @vitest-environment jsdom */
/**
 * 带着一张邀请链接来到登录页(ADR 0054):说清谁邀请你进哪里、还没账号能不能凭它注册;注册时带上它,不用再手抄一个码。
 * 用不了的(用过、撤回、过期、认不出)说是哪件事,能放下这张邀请照常登录。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const login = vi.fn();
const register = vi.fn();
const h = vi.hoisted(() => ({ preview: null as Record<string, unknown> | null, previewCalls: [] as string[] }));

vi.mock("@/app/auth", () => ({
  useAuth: () => ({ hasUsers: true, openRegistration: false, login, register }),
}));
vi.mock("@/app/preferences", () => {
  const t = (key: string) =>
    ({
      loginInviteTitle: "{inviter} 邀请你加入「{workspace}」,角色:{role}",
      role_editor: "编辑者",
    })[key] ?? key;
  return { useI18n: () => t, usePreferences: () => ({ locale: "zh", setLocale: () => undefined, t }) };
});
vi.mock("@/components/app/ServerPicker", () => ({ ServerPicker: () => null }));
vi.mock("@/api/client", async (importOriginal) => {
  const { ApiError } = await importOriginal<typeof import("@/api/client")>();
  return {
    ...(await importOriginal<typeof import("@/api/client")>()),
    oauthProviders: async () => [],
    previewInviteLink: async (code: string) => {
      h.previewCalls.push(code);
      if (!h.preview) throw new ApiError("没有这个邀请链接", 404, "");
      return h.preview;
    },
  };
});

const { LoginView } = await import("./LoginView");
const { pendingInvite, setPendingInvite } = await import("@/lib/inviteLinks");

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LoginView />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  h.preview = null;
  h.previewCalls = [];
  register.mockReset();
  register.mockResolvedValue(undefined);
});
afterEach(() => cleanup());

describe("带着邀请链接来的", () => {
  it("说谁邀请你进哪里;注册时带上这张,不再摆手填邀请码的框", async () => {
    setPendingInvite("Invite-Code-1234");
    h.preview = { workspace_name: "内容组", inviter_name: "阿青", role: "editor", state: "open", allows_signup: true };
    mount();
    expect(await screen.findByText("阿青 邀请你加入「内容组」,角色:编辑者")).toBeInTheDocument();
    expect(screen.getByText("loginInviteSignupOk")).toBeInTheDocument();
    expect(h.previewCalls).toEqual(["Invite-Code-1234"]);

    fireEvent.click(screen.getByRole("button", { name: "switchToRegister" }));
    expect(screen.queryByLabelText("inviteCode")).toBeNull();
    fireEvent.change(screen.getByLabelText("username"), { target: { value: "newbie" } });
    fireEvent.change(screen.getByLabelText("displayName"), { target: { value: "新人" } });
    fireEvent.change(screen.getByLabelText("password"), { target: { value: "secret1" } });
    fireEvent.change(screen.getByLabelText("confirmPassword"), { target: { value: "secret1" } });
    fireEvent.submit(screen.getByLabelText("password").closest("form")!);
    await waitFor(() => expect(register).toHaveBeenCalledWith("newbie", "secret1", "新人", "Invite-Code-1234"));
    expect(pendingInvite()).toBe("Invite-Code-1234");
  });

  it("工作区管理员发的、还没放行的:说清只对已有账号有效", async () => {
    setPendingInvite("Invite-Code-1234");
    h.preview = { workspace_name: "内容组", inviter_name: "阿青", role: "editor", state: "open", allows_signup: false };
    mount();
    expect(await screen.findByText("loginInviteMembersOnly")).toBeInTheDocument();
  });

  it("用过的、认不出的:说是哪件事,能放下它", async () => {
    setPendingInvite("Invite-Code-1234");
    h.preview = { workspace_name: "内容组", inviter_name: "阿青", role: "editor", state: "used", allows_signup: true };
    mount();
    expect(await screen.findByText("loginInviteUsed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "loginInviteDismiss" }));
    await waitFor(() => expect(document.querySelector("[data-login-invite]")).toBeNull());
    expect(pendingInvite()).toBeNull();

    cleanup();
    setPendingInvite("Unknown-Code-9999");
    h.preview = null;
    mount();
    expect(await screen.findByText("loginInviteUnknown")).toBeInTheDocument();
  });

  it("手填的框认得出粘进来的整条链接", async () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "switchToRegister" }));
    fireEvent.change(screen.getByLabelText("username"), { target: { value: "newbie" } });
    fireEvent.change(screen.getByLabelText("displayName"), { target: { value: "新人" } });
    fireEvent.change(screen.getByLabelText("inviteCode"), { target: { value: " https://studio.example.com/#/join/Pasted-Code-5678 " } });
    fireEvent.change(screen.getByLabelText("password"), { target: { value: "secret1" } });
    fireEvent.change(screen.getByLabelText("confirmPassword"), { target: { value: "secret1" } });
    fireEvent.submit(screen.getByLabelText("password").closest("form")!);
    await waitFor(() => expect(register).toHaveBeenCalledWith("newbie", "secret1", "新人", "Pasted-Code-5678"));
  });
});
