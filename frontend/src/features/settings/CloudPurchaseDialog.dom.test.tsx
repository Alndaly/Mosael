// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { loadMessages } from "@/app/messageTables";
import { PreferencesProvider } from "@/app/preferences";

const cloud = vi.hoisted(() => ({ listCloudPlans: vi.fn(), createCloudOrder: vi.fn(), getCloudOrder: vi.fn() }));
vi.mock("@/api/domains/cloud", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/cloud")>()),
  ...cloud,
}));
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn(async () => "data:image/png;base64,QR") } }));

import { CloudPurchaseDialog } from "@/features/settings/CloudPurchaseDialog";

const PLANS = {
  plans: [
    { slug: "pro", name: "Pro", period: "month", monthly_credits: 20000, credit_ttl_days: 60, price_cents: 2900, currency: "CNY" },
    { slug: "max", name: "Max", period: "year", monthly_credits: 50000, credit_ttl_days: 60, price_cents: 99900, currency: "CNY" },
  ],
  channels: ["alipay", "wechat"],
};

const order = (status: string) => ({
  id: "o1", status, plan: { slug: "max", name: "Max", period: "year" }, amount_cents: 99900, currency: "CNY",
  channel: "wechat", code_url: status === "pending" ? "weixin://wxpay/bizpayurl?pr=abc" : null,
  created_at: "2026-10-29T10:00:00", expires_at: "2026-10-29T10:30:00", paid_at: null,
  subscription_ends_at: status === "paid" ? "2027-10-29T10:01:00" : null,
});

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <PreferencesProvider>
        <CloudPurchaseDialog open onOpenChange={() => undefined} />
      </PreferencesProvider>
    </QueryClientProvider>,
  );
  return { invalidate };
}

describe("订阅 / 续费", () => {
  beforeAll(() => loadMessages("zh-CN"));
  beforeEach(() => {
    cloud.listCloudPlans.mockReset().mockResolvedValue(PLANS);
    cloud.createCloudOrder.mockReset().mockResolvedValue({ order: order("pending") });
    cloud.getCloudOrder.mockReset();
  });

  it("选套餐和支付方式下单,画出二维码;轮询到到账就说有效期到哪天、刷新余额", async () => {
    cloud.getCloudOrder.mockResolvedValueOnce({ order: order("pending") }).mockResolvedValue({ order: order("paid") });
    const { invalidate } = renderDialog();
    await userEvent.click(await screen.findByRole("radio", { name: /Max/ }));
    await userEvent.click(screen.getByRole("radio", { name: "微信支付" }));
    await userEvent.click(screen.getByRole("button", { name: "去付款" }));

    expect(cloud.createCloudOrder).toHaveBeenCalledWith("max", "wechat");
    expect(await screen.findByText(/用微信支付扫码支付/)).toBeTruthy();
    await waitFor(() => expect(document.querySelector("img")?.getAttribute("src")).toBe("data:image/png;base64,QR"));
    expect(await screen.findByText(/已到账。Max 的有效期到 2027\/10\/29/, {}, { timeout: 6000 })).toBeTruthy();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["cloud-account"] });
  }, 10_000);

  it("二维码过期没付:说没扣款,给重新下单", async () => {
    cloud.getCloudOrder.mockResolvedValue({ order: order("closed") });
    renderDialog();
    await userEvent.click(await screen.findByRole("button", { name: "去付款" }));
    expect(await screen.findByText("二维码过期了,没有扣款。", {}, { timeout: 6000 })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "重新下单" }));
    expect(await screen.findByRole("button", { name: "去付款" })).toBeTruthy();
  }, 10_000);

  it("这个部署没开任何支付渠道:说清楚,不给付款", async () => {
    cloud.listCloudPlans.mockResolvedValue({ ...PLANS, channels: [] });
    renderDialog();
    expect(await screen.findByText("这个部署还没开通在线购买。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "去付款" }).hasAttribute("disabled")).toBe(true);
  });
});
