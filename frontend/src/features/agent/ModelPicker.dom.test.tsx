/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModelPicker } from "./ModelPicker";

const { api, listProviderModels, gotoSettings } = vi.hoisted(() => ({
  api: vi.fn(),
  listProviderModels: vi.fn(),
  gotoSettings: vi.fn(),
}));

vi.mock("@/api/client", () => ({ api, listProviderModels }));
vi.mock("@/lib/deepLink", () => ({ gotoSettings }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      agentConfigureModel: "配置对话模型",
      agentModelLabel: "对话模型",
      agentModelPlaceholder: "选择模型",
      cmdkEmpty: "没有结果",
    })[key] ?? key,
}));

function renderPicker() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ModelPicker workspaceId="workspace-1" session={null} />
    </QueryClientProvider>,
  );
}

describe("ModelPicker", () => {
  beforeEach(() => {
    api.mockReset();
    listProviderModels.mockReset();
    gotoSettings.mockReset();
  });

  it("replaces the empty model picker with a direct configuration action", async () => {
    api.mockImplementation(async (path: string) => {
      if (path === "/api/settings/providers") return [];
      if (path === "/api/settings/provider-defaults") return [];
      throw new Error(`Unexpected API path: ${path}`);
    });

    renderPicker();
    const configure = await screen.findByRole("button", { name: "配置对话模型" });
    fireEvent.click(configure);

    expect(gotoSettings).toHaveBeenCalledWith("providers:chat");
  });

  it("does not flash the configuration action while providers are still loading", async () => {
    let resolveProviders!: (value: unknown[]) => void;
    api.mockImplementation((path: string) => {
      if (path === "/api/settings/providers") {
        return new Promise((resolve) => {
          resolveProviders = resolve;
        });
      }
      if (path === "/api/settings/provider-defaults") return Promise.resolve([]);
      throw new Error(`Unexpected API path: ${path}`);
    });

    renderPicker();
    expect(screen.queryByRole("button", { name: "配置对话模型" })).toBeNull();

    resolveProviders([]);
    await waitFor(() => expect(screen.getByRole("button", { name: "配置对话模型" })).toBeInTheDocument());
  });
});
