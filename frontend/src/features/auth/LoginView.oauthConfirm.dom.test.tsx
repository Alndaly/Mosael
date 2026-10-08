/** @vitest-environment jsdom */
/**
 * 第三方登录要把回调页上的确认码填回来才登进去(D56 / SEC-11)。浏览器那边成了,轮询只说「等确认」,这里换成确认码输入框;
 * 填对了才拿到票落座,填错了说还能试几次;轮询本身从不交票。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const adoptAuth = vi.fn();
const confirmAnswers: Array<Record<string, unknown>> = [];

vi.mock("@/app/auth", () => ({
  useAuth: () => ({ hasUsers: true, openRegistration: false, login: vi.fn(), register: vi.fn(), adoptAuth }),
}));
vi.mock("@/app/preferences", () => {
  const t = (key: string) => key;
  return { useI18n: () => t, usePreferences: () => ({ locale: "zh", setLocale: () => undefined, t }) };
});
vi.mock("@/components/app/ServerPicker", () => ({ ServerPicker: () => null }));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  oauthProviders: async () => ({ providers: ["google"] }),
  oauthStart: async () => ({ pending_id: "p-1", url: "https://accounts.example/auth" }),
  oauthPending: vi.fn(async () => ({ status: "confirm" })),
  oauthConfirm: vi.fn(async () => confirmAnswers.shift() ?? { status: "expired" }),
}));

const { LoginView } = await import("./LoginView");
const { oauthConfirm } = await import("@/api/client");

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.spyOn(window, "open").mockImplementation(() => null);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  adoptAuth.mockReset();
  vi.mocked(oauthConfirm).mockClear();
  confirmAnswers.length = 0;
});

async function startGoogleAndReachConfirm() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LoginView />
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByRole("button", { name: /authContinueGoogle/ }));
  await waitFor(() => expect(screen.getByText("authOauthWaiting")).toBeTruthy());
  await act(async () => {
    vi.advanceTimersByTime(2100);
  });
  return screen.findByLabelText("authOauthConfirmLead");
}

it("浏览器那边成了:不直接落座,换成确认码输入框", async () => {
  const input = await startGoogleAndReachConfirm();
  expect(input).toBeTruthy();
  expect(adoptAuth).not.toHaveBeenCalled();
  expect(screen.queryByText("authOauthWaiting")).toBeNull();
});

it("填错说还能试几次;填对才拿到票落座", async () => {
  confirmAnswers.push({ status: "wrong_code", attempts_left: 4 });
  confirmAnswers.push({ status: "done", token: "t-1", user: { id: "u-1" } });
  const input = await startGoogleAndReachConfirm();

  fireEvent.change(input, { target: { value: "aaa-aaa" } });
  fireEvent.click(screen.getByRole("button", { name: "authOauthConfirmSubmit" }));
  expect(await screen.findByText("authOauthWrongCode")).toBeTruthy();
  expect(adoptAuth).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: "K7P-4QX" } });
  fireEvent.click(screen.getByRole("button", { name: "authOauthConfirmSubmit" }));
  await waitFor(() => expect(adoptAuth).toHaveBeenCalledWith({ token: "t-1", user: { id: "u-1" } }));
  expect(vi.mocked(oauthConfirm).mock.calls).toEqual([["p-1", "aaa-aaa"], ["p-1", "K7P-4QX"]]);
});

it("试满作废:说原因,回到能重新点登录的样子", async () => {
  confirmAnswers.push({ status: "error", error: "确认码填错太多次" });
  const input = await startGoogleAndReachConfirm();

  fireEvent.change(input, { target: { value: "BBBBBB" } });
  fireEvent.click(screen.getByRole("button", { name: "authOauthConfirmSubmit" }));

  expect(await screen.findByText("确认码填错太多次")).toBeTruthy();
  expect(screen.queryByLabelText("authOauthConfirmLead")).toBeNull();
  expect(screen.getByRole("button", { name: /authContinueGoogle/ })).toBeEnabled();
});
