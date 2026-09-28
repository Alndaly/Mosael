/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 默认模型一格空着时,说的下一步要对得上这一页:连接列表在**下面**;「一条都没有」和「有、但都停用了」
 * 下一步不一样(添加 / 启用);别的能力的连接不算数(图像页上有一条对话连接,图像照样没有东西可选)。
 */

let providers: unknown[] = [];

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

//: 替身落在 transport 上:api/domains/providers 的函数经过它。
vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: async (path: string) => {
    if (path === "/api/settings/providers") return providers;
    return [];
  },
}));

import { ProviderDefaultsSection } from "./ProviderDefaultsSection";

function renderSection(capability: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProviderDefaultsSection capabilities={[capability]} />
    </QueryClientProvider>,
  );
}

const profile = (id: string, capability: string, enabled: boolean) => ({ id, name: id, enabled, capability_ids: [capability] });

describe("默认模型的空态", () => {
  beforeEach(() => {
    providers = [];
  });

  it("这项能力一条连接都没有:让他去下面添加", async () => {
    providers = [profile("chat-1", "chat", true)];
    renderSection("image");
    expect(await screen.findByText("providerDefaultsNoProvider")).toBeTruthy();
  });

  it("有连接但都停用了:让他去下面启用,而不是再加一条", async () => {
    providers = [profile("img-1", "image", false)];
    renderSection("image");
    expect(await screen.findByText("providerDefaultsAllDisabled")).toBeTruthy();
    expect(screen.queryByText("providerDefaultsNoProvider")).toBeNull();
  });

  it("有启用着的连接:列出默认模型那一行", async () => {
    providers = [profile("img-1", "image", true)];
    renderSection("image");
    expect(await screen.findByText("capImage")).toBeTruthy();
    expect(screen.queryByText("providerDefaultsNoProvider")).toBeNull();
    expect(screen.queryByText("providerDefaultsAllDisabled")).toBeNull();
  });
});
