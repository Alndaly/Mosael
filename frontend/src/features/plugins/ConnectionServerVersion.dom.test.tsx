/** @vitest-environment jsdom */

/**
 * 「连一台服务器」的连接卡上也要看得到版本(维护者截图:展开后是名称 / 在哪跑 / 服务器地址 / 凭据 / token,没有版本)。
 *
 * 宿主那一侧本来就支持任意实例:没有本机服务那一行时,版本查询从连接配置的 `server_url` 问远端那台的
 * `/system_stats`(`running_version` 里 `row is None` 那一路);缺的是连接页不画那一行。这里钉住:
 *
 * - 展开的「连一台服务器」连接有一行安静的事实:版本;问一次,显示远端自己报的版本;
 * - 连不上 / 超时只影响这一行,连接卡其余照常,不报错;
 * - 它在跑但没报版本 -> 说清它没报,不猜一个;
 * - 远端**永远**不是 Mosael 装的那一份:文案说 Mosael 只连过去,不装也不起停它;
 * - 「用我自己装的」那一行的文案和行为不变(回归);
 * - 不展开的连接不为它探;展开哪张才探哪张,页头和连接卡共用同一个 query key,只探一次。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  packages: [] as Array<Record<string, unknown>>,
  services: {} as Record<string, Record<string, unknown> | null>,
  versions: vi.fn(),
  version: vi.fn(),
  local: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

//: 详情那一栏要的接口很多,这里只关心版本那一行:认得的几个给真数据,其余一律回空(和
//: PluginServiceVersion.dom.test 同一个写法)。
vi.mock("@/api/client", () => {
  const known: Record<string, unknown> = {
    listPluginPackages: async () => h.packages,
    listPluginMarket: async () => ({ plugins: [], index_error: "" }),
    pluginDir: async () => ({ path: "/plugins" }),
    rescanPlugins: async () => [],
    getLocalService: (id: string) => h.local(id),
    getLocalServiceVersions: (id: string) => h.versions(id),
    getLocalServiceVersion: (id: string) => h.version(id),
    discoverLocalServices: async () => ({ servers: [] }),
    getLocalServiceModelFolders: async () => ({ folders: [], running: false, suggestions: [] }),
  };
  const fallback = new Map<string, unknown>();
  return new Proxy(known, {
    get: (target, key) => {
      if (typeof key !== "string" || key === "then" || key in target) return target[key as string];
      if (!fallback.has(key)) fallback.set(key, vi.fn().mockResolvedValue([]));
      return fallback.get(key);
    },
    has: (target, key) => key !== "then" && (typeof key === "string" || key in target),
  });
});
vi.mock("sonner", () => ({ toast: h.toast }));

let locale: "zh-CN" | "en-US" = "zh-CN";
vi.mock("@/app/preferences", async (original) => {
  const { messages } = await import("@/app/messages");
  return {
    ...(await original<typeof import("@/app/preferences")>()),
    useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages[locale][key],
    usePreferences: () => ({ locale }),
  };
});

import { messages } from "@/app/messages";
import { PluginsView } from "./PluginsView";

/** 一个声明了本机服务、但连接都是「连一台服务器」的 ComfyUI 包。 */
const PKG = (connections: string[]) => ({
  id: "dev.mosael.comfyui",
  name: "ComfyUI",
  version: "1.12.4",
  kind: "process",
  multiple: true,
  permissions: [],
  provides: ["generation"],
  summary_field: "server_url",
  config_fields: [{ key: "server_url", label: "服务器地址", type: "string", required: true }],
  credential_fields: [],
  services: [{ key: "comfyui", title: "ComfyUI", tool: "comfyui_generation" }],
  instances: connections.map((connectionId) => ({
    id: connectionId,
    package_id: "dev.mosael.comfyui",
    name: `ComfyUI · ${connectionId}`,
    enabled: true,
    config: { server_url: "http://127.0.0.1:8189" },
    blocked_reason: "",
    pending_permissions: [],
    permissions_added: false,
    authorization: "",
    tools: [],
    capability_status: {},
  })),
});

/** 「用我自己装的」那一份(回归用)。 */
const directoryService = (id: string): Record<string, unknown> => ({
  instance_id: id,
  service: "comfyui",
  title: "ComfyUI",
  mode: "directory",
  directory: `/Users/me/ComfyUI`,
  python: "",
  port: 8189,
  url: "http://127.0.0.1:8189",
  state: "running",
  installed: true,
  can_manage: true,
  needs_rebuild: false,
  install: null,
  shared_models: [],
  listen_lan: false,
  keep_running: false,
  extra_args: [],
  pid: 123,
  started_at: null,
  ready_seconds: null,
  adopted: false,
  restarts: 0,
  error: "",
  failure_lines: [],
  issue: null,
  idle_stop_minutes: 0,
  idle_stopped: false,
});

const running = { current: "0.41.0", source: "running", running: true, reason: "" };

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PluginsView workspaceId="w1" />
    </QueryClientProvider>,
  );
}

