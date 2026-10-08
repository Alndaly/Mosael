/** @vitest-environment jsdom */

/**
 * 登录、注册按回车就提交。`Button` 不写 type 时默认是 `type="button"`(components/ui/button.tsx)—— 提交那颗必须写
 * `type="submit"`,漏了的话点它、按回车都不提交。这里走用户的路:在最后一格里敲回车。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const login = vi.fn(async () => undefined);
const register = vi.fn(async () => undefined);

vi.mock("@/app/auth", () => ({
  useAuth: () => ({ hasUsers: true, openRegistration: true, login, register }),
}));
vi.mock("@/app/preferences", () => {
  const t = (key: string) => key;
  return { useI18n: () => t, usePreferences: () => ({ locale: "zh", setLocale: () => undefined, t }) };
});
vi.mock("@/components/app/ServerPicker", () => ({ ServerPicker: () => null }));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  oauthProviders: async () => [],
}));

const { LoginView } = await import("./LoginView");

afterEach(() => {
  cleanup();
  login.mockClear();
  register.mockClear();
});

function show() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LoginView />
    </QueryClientProvider>,
  );
}

describe("登录页按回车提交", () => {
  it("登录:密码框里敲回车", async () => {
    const user = userEvent.setup();
    show();
    await user.type(screen.getByLabelText("username"), "kinda");
    await user.type(screen.getByLabelText("password"), "secret{Enter}");
    await waitFor(() => expect(login).toHaveBeenCalledWith("kinda", "secret"));
  });

  it("注册:确认密码那一格里敲回车;点「用户协议」这种表单里的普通按钮不提交", async () => {
    const user = userEvent.setup();
    show();
    await user.click(screen.getByRole("button", { name: "switchToRegister" }));
    await user.type(screen.getByLabelText("username"), "kinda");
    await user.type(screen.getByLabelText("displayName"), "Kinda");
    await user.type(screen.getByLabelText("password"), "secret");
    await user.click(screen.getByRole("button", { name: "legalTerms" }));
    expect(register).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    await user.type(screen.getByLabelText("confirmPassword"), "secret{Enter}");
    await waitFor(() => expect(register).toHaveBeenCalledTimes(1));
  });
});
