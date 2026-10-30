/** @vitest-environment jsdom */
/**
 * 设置 → 账户里的「MosaelCloud 账号」:桌面端**自己**用邮箱登录云端。
 *
 * 三条路都要:邮箱 / 手机号 + 密码、邮箱验证码、手机短信验证码。登录之后显示登录标识、退出登录和密码设置;
 * cookie 值不在任何回包里,界面也就没有它可显示。部署关掉了 Cloud 时按钮禁用、说清找谁 ——
 * 界面不摆一颗点了只会错的按钮,也不教用户设环境变量(ADR 0088 §0)。
 */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/transport";
import * as cloudApi from "@/api/domains/cloud";

vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return {
    useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key],
    usePreferences: () => ({ locale: "zh-CN", preferences: {}, updatePreferences: vi.fn() }),
  };
});

vi.mock("@/api/domains/cloud", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/domains/cloud")>();
  return {
    ...actual,
    getCloudSession: vi.fn(),
    loadCloudSession: vi.fn(),
    loginWithPassword: vi.fn(),
    loginWithPhonePassword: vi.fn(),
    verifyCloudMfa: vi.fn(),
    getCloudMfaStatus: vi.fn(),
    setupCloudMfa: vi.fn(),
    enableCloudMfa: vi.fn(),
    disableCloudMfa: vi.fn(),
    regenerateCloudMfaRecoveryCodes: vi.fn(),
    requestCloudLoginCode: vi.fn(),
    verifyCloudLoginCode: vi.fn(),
    requestCloudLoginSmsCode: vi.fn(),
    verifyCloudLoginSms: vi.fn(),
    changeCloudPassword: vi.fn(),
    logoutCloud: vi.fn(),
  };
});

import { CloudAccountSection } from "./AccountSection.cloud";
import { WithQueryClient } from "@/test/queryClient";

const api = vi.mocked(cloudApi);

function apiError(status: number, code: string, message: string): ApiError {
  return new ApiError(message, status, JSON.stringify({ detail: { code, message } }));
}

beforeEach(() => {
  vi.clearAllMocks();
  api.loadCloudSession.mockResolvedValue(null);
  api.getCloudMfaStatus.mockResolvedValue({ enabled: false, recovery_codes_remaining: 0 });
});

afterEach(cleanup);