const card = (id: string) => document.querySelector<HTMLElement>(`[data-connection="${id}"]`);
/** 连接卡里那一行「版本」(页头那一行没有 id)。 */
const versionRow = (id: string) => document.getElementById(`local-service-version-${id}`);

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  window.localStorage.clear();
  locale = "zh-CN";
  h.packages = [];
  h.services = {};
  h.toast.success.mockReset();
  h.toast.error.mockReset();
  h.versions.mockReset();
  h.version.mockReset();
  h.local.mockReset();
  h.local.mockImplementation(async (id: string) => h.services[id] ?? null);
});

afterEach(cleanup);

describe("「连一台服务器」连接卡上的版本", () => {
  it("展开的连接卡有一行版本:显示远端自己报的版本;页头和卡片共用一次探测", async () => {
    h.packages = [PKG(["c1"])];
    h.version.mockResolvedValue(running);
    show();

    const expected = messages["zh-CN"].localServiceVersionRemoteRunning.replace("{version}", "0.41.0");
    await waitFor(() => expect(versionRow("c1")?.textContent).toContain(expected));
    expect(card("c1")?.textContent).toContain("在哪跑");
    expect(card("c1")?.textContent).toContain("服务器地址");
    expect(h.version, "页头那一行和连接卡读的是同一个 query key:只探一次").toHaveBeenCalledTimes(1);
    expect(h.version).toHaveBeenCalledWith("c1");
  });

  it("连不上 / 超时:只有版本这一行说连不上,连接卡其它内容照常、不报错", async () => {
    h.packages = [PKG(["c1"])];
    h.version.mockResolvedValue({ current: "", source: "", running: false, reason: "unreachable" });
    show();

    await waitFor(() =>
      expect(versionRow("c1")?.textContent).toContain(messages["zh-CN"].localServiceVersionRemoteUnreachable));
    const body = card("c1")!;
    expect(body.textContent).toContain("在哪跑");
    expect(body.textContent).toContain("服务器地址");
    expect(within(body).queryByRole("alert"), "降级,不把整张连接卡变成错误").toBeNull();
    expect(h.version).toHaveBeenCalledTimes(1);
  });

  it("在跑但没报版本:说清它没报版本,不猜一个", async () => {
    h.packages = [PKG(["c1"])];
    h.version.mockResolvedValue({ current: "", source: "", running: true, reason: "no_version" });
    show();

    await waitFor(() =>
      expect(versionRow("c1")?.textContent).toContain(messages["zh-CN"].localServiceVersionRemoteNoVersion));
    expect(versionRow("c1")?.textContent, "不许猜一个版本号").not.toMatch(/\d+\.\d+/);
  });

  it.each(["zh-CN", "en-US"] as const)("远端不是 Mosael 装的那一份(%s):文案说 Mosael 只连过去", async (one) => {
    locale = one;
    h.packages = [PKG(["c1"])];
    h.version.mockResolvedValue(running);
    show();

    const expected = messages[one].localServiceVersionRemoteRunning.replace("{version}", "0.41.0");
    await waitFor(() => expect(versionRow("c1")?.textContent).toContain(expected));
    //: 远端永远不是 Mosael 装的:别把那句话说回来
    expect(versionRow("c1")?.textContent).not.toContain(one === "zh-CN" ? "Mosael 装的" : "Mosael installed");
  });

  it("「用我自己装的」那一份(回归):仍说不是 Mosael 装的、在跑时用 running 那句,行为不变", async () => {
    h.packages = [PKG(["c1"])];
    h.services.c1 = directoryService("c1");
    h.version.mockResolvedValue(running);
    show();

    const expected = messages["zh-CN"].localServiceVersionOtherRunning.replace("{version}", "0.41.0");
    await waitFor(() => expect(versionRow("c1")?.textContent).toContain(expected));
    expect(h.version).toHaveBeenCalledWith("c1");
    expect(h.versions, "不是让 Mosael 装的那一份:仍不去读安装记录").not.toHaveBeenCalled();
  });

  it("不展开的连接不发探测请求;展开哪张才探哪张,收起再展开不重复探", async () => {
    h.packages = [PKG(["c1", "c2", "c3"])];
    h.version.mockResolvedValue(running);
    show();

    //: 页头挑详情里的第一份(c1)探一次
    await waitFor(() => expect(h.version).toHaveBeenCalledTimes(1));
    expect(h.version).toHaveBeenCalledWith("c1");
    //: 三张连接默认收起:没有哪张卡各自去探
    expect(card("c2")?.querySelector("[aria-expanded='false']")).toBeTruthy();
    expect(h.version).toHaveBeenCalledTimes(1);

    const user = userEvent.setup();
    await user.click(card("c2")!.querySelector("button[aria-expanded]")!);
    await waitFor(() => expect(versionRow("c2")).toBeTruthy());
    await waitFor(() => expect(h.version).toHaveBeenCalledTimes(2));
    expect(h.version.mock.calls.map(([id]) => id)).toEqual(["c1", "c2"]);

    //: 收起再展开:同一个 query key + staleTime,不再探
    await user.click(card("c2")!.querySelector("button[aria-expanded]")!);
    await user.click(card("c2")!.querySelector("button[aria-expanded]")!);
    await waitFor(() => expect(versionRow("c2")).toBeTruthy());
    expect(h.version).toHaveBeenCalledTimes(2);
  });
});
