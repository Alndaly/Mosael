/** @vitest-environment jsdom */

/**
 * **插件页上也能看到 ComfyUI 的版本**(维护者:「ComfyUI 插件内可以看 ComfyUI 的版本」)。
 *
 * 版本数据早就有(`GET …/local-service/versions`),但此前只有把连接展开、翻到本机服务那一块才看得见;
 * 插件页本身(页头、详情)什么也没说。这里钉住的是**页头那一行轻量版本**:
 *
 * - 当前版本 + 有新版本时指出来;
 * - 不是 Mosael 装的那一份(current 读不到)时说清楚,不留空白、不写 0;
 * - 上游查不到(离线 / 限流 / 404)时只说查不到(原因),**绝不说「已经是最新的」**;
 * - 页头只问**一次**版本 —— 插件列表里每张卡、每个连接各问一次会变慢变吵(ADR 0073 记着的那次网络调用)。
 *
 * 连接页上那一整行(更新 / 回到上一版 / 发布说明 / 先确认)仍在,由 LocalServiceVersion.dom.test 盯着;
 * 这里只钉插件页上那一眼能看见的摘要。
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
  local: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

//: 详情那一栏要的接口很多,这里只关心版本那一行:认得的几个给真数据,其余一律回空(和
//: PluginsView.scan.dom.test 同一个写法)。
vi.mock("@/api/client", () => {
  const known: Record<string, unknown> = {
    listPluginPackages: async () => h.packages,
    listPluginMarket: async () => ({ plugins: [], index_error: "" }),
    pluginDir: async () => ({ path: "/plugins" }),
    rescanPlugins: async () => [],
    getLocalService: (id: string) => h.local(id),
    getLocalServiceVersions: (id: string) => h.versions(id),
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

import type { LocalServiceVersions } from "@/api/client";
import { messages } from "@/app/messages";
import { PluginsView } from "./PluginsView";

const PKG = (id: string, connections: string[]) => ({
  id,
  name: `插件 ${id}`,
  version: "1.12.4",
  kind: "process",
  multiple: true,
  permissions: [],
  provides: ["generation"],
  config_fields: [],
  credential_fields: [],
  services: [{ key: "comfyui", title: "ComfyUI", tool: "comfyui_generation" }],
  instances: connections.map((connectionId) => ({
    id: connectionId,
    package_id: id,
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

const service = (id: string, overrides: Record<string, unknown> = {}) => ({
  instance_id: id,
  service: "comfyui",
  title: "ComfyUI",
  mode: "managed",
  directory: `/data/local-services/${id}`,
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
  pid: null,
  started_at: null,
  ready_seconds: null,
  adopted: false,
  restarts: 0,
  error: "",
  failure_lines: [],
  issue: null,
  idle_stop_minutes: 0,
  idle_stopped: false,
  ...overrides,
});

const versions = (overrides: Record<string, unknown> = {}): LocalServiceVersions => ({
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
    notes: "",
    url: "https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.41.0",
    checked_at: "2026-10-15T22:57:45Z",
    message: "",
  },
  ...overrides,
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PluginsView workspaceId="w1" />
    </QueryClientProvider>,
  );
}

/** 页头那条事实行(版本 / 作者 / 调用方补的几条都在里面)。 */
const facts = () => document.querySelector<HTMLElement>("[data-plugin-facts]")!;
/** 插件页上**新增**的那一行版本;连接页上那一整行不在这里。 */
const versionFact = () => document.querySelector<HTMLElement>("[data-service-version]");

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
  h.local.mockReset();
  h.local.mockImplementation(async (id: string) => h.services[id] ?? null);
});

afterEach(cleanup);

