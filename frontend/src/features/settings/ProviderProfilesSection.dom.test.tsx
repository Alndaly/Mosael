/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 「一条连接都没有」和「没问出来」是两回事,这一屏必须分得清。
 *
 * 用户撞到的:AI 对话那一页只有一条空灰条 —— 没有列表、没有"还没有连接"、也没有任何错误。
 * 原因是空状态挂在 `profiles.data && ...` 后面:请求失败(401、后端没起、网络断)时 `data` 是
 * undefined,那一行被短路掉,而外层容器照画 —— 于是失败长得和"空"一模一样,而"空"又长得像
 * 什么都没发生。用户看到的是"明明实际是有的,为什么这里空的"。
 *
 * 三种状态三种样子:**在问**(骨架/一句话)、**没问出来**(说清楚,并给重试)、**问出来是空的**
 * (空状态 + 下一步)。
 */

const TEMPLATES: Record<string, string> = {
  providerNoProfiles: "还没有连接",
  providerNoCapabilityProfiles: "这项能力还没有连接",
  providerLoadFailed: "没能读取你的连接",
  retry: "重试",
  connecting: "连接中…",
};

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEMPLATES[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

let providersResult: unknown = [];

vi.mock("@/api/client", () => ({
  api: async (path: string) => {
    if (path.startsWith("/api/settings/providers")) {
      if (providersResult instanceof Error) throw providersResult;
      return providersResult;
    }
    if (path.startsWith("/api/settings/provider-vendors")) return [];
    return [];
  },
  listMembers: async () => ({ my_role: "owner", members: [] }),
}));

import { ProviderProfilesSection } from "@/features/settings/ProviderProfilesSection";

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProviderProfilesSection capability="chat" />
    </QueryClientProvider>,
  );
}

describe("供应商连接列表", () => {
  it("问出来是空的 → 说「还没有连接」", async () => {
    providersResult = [];
    const { container } = renderSection();

    await waitFor(() => expect(container.textContent).toContain(TEMPLATES.providerNoCapabilityProfiles));
  });

  it("没问出来 → 说清楚,并且给一条出路", async () => {
    // 这正是用户撞到的那一屏:此前它和"空"长得一模一样 —— 一条什么都没有的灰条。
    providersResult = new Error("401 未登录");
    const { container } = renderSection();

    await waitFor(() => expect(container.textContent).toContain(TEMPLATES.providerLoadFailed));
    expect(container.textContent).not.toContain(TEMPLATES.providerNoCapabilityProfiles);
    expect(screen.getByText(TEMPLATES.retry)).toBeTruthy();
  });

  it("失败时把后端说的话原样带上 —— 「没能读取」本身不足以让人知道下一步", async () => {
    providersResult = new Error("连接被拒绝:后端没有在 127.0.0.1:8800 上");
    const { container } = renderSection();

    await waitFor(() => expect(container.textContent).toContain("连接被拒绝"));
  });
});