describe("MosaelCloud 账号", () => {
  it("未登录:邮箱或手机号 + 密码,一条表单纯粹登录", async () => {
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    const email = await screen.findByLabelText("邮箱或手机号");
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument();
    fireEvent.change(email, { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "secret" } });
    api.loginWithPassword.mockResolvedValueOnce({ email: "alice@example.com" });

    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => expect(api.loginWithPassword).toHaveBeenCalledWith("alice@example.com", "secret"));
    expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出登录" })).toBeInTheDocument();
  });

  it("密码那条:手机号走手机号密码接口", async () => {
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    fireEvent.change(await screen.findByLabelText("邮箱或手机号"), { target: { value: "13800138000" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Phone-Horse-9" } });
    api.loginWithPhonePassword.mockResolvedValueOnce({ email: "+8613800138000", has_password: true });

    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() =>
      expect(api.loginWithPhonePassword).toHaveBeenCalledWith("13800138000", "Phone-Horse-9"),
    );
    expect(await screen.findByText("+8613800138000")).toBeInTheDocument();
  });

  it("开了双因素:密码通过后还要输入认证码", async () => {
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    fireEvent.change(await screen.findByLabelText("邮箱或手机号"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "secret" } });
    api.loginWithPassword.mockResolvedValueOnce({
      mfa_required: true,
      ticket: "mfa-ticket",
      methods: ["totp", "recovery"],
    });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("双因素认证")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("验证码或恢复码"), { target: { value: "123456" } });
    api.verifyCloudMfa.mockResolvedValueOnce({ email: "alice@example.com" });
    fireEvent.click(screen.getByRole("button", { name: "验证并登录" }));

    await waitFor(() => expect(api.verifyCloudMfa).toHaveBeenCalledWith("mfa-ticket", "123456"));
    expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
  });

  it("验证码那条:发码 → 填 6 位 → 验证", async () => {
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    fireEvent.click(await screen.findByRole("button", { name: "用邮箱验证码登录" }));
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "bob@example.com" } });
    api.requestCloudLoginCode.mockResolvedValueOnce({ sent: true });

    fireEvent.click(screen.getByRole("button", { name: "发送验证码" }));
    await waitFor(() => expect(api.requestCloudLoginCode).toHaveBeenCalledWith("bob@example.com"));
    expect(await screen.findByText(/验证码已发出/)).toBeInTheDocument();

    const code = screen.getByLabelText("邮箱验证码");
    api.verifyCloudLoginCode.mockResolvedValueOnce({ email: "bob@example.com" });
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "验证并登录" }));

    await waitFor(() => expect(api.verifyCloudLoginCode).toHaveBeenCalledWith("bob@example.com", "123456"));
    expect(await screen.findByText("bob@example.com")).toBeInTheDocument();
  });

  it("短信那条:发短信码 → 填 6 位 → 验证，并进入 60 秒冷却", async () => {
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    fireEvent.click(await screen.findByRole("button", { name: "用手机验证码登录" }));
    fireEvent.change(screen.getByLabelText("手机号"), { target: { value: "13800138000" } });
    api.requestCloudLoginSmsCode.mockResolvedValueOnce({ sent: true });

    fireEvent.click(screen.getByRole("button", { name: "发送验证码" }));
    await waitFor(() => expect(api.requestCloudLoginSmsCode).toHaveBeenCalledWith("13800138000"));
    expect(await screen.findByText(/短信验证码已发出/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重新发送（60s）/ })).toBeDisabled();

    const code = screen.getByLabelText("短信验证码");
    api.verifyCloudLoginSms.mockResolvedValueOnce({ email: "+8613800138000" });
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "验证并登录" }));

    await waitFor(() => expect(api.verifyCloudLoginSms).toHaveBeenCalledWith("13800138000", "123456"));
    expect(await screen.findByText("+8613800138000")).toBeInTheDocument();
  });

  it("已登录且已有密码:验证当前密码后修改", async () => {
    api.loadCloudSession.mockResolvedValueOnce({ email: "dave@example.com", has_password: true });
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    expect(await screen.findByText("修改登录密码")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "old-password" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "New-Horse-9" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "New-Horse-9" } });
    api.changeCloudPassword.mockResolvedValueOnce({ email: "dave@example.com", has_password: true });

    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    await waitFor(() => expect(api.changeCloudPassword).toHaveBeenCalledWith("old-password", "New-Horse-9"));
    expect(await screen.findByText(/密码已更新/)).toBeInTheDocument();
  });

  it("邮箱验证码登录且没有密码:不要求当前密码，可直接设置", async () => {
    api.loadCloudSession.mockResolvedValueOnce({ email: "erin@example.com", has_password: false });
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    expect(await screen.findByText("设置登录密码")).toBeInTheDocument();
    expect(screen.queryByLabelText("当前密码")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "First-Horse-9" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "First-Horse-9" } });
    api.changeCloudPassword.mockResolvedValueOnce({ email: "erin@example.com", has_password: true });
    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    await waitFor(() => expect(api.changeCloudPassword).toHaveBeenCalledWith("", "First-Horse-9"));
  });

  it("已登录且没有密码:显示设置密码,不要求当前密码", async () => {
    api.loadCloudSession.mockResolvedValueOnce({ email: "carol@example.com", has_password: false });
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    expect(await screen.findByText("carol@example.com")).toBeInTheDocument();
    expect(screen.getByText("设置登录密码")).toBeInTheDocument();
    expect(screen.queryByLabelText("当前密码")).not.toBeInTheDocument();
    api.logoutCloud.mockResolvedValueOnce(undefined);
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));

    await waitFor(() => expect(api.logoutCloud).toHaveBeenCalled());
    expect(await screen.findByLabelText("邮箱或手机号")).toBeInTheDocument();
  });

  it("云端密码不足 8 位时提示的是 8 位,不是本地账号的 4 位", async () => {
    api.loadCloudSession.mockResolvedValueOnce({ email: "+8613800138000", has_password: false });
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    await screen.findByText("设置登录密码");
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    expect(await screen.findByText("MosaelCloud 密码至少 8 个字符。")).toBeInTheDocument();
    expect(api.changeCloudPassword).not.toHaveBeenCalled();
  });

  it("短信账号登录后同样能设置密码", async () => {
    api.loadCloudSession.mockResolvedValueOnce({ email: "+8613800138000", has_password: false });
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    expect(await screen.findByText("+8613800138000")).toBeInTheDocument();
    expect(await screen.findByText("设置登录密码")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "Phone-Horse-9" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "Phone-Horse-9" } });
    api.changeCloudPassword.mockResolvedValueOnce({ email: "+8613800138000", has_password: true });
    fireEvent.click(screen.getByRole("button", { name: "更新密码" }));

    await waitFor(() => expect(api.changeCloudPassword).toHaveBeenCalledWith("", "Phone-Horse-9"));
  });

  it("错误原样显示后端文案,不只显示一个 code", async () => {
    render(<CloudAccountSection />, { wrapper: WithQueryClient });
    fireEvent.change(await screen.findByLabelText("邮箱或手机号"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "wrong" } });
    api.loginWithPassword.mockRejectedValueOnce(apiError(401, "invalid_credentials", "邮箱或密码不正确。"));

    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    //: 后端那句人话原样出现在失败卡上;机器码不往界面上摆。
    expect(await screen.findByText("邮箱或密码不正确。")).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toContain("invalid_credentials");
  });

  it("登录中禁用按钮", async () => {
    render(<CloudAccountSection />, { wrapper: WithQueryClient });
    fireEvent.change(await screen.findByLabelText("邮箱或手机号"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "secret" } });
    let release: (value: { email: string }) => void = () => {};
    api.loginWithPassword.mockReturnValueOnce(new Promise((resolve) => { release = resolve; }));

    const button = screen.getByRole("button", { name: "登录" });
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    release({ email: "alice@example.com" });
    expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
  });

  it("部署关掉了 Cloud:按钮禁用,说清找部署管理员,不教用户设环境变量", async () => {
    api.loadCloudSession.mockRejectedValueOnce(
      apiError(503, "cloud_not_configured", "MosaelCloud is not configured for this deployment."),
    );
    render(<CloudAccountSection />, { wrapper: WithQueryClient });

    expect(await screen.findByText("这个部署关闭了 MosaelCloud。")).toBeInTheDocument();
    expect(screen.getByText("需要的话请联系部署管理员。")).toBeInTheDocument();
    expect(screen.queryByText(/MOSAEL_CLOUD_URL/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录" })).toBeDisabled();
    expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
  });
});