describe("插件页上的 ComfyUI 版本", () => {
  it("页头显示装着的那一版和新版本;点新版本那颗跳到连接里那一行", async () => {
    h.packages = [PKG("dev.mosael.comfyui", ["c1", "c2"])];
    h.services.c1 = service("c1");
    h.services.c2 = service("c2");
    h.versions.mockResolvedValue(versions());
    show();

    await waitFor(() => expect(facts().textContent).toContain("0.39.0"));
    expect(versionFact()?.textContent).toContain("有新版本 0.41.0");
    expect(within(facts()).getByRole("button", { name: "有新版本 0.41.0" })).toBeTruthy();

    //: 点它:展开第一个连接,滚到「版本」那一行(更新、回到上一版都在那里)
    const user = userEvent.setup();
    await user.click(within(facts()).getByRole("button", { name: "有新版本 0.41.0" }));
    await waitFor(() => {
      const card = document.querySelector<HTMLElement>("[data-connection='c1']");
      expect(card?.querySelector("[aria-expanded]")?.getAttribute("aria-expanded")).toBe("true");
    });
    await waitFor(() =>
      expect(vi.mocked(Element.prototype.scrollIntoView).mock.contexts).toContain(document.getElementById("local-service-version-c1")),
    );
  });

  it("不是 Mosael 装的那一份(用我自己装的):说版本读不到,不去问版本", async () => {
    h.packages = [PKG("dev.mosael.comfyui", ["c1"])];
    h.services.c1 = service("c1", { mode: "directory" });
    show();

    await waitFor(() => expect(versionFact()).toBeTruthy());
    expect(versionFact()?.textContent).toBe(messages["zh-CN"].pluginServiceVersionNotManaged);
    expect(h.versions, "不是让 Mosael 装的那一份,没有版本接口可问").not.toHaveBeenCalled();
  });

  it.each(["zh-CN", "en-US"] as const)("装着的这一份读不到当前版本(current 为空,%s):说明不是 Mosael 装的这一份", async (one) => {
    locale = one;
    h.packages = [PKG("dev.mosael.comfyui", ["c1"])];
    h.services.c1 = service("c1");
    h.versions.mockResolvedValue(versions({ current: "", latest: "", update: "", source: "", upstream: { status: "not_checked", version: "", tag: "", notes: "", url: "", checked_at: "", message: "" } }));
    show();

    await waitFor(() => expect(versionFact()).toBeTruthy());
    expect(versionFact()?.textContent).toBe(messages[one].pluginServiceVersionNotManaged);
  });

  it("上游查不到(离线):说查不到和原因,不说「已经是最新的」", async () => {
    h.packages = [PKG("dev.mosael.comfyui", ["c1"])];
    h.services.c1 = service("c1");
    h.versions.mockResolvedValue(versions({
      latest: "",
      update: "",
      source: "",
      upstream: { status: "offline", version: "", tag: "", notes: "", url: "", checked_at: "", message: "离线" },
    }));
    show();

    await waitFor(() => expect(versionFact()?.textContent).toContain("查不到（离线）"));
    expect(versionFact()?.textContent).not.toContain("已经是最新的");
    expect(versionFact()?.textContent).not.toContain(messages["zh-CN"].localServiceVersionLatest.slice(0, 4));
  });

  it("插件列表打开时版本只问一次(选中的详情那一份),不是每个插件、每个连接各问一次", async () => {
    //: 选中的那个插件有三个连接(默认收起),列表里另外还有两个插件 —— 各问一次的话是 5 次。
    h.packages = [
      PKG("dev.a", ["a1", "a2", "a3"]),
      PKG("dev.b", ["b1"]),
      PKG("dev.c", ["c1"]),
    ];
    for (const id of ["a1", "a2", "a3", "b1", "c1"]) h.services[id] = service(id);
    h.versions.mockResolvedValue(versions());
    show();

    await waitFor(() => expect(h.versions).toHaveBeenCalled());
    expect(h.versions.mock.calls.length, "上游查询只给详情里那一份,不给每张卡各来一次").toBe(1);
    //: 本机服务那一层(便宜、不联网)每个连接读一次 —— 只有它知道这一份是不是 Mosael 装的
    expect(h.local.mock.calls.length).toBeGreaterThanOrEqual(3);
    //: 列表、详情都落定(版本那一行画出来了)之后仍然是那一次:没有别的卡在后面补问
    await waitFor(() => expect(facts().textContent).toContain("0.39.0"));
    expect(h.versions).toHaveBeenCalledTimes(1);
  });
});
