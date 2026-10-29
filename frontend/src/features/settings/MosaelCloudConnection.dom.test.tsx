// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProviderProfile } from "@/api/domains/providers";
import { ApiError } from "@/api/transport";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      providerMosaelCloud: "Mosael Cloud",
      providerMosaelCloudSignedIn: "官方中转 · {email}",
      providerMosaelCloudSignedOut: "登录后可用",
      providerMosaelCloudSignIn: "去登录",
      providerMosaelCloudSoon: "这类模型即将开放",
      providerMosaelCloudCredits: "{credits} 积分",
      providerMosaelCloudRefresh: "刷新",
      providerMosaelCloudSynced: "取到 {n} 个模型",
      modelListTitle: "模型",
    })[key] ?? key,
}));

let session: () => Promise<unknown> = async () => null;
const cloud = vi.hoisted(() => ({ getCloudAccount: vi.fn(), syncCloudConnection: vi.fn() }));
vi.mock("@/api/domains/cloud", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/cloud")>()),
  loadCloudSession: () => session(),
  getCloudAccount: () => cloud.getCloudAccount(),
  syncCloudConnection: () => cloud.syncCloudConnection(),
}));
vi.mock("@/features/settings/ProviderModelList", () => ({
  ProviderModelList: ({ profileId }: { profileId: string }) => <div data-testid="models">{profileId}</div>,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const gotoSettings = vi.fn();
vi.mock("@/lib/deepLink", () => ({ gotoSettings: (id: string) => gotoSettings(id) }));

import { MosaelCloudConnection } from "@/features/settings/MosaelCloudConnection";

const PROFILE = { id: "cloud-1", vendor: "mosael-cloud", name: "Mosael Cloud" } as ProviderProfile;

function renderRow(props: { profile?: ProviderProfile | null; offersCapability?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MosaelCloudConnection profile={props.profile ?? null} offersCapability={props.offersCapability ?? false} />
    </QueryClientProvider>,
  );
}

describe("供应商列表里的 Mosael Cloud", () => {
  beforeEach(() => {
    gotoSettings.mockReset();
    cloud.getCloudAccount.mockReset().mockResolvedValue({ credits: 998, batches: [], next_grant_at: null, plan: "Pro" });
    cloud.syncCloudConnection.mockReset().mockResolvedValue({ profile_id: "cloud-1", models: 3 });
  });

  it("登录了:写出账号和积分,不给登录按钮", async () => {
    session = async () => ({ email: "alice@example.com" });
    renderRow({ profile: PROFILE, offersCapability: true });
    expect(await screen.findByText(/官方中转 · alice@example.com · 998 积分/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "去登录" })).toBeNull();
  });

  it("这一页的能力网关有:能展开看模型(就是那条连接的模型行)", async () => {
    session = async () => ({ email: "alice@example.com" });
    renderRow({ profile: PROFILE, offersCapability: true });
    await userEvent.click(await screen.findByRole("button", { name: "模型" }));
    expect(screen.getByTestId("models").textContent).toBe("cloud-1");
    expect(screen.queryByText("这类模型即将开放")).toBeNull();
  });

  it("这一页的能力网关还没有:说即将开放,不给展开", async () => {
    session = async () => ({ email: "alice@example.com" });
    renderRow({ profile: PROFILE, offersCapability: false });
    expect(await screen.findByText("这类模型即将开放")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "模型" })).toBeNull();
  });

  it("「刷新」重新对齐网关目录", async () => {
    session = async () => ({ email: "alice@example.com" });
    renderRow({ profile: null });
    await userEvent.click(await screen.findByRole("button", { name: "刷新" }));
    await waitFor(() => expect(cloud.syncCloudConnection).toHaveBeenCalledTimes(1));
  });

  it("没登录也列出来,点「去登录」跳到账户页", async () => {
    session = async () => null;
    renderRow();
    await userEvent.click(await screen.findByRole("button", { name: "去登录" }));
    expect(gotoSettings).toHaveBeenCalledWith("account");
    expect(cloud.getCloudAccount).not.toHaveBeenCalled();
  });

  it("部署关掉了 Cloud 就不出现", async () => {
    let asked = 0;
    session = async () => {
      asked += 1;
      throw new ApiError("off", 503, JSON.stringify({ detail: { code: "cloud_not_configured" } }));
    };
    const { container } = renderRow();
    await waitFor(() => expect(asked).toBe(1));
    await act(async () => {});
    expect(container.textContent).toBe("");
  });
});
