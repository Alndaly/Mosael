/** @vitest-environment jsdom */
/**
 * 设置 → 账户里的「MosaelCloud 账号」。
 *
 * 维护者原话:「软件内没有登录云账号的地方」。这个区块要回答四件事:
 *
 * - 没绑的时候,说清云账号是什么、和本地账号是什么关系、不绑也能用;主操作是**登录**(设备码),
 *   确认码要大、可复制,浏览器能打开;
 * - 已绑的时候,看得到绑的是哪个邮箱、什么时候绑的、绑在哪台设备;
 * - 解绑只解这一台,解完**从后端重读**,不在组件里自己改状态;
 * - 等待 / 成功 / 失败三态都有话说,过期与已用把云端错误码原样转述,连不上说「连不上」。
 *
 * 桌面窗口里没有云端的 HttpOnly 会话 cookie,所以这里**只走设备码**,不做邮箱 + 密码的假登录。
 */
import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/transport";
import { parseServerTime } from "@/lib/time";

const h = vi.hoisted(() => ({
  status: vi.fn(),
  start: vi.fn(),
  complete: vi.fn(),
  unbind: vi.fn(),
}));

vi.mock("@/api/domains/cloud", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/domains/cloud")>();
  return {
    ...actual,
    getCloudBinding: h.status,
    startCloudBinding: h.start,
    completeCloudBinding: h.complete,
    unbindCloudBinding: h.unbind,
  };
});
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return {
    useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key],
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});

import { CloudBindingSection } from "./CloudBindingSection";

const unbound = { bound: false, email: null, device_id: null, created_at: null };
const bound = {
  bound: true,
  email: "alice@example.com",
  device_id: "cloud-device-1",
  created_at: "2026-10-20T00:00:00",
};
const code = {
  status: "pending_authorization" as const,
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
  h.start.mockResolvedValue(code);
});
afterEach(cleanup);

async function signIn(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "登录 MosaelCloud" }));
  await screen.findByText("ABCD-EFGH");
}

