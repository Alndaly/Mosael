/** @vitest-environment jsdom */

/**
 * 「版本」那一行**不许说谎**(ADR 0073):当前版本、上游最新、上次检查、能不能升,四种状态各说各的。
 *
 * 最要紧的一条:「已经是最新的」**只有**当前 == 上游最新时才出现;查不到(离线、限流、404)要说查不到,
 * 不能让它看起来像「已最新」。「查不到」时内置表里还有更新的话,按钮照样给(离线降级路径)。
 *
 * 中英各渲染一遍:这两句在两种语言里都不能说出「已最新」。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getLocalServiceVersions: vi.fn(),
  updateLocalService: vi.fn(),
  rollbackLocalService: vi.fn(),
  getLocalServiceLogs: vi.fn(),
}));
vi.mock("@/api/client", () => api);
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

let locale: "zh-CN" | "en-US" = "zh-CN";
vi.mock("@/app/preferences", async (original) => {
  const { messages } = await import("@/app/messages");
  return {
    ...(await original<typeof import("@/app/preferences")>()),
    useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages[locale][key],
    usePreferences: () => ({ locale }),
  };
});

import type { LocalService } from "@/api/client";
import { messages } from "@/app/messages";
import { ManagedVersion } from "./LocalServiceVersion";

const SERVICE = {
  service: "comfyui", title: "ComfyUI", mode: "managed", directory: "/data/local-services/i1", python: "", port: 8189,
  url: "http://127.0.0.1:8189", state: "running", installed: true, can_manage: true, install: null,
} as unknown as LocalService;

const versions = (overrides: Record<string, unknown> = {}) => ({
  current: "0.39.0",
  latest: "0.39.0",
  update: "0.41.0",
  previous: "",
  unfinished: "",
  source: "upstream",
  upstream: {
    status: "ok",
    version: "0.41.0",
    tag: "v0.41.0",
    notes: "Add ImageSDRToHDR node.",
    url: "https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.41.0",
    checked_at: "2026-10-15T22:57:45Z",
    message: "",
  },
  ...overrides,
});

const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ManagedVersion instanceId="i1" service={SERVICE} />
    </QueryClientProvider>,
  );

describe("版本那一行", () => {
  beforeEach(() => {
    locale = "zh-CN";
    api.getLocalServiceVersions.mockReset();
    api.updateLocalService.mockReset();
    api.rollbackLocalService.mockReset();
  });
  afterEach(cleanup);

  it.each(["zh-CN", "en-US"] as const)("可升到上游最新(%s):当前 / 上游最新 / 上次检查 / 可升都写出来", async (one) => {
    locale = one;
    api.getLocalServiceVersions.mockResolvedValue(versions());
    mount();
    const table = messages[one];
    expect(await screen.findByText(table.localServiceVersionAvailable.replace("{current}", "0.39.0")
      .replace("{latest}", "0.41.0"))).toBeTruthy();
    expect(screen.getByText(table.localServiceVersionFactCurrent.replace("{version}", "0.39.0"))).toBeTruthy();
    expect(screen.getByText(table.localServiceVersionFactUpstream.replace("{version}", "0.41.0"))).toBeTruthy();
    expect(screen.getByText(new RegExp(`^${table.localServiceVersionFactChecked.replace("{time}", "")}`))).toBeTruthy();
    expect(screen.getByText(table.localServiceVersionFactUpdate.replace("{version}", "0.41.0"))).toBeTruthy();
    expect(screen.getByRole("button", { name: table.localServiceUpdateTo.replace("{version}", "0.41.0") })).toBeTruthy();
    expect(screen.queryByText(table.localServiceVersionLatest.replace("{current}", "0.39.0"))).toBeNull();
  });

  it.each(["zh-CN", "en-US"] as const)("当前 == 上游最新(%s):才说已经是最新的", async (one) => {
    locale = one;
    api.getLocalServiceVersions.mockResolvedValue(versions({
      current: "0.41.0", update: "", source: "", upstream: versions().upstream,
    }));
    mount();
    const table = messages[one];
    expect(await screen.findByText(table.localServiceVersionLatest.replace("{current}", "0.41.0"))).toBeTruthy();
    expect(screen.queryByRole("button", { name: new RegExp(table.localServiceUpdateTo.replace("{version}", ".*")) })).toBeNull();
  });

  it.each(["zh-CN", "en-US"] as const)("查不到上游(%s):说查不到和原因,绝不说已经是最新的;内置表有更新照样给按钮", async (one) => {
    locale = one;
    const reason = one === "zh-CN" ? "连不上 GitHub(离线、代理或网络问题)" : "Couldn't reach GitHub (offline, proxy, or network problem)";
    api.getLocalServiceVersions.mockResolvedValue(versions({
      update: "0.39.0", source: "pinned",
      upstream: {
        status: "offline", version: "", tag: "", notes: "", url: "", checked_at: "", message: reason,
      },
    }));
    mount();
    const table = messages[one];
    const prefix = table.localServiceVersionCheckFailed.split("{reason}")[0].trim();
    const warning = await screen.findByText(new RegExp(prefix));
    expect(warning.textContent).toContain(reason);
    expect(screen.getByText(table.localServiceVersionPinned.replace("{current}", "0.39.0")
      .replace("{version}", "0.39.0"))).toBeTruthy();
    expect(screen.getByRole("button", { name: table.localServiceUpdateTo.replace("{version}", "0.39.0") })).toBeTruthy();
    expect(screen.queryByText(table.localServiceVersionLatest.replace("{current}", "0.39.0"))).toBeNull();
  });
});
