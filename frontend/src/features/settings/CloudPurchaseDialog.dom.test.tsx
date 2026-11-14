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
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

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
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <PreferencesProvider>
        <CloudPurchaseDialog open onOpenChange={onOpenChange} />
      </PreferencesProvider>
    </QueryClientProvider>,
  );
  return { invalidate, onOpenChange };
}

describe("订阅 / 续费", () => {
  beforeAll(() => loadMessages("zh-CN"));
  beforeEach(() => {
    cloud.listCloudPlans.mockReset().mockResolvedValue(PLANS);
    cloud.createCloudOrder.mockReset().mockResolvedValue({ order: order("pending") });
    cloud.getCloudOrder.mockReset();
    toast.success.mockReset();
  });

  it("选套餐和支付方式下单,画出二维码;到账就收起购买框,提示有效期到哪天、刷新余额(不留中间页)", async () => {
    cloud.getCloudOrder.mockResolvedValueOnce({ order: order("pending") }).mockResolvedValue({ order: order("paid") });
    const { invalidate, onOpenChange } = renderDialog();
    await userEvent.click(await screen.findByRole("radio", { name: /Max/ }));
    await userEvent.click(screen.getByRole("radio", { name: "微信支付" }));
    await userEvent.click(screen.getByRole("button", { name: "去付款" }));

    expect(cloud.createCloudOrder).toHaveBeenCalledWith("max", "wechat");
    expect(await screen.findByText(/用微信支付扫码支付/)).toBeTruthy();
    await waitFor(() => expect(document.querySelector("img")?.getAttribute("src")).toBe("data:image/png;base64,QR"));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false), { timeout: 6000 });
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(toast.success.mock.calls[0][0]).toMatch(/订阅成功:Max 有效期到 2027\/10\/29/);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["cloud-account"] });
    //: 到账那一刻二维码就卸掉了,框里不留「已到账」那一页
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("[data-cloud-order]")).toBeNull();
  }, 10_000);

  it("二维码过期没付:说没扣款,给重新下单", async () => {
    cloud.getCloudOrder.mockResolvedValue({ order: order("closed") });
    renderDialog();
    await userEvent.click(await screen.findByRole("button", { name: "去付款" }));
    expect(await screen.findByText("二维码过期了,没有扣款。", {}, { timeout: 6000 })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "重新下单" }));
    expect(await screen.findByRole("button", { name: "去付款" })).toBeTruthy();
  }, 10_000);

  it("支付宝网页支付只渲染 200 方形二维码，不再嵌入整页", async () => {
    cloud.createCloudOrder.mockResolvedValue({
      order: {
        ...order("pending"),
        channel: "alipay",
        code_url: null,
        payment_html: '<form action="https://openapi.alipay.com/gateway.do"></form>',
      },
    });
    renderDialog();
    await userEvent.click(await screen.findByRole("button", { name: "去付款" }));
    const iframe = await waitFor(() => {
      const element = document.querySelector("iframe");
      expect(element).not.toBeNull();
      return element!;
    });
    expect(iframe.getAttribute("srcdoc")).toContain("openapi.alipay.com");
    expect(iframe.getAttribute("src")).toBeNull();
    expect(iframe.getAttribute("sandbox")).toBeNull();
    expect(iframe.className).toContain("size-[200px]");
  });

  it("这个部署没开任何支付渠道:说清楚,不给付款", async () => {
    cloud.listCloudPlans.mockResolvedValue({ ...PLANS, channels: [] });
    renderDialog();
    expect(await screen.findByText("这个部署还没开通在线购买。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "去付款" }).hasAttribute("disabled")).toBe(true);
  });
});
