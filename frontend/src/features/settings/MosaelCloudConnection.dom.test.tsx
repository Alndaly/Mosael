// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/transport";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      providerMosaelCloud: "Mosael Cloud",
      providerMosaelCloudSignedIn: "官方中转 · {email}",
      providerMosaelCloudSignedOut: "登录后可用",
      providerMosaelCloudSignIn: "去登录",
      providerMosaelCloudSoon: "模型即将开放",
    })[key] ?? key,
}));

let session: () => Promise<unknown> = async () => null;
vi.mock("@/api/domains/cloud", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/cloud")>()),
  loadCloudSession: () => session(),
}));

const gotoSettings = vi.fn();
vi.mock("@/lib/deepLink", () => ({ gotoSettings: (id: string) => gotoSettings(id) }));

import { MosaelCloudConnection } from "@/features/settings/MosaelCloudConnection";

function renderRow() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MosaelCloudConnection />
    </QueryClientProvider>,
  );
}

describe("供应商列表里的 Mosael Cloud", () => {
  beforeEach(() => gotoSettings.mockReset());

  it("登录了就写出是哪个账号,不给登录按钮", async () => {
    session = async () => ({ email: "alice@example.com" });
    renderRow();
    expect(await screen.findByText("官方中转 · alice@example.com")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "去登录" })).toBeNull();
  });

  it("没登录也列出来,点「去登录」跳到账户页", async () => {
    session = async () => null;
    renderRow();
    await userEvent.click(await screen.findByRole("button", { name: "去登录" }));
    expect(gotoSettings).toHaveBeenCalledWith("account");
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
