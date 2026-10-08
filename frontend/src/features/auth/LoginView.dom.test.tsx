/** @vitest-environment jsdom */
/**
 * 登录失败的那句话要说准:连不上、后端出错、用户名被占,都不是「账号密码错」。
 *
 * 此前这里从 `err.message` 里 JSON.parse 响应体、找 "failed to fetch" —— 可 transport 抛到这里时
 * message 早已翻成人话,离线也另有 ApiOfflineError,于是除了兜底那句,一条分支都走不到:
 * 用户名重复只说「无法创建账户」,后端没起来被说成「用户名或密码不正确」。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, ApiOfflineError } from "@/api/client";

const login = vi.fn();
const register = vi.fn();

vi.mock("@/app/auth", () => ({
  useAuth: () => ({ hasUsers: true, openRegistration: false, login, register }),
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
  login.mockReset();
});

async function submitLoginFailingWith(error: unknown): Promise<void> {
  login.mockRejectedValue(error);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LoginView />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("username"), { target: { value: "kinda" } });
  fireEvent.change(screen.getByLabelText("password"), { target: { value: "secret" } });
  fireEvent.submit(screen.getByLabelText("password").closest("form")!);
}

describe("登录失败的说法", () => {
  it("连不上后端说「连不上」", async () => {
    await submitLoginFailingWith(new ApiOfflineError("http://127.0.0.1:8800 连不上"));
    expect(await screen.findByText("loginNetworkError")).toBeTruthy();
  });

  it("后端 5xx 说「后端出错」", async () => {
    await submitLoginFailingWith(new ApiError("后端出错了", 500, ""));
    expect(await screen.findByText("loginServerError")).toBeTruthy();
  });

  it("401 才说账号密码不对", async () => {
    await submitLoginFailingWith(new ApiError("Invalid credentials", 401, ""));
    expect(await screen.findByText("loginFailed")).toBeTruthy();
  });
});

describe("忘了密码", () => {
  it("登录页说清找谁重置,并给出怎么做的文档", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <LoginView />
      </QueryClientProvider>,
    );
    expect(document.querySelector("[data-login-forgot]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "loginForgot" }));
    const hint = document.querySelector("[data-login-forgot]");
    expect(hint?.textContent).toContain("loginForgotBody");
    expect(hint?.querySelector("a")?.getAttribute("href")).toBe("https://mosael.com/zh/docs/guides/admin");
  });
});
