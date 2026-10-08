/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 默认模型一格空着时,说的下一步要对得上这一页:连接列表在**下面**;「一条都没有」和「有、但都停用了」
 * 下一步不一样(添加 / 启用);别的能力的连接不算数(图像页上有一条对话连接,图像照样没有东西可选)。
 */

let providers: unknown[] = [];
let defaults: unknown[] = [];
let models: unknown[] = [];

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

//: 替身落在 transport 上:api/domains/providers 的函数经过它。
vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: async (path: string) => {
    if (path === "/api/settings/providers") return providers;
    if (path.startsWith("/api/settings/provider-defaults")) return defaults;
    if (path.includes("models")) return models;
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

//: 体检 UM-23:默认模型指向「未授权 / 缺密钥」的连接时此前毫无提示,AI Studio、智能体用默认模型时才报错。
describe("默认模型所在的连接用不了", () => {
  beforeEach(() => {
    providers = [];
    defaults = [];
    models = [];
  });

  it("说清是哪条连接、为什么用不了;「去处理」把焦点交给那条连接上修它的按钮", async () => {
    providers = [{ id: "kimi", name: "Kimi", enabled: true, capability_ids: ["chat"], auth_type: "oauth", oauth_linked: false, key_hint: "" }];
    defaults = [{ capability: "chat", provider_profile_id: "kimi", model: "k3", is_mine: true }];
    models = [{ provider_profile_id: "kimi", provider_name: "Kimi", model: "k3", display_name: "k3" }];
    //: 连接列表那一行(另一个组件画的)只要有这个 id 和修它的按钮就行。
    const row = document.createElement("div");
    row.id = "provider-profile-kimi";
    row.scrollIntoView = () => {};
    const fix = document.createElement("button");
    fix.setAttribute("data-provider-fix", "");
    row.append(fix);
    document.body.append(row);

    const { container } = renderSection("chat");
    await waitFor(() => expect(container.querySelector('[data-default-broken="unauthorized"]')).not.toBeNull());
    expect(container.querySelector("[data-default-broken]")?.textContent).toContain("providerDefaultBroken_unauthorized");
    fireEvent.click(screen.getByRole("button", { name: "providerDefaultFix" }));
    expect(document.activeElement).toBe(fix);
    row.remove();
  });

  it("连接好好的就不说", async () => {
    providers = [{ id: "kimi", name: "Kimi", enabled: true, capability_ids: ["chat"], auth_type: "api_key", key_hint: "…abcd" }];
    defaults = [{ capability: "chat", provider_profile_id: "kimi", model: "k3", is_mine: true }];
    models = [{ provider_profile_id: "kimi", provider_name: "Kimi", model: "k3", display_name: "k3" }];
    const { container } = renderSection("chat");
    await screen.findByText("capChat");
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(container.querySelector("[data-default-broken]")).toBeNull();
  });
});