describe("MosaelCloud 账号", () => {
  it("未绑定时:说清云账号能做什么、和本地账号什么关系、不绑也能用;主操作是登录", async () => {
    h.status.mockResolvedValue(unbound);
    render(<CloudBindingSection />);

    expect(await screen.findByRole("button", { name: "登录 MosaelCloud" })).toBeTruthy();
    expect(screen.getByText(/用来登录官网、管理云端设备/)).toBeTruthy();
    //: 这一块已经排在本地账号之后,而且从此只说名字、不说方位。
    expect(screen.queryByText(/上面的本地账号/)).toBeNull();
    expect(screen.queryByText(/上面|下面|如上/)).toBeNull();
    //: 说清两者的关系:本地账号管本机,云账号独立,不绑也能用全部本地功能。
    expect(screen.getByText(/本地账号管这台机器/)).toBeTruthy();
    expect(screen.getByText(/两个是独立的/)).toBeTruthy();
    expect(screen.getByText(/不绑云账号也能用全部本地功能/)).toBeTruthy();
    //: 浏览器里可以用第三方登录,但软件内不内嵌它们 —— 这一句也要在。
    expect(screen.getByText(/GitHub \/ Google/)).toBeTruthy();
    expect(screen.queryByText(/alice@example\.com/)).toBeNull();
  });

  it("设备码:大字显示确认码、可以复制、能把浏览器打开", async () => {
    h.status.mockResolvedValue(unbound);
    const user = userEvent.setup();
    //: userEvent.setup() 自己会换掉 navigator.clipboard —— 要在它之后再装我们的桩。
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<CloudBindingSection />);

    await signIn(user);

    const shown = screen.getByText("ABCD-EFGH");
    expect(shown.tagName).toBe("CODE");
    //: 确认码是这一步唯一要用户抄/对的东西,不能和正文同字号。
    expect(shown.className).toContain("text-2xl");
    expect(screen.getByText(/等你在浏览器里确认/)).toBeTruthy();

    const open = screen.getByRole("link", { name: "在浏览器里打开" });
    expect(open.getAttribute("href")).toBe(code.verification_uri_complete);

    await user.click(screen.getByRole("button", { name: "复制确认码" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("ABCD-EFGH"));
    expect(await screen.findByRole("button", { name: "已复制" })).toBeTruthy();
  });

  it("已绑定时:显示云端邮箱、登录时间和设备,并给「解除本机绑定」", async () => {
    h.status.mockResolvedValue(bound);
    render(<CloudBindingSection />);

    expect(await screen.findByText("已登录为 alice@example.com")).toBeTruthy();
    const when = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(
      parseServerTime(bound.created_at),
    );
    expect(screen.getByText(`登录时间:${when}`)).toBeTruthy();
    expect(screen.getByText("设备:这台电脑")).toBeTruthy();
    expect(screen.getByText(/只是这台电脑/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "解除本机绑定" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "登录 MosaelCloud" })).toBeNull();
  });

  it("解绑后从后端重读:状态立刻回到未绑定", async () => {
    h.status.mockResolvedValueOnce(bound).mockResolvedValue(unbound);
    h.unbind.mockResolvedValue({ removed: true });
    const user = userEvent.setup();
    render(<CloudBindingSection />);

    await user.click(await screen.findByRole("button", { name: "解除本机绑定" }));

    expect(await screen.findByRole("button", { name: "登录 MosaelCloud" })).toBeTruthy();
    await waitFor(() => expect(h.status).toHaveBeenCalledTimes(2));
    expect(h.unbind).toHaveBeenCalledTimes(1);
  });

  it("确认成功后也从后端重读,不拿 complete 的回包当状态", async () => {
    h.status.mockResolvedValueOnce(unbound).mockResolvedValue(bound);
    h.complete.mockResolvedValue({ status: "approved", email: "alice@example.com", device_id: "cloud-device-1" });
    const user = userEvent.setup();
    render(<CloudBindingSection />);

    await signIn(user);
    await user.click(screen.getByRole("button", { name: "我已确认" }));

    expect(await screen.findByText("已登录为 alice@example.com")).toBeTruthy();
    expect(await screen.findByText("已登录 MosaelCloud。")).toBeTruthy();
    await waitFor(() => expect(h.status).toHaveBeenCalledTimes(2));
  });

  it("还没确认:保留确认码,说明要回浏览器确认", async () => {
    h.status.mockResolvedValue(unbound);
    h.complete.mockResolvedValue({ status: "pending", email: null, device_id: null });
    const user = userEvent.setup();
    render(<CloudBindingSection />);

    await signIn(user);
    await user.click(screen.getByRole("button", { name: "我已确认" }));

    expect(await screen.findByText(/还没确认/)).toBeTruthy();
    expect(screen.getByText("ABCD-EFGH")).toBeTruthy();
    expect(screen.getByRole("button", { name: "我已确认" })).toBeTruthy();
  });

  it("确认码过期:原样转述云端错误码,并给重新获取", async () => {
    h.status.mockResolvedValue(unbound);
    h.complete.mockRejectedValue(
      new ApiError(
        "This code expired.",
        410,
        JSON.stringify({ detail: { code: "device_code_expired", message: "This code expired." } }),
      ),
    );
    const user = userEvent.setup();
    render(<CloudBindingSection />);

    await signIn(user);
    await user.click(screen.getByRole("button", { name: "我已确认" }));

    expect(await screen.findByText(/device_code_expired/)).toBeTruthy();
    expect(screen.getByText(/确认码已过期或已被使用/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "重新获取确认码" })).toBeTruthy();
  });

  it("连不上 MosaelCloud:说清楚,登录入口还在,不是一颗死按钮", async () => {
    h.status.mockResolvedValue(unbound);
    h.start.mockRejectedValue(
      new ApiError(
        "Can't reach MosaelCloud.",
        503,
        JSON.stringify({ detail: { code: "cloud_unreachable", message: "Can't reach MosaelCloud." } }),
      ),
    );
    const user = userEvent.setup();
    render(<CloudBindingSection />);

    await user.click(await screen.findByRole("button", { name: "登录 MosaelCloud" }));

    expect(await screen.findByText(/连不上 MosaelCloud/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "登录 MosaelCloud" })).toBeTruthy();
  });

  it("读不到绑定状态时同样说「连不上」,并给重试", async () => {
    h.status
      .mockRejectedValueOnce(
        new ApiError(
          "Can't reach MosaelCloud.",
          503,
          JSON.stringify({ detail: { code: "cloud_unreachable", message: "Can't reach MosaelCloud." } }),
        ),
      )
      .mockResolvedValueOnce(unbound);
    const user = userEvent.setup();
    render(<CloudBindingSection />);

    expect(await screen.findByText(/连不上 MosaelCloud/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("button", { name: "登录 MosaelCloud" })).toBeTruthy();
  });
});
