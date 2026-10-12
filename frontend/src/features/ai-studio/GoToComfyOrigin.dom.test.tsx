/** @vitest-environment jsdom */

/**
 * 会话列表上那一颗「回到那里」去 ComfyUI 工作台时的**当场反馈**(维护者:「要过阵子才会成功跳转,容易让人误解」)。
 *
 * 两个列表各测一遍(两个分区共用一个 SessionList,但接的那条路不一样):创作分区的「来自别处」(goToOrigin)、
 * 对话分区「对话记录」里家在那台 ComfyUI 上的对话(goHome)—— 维护者说的是后面那一列。
 *
 * 点下去到那一处真出现之间要做好几步(读那台机器的工作流库、探/起它背后的本机服务、亮出内嵌视图、把那一张工作流读进画布),
 * 几秒到一两分钟都有。这一段里 AI Studio 那一页原样停着,所以说话的是**这一行自己**:箭头换成转圈、名字换成「正在启动…」
 * (既有的文案,见 app/messages 的 localServices 两份),真要去起本机服务时再把「第一次启动可能要一两分钟」说全;起了、开完了就收掉;
 * 没成也收掉,原因照旧一条 toast;转着的时候连点只去一次(只叫一次桥)。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const TEXT: Record<string, string> = {
  agentGoHome: "回到那里",
  createGoToOrigin: "回到那里",
  createOriginComfy: "ComfyUI《{name}》",
  localServiceOpenStarting: "正在启动…",
  localServiceStartingNote: "正在启动本机服务,第一次启动可能要一两分钟…",
};
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEXT[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

//: 这一条路上要问的那几样(其余照旧走真的:两个列表自己那一套 fetch 在下面 mock)
const api = vi.hoisted(() => ({
  getWorkflowLibrary: vi.fn(),
  listPluginPackages: vi.fn(),
  getLocalService: vi.fn(),
  ensureLocalService: vi.fn(),
  listAgentSessions: vi.fn(),
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  getWorkflowLibrary: api.getWorkflowLibrary,
  listPluginPackages: api.listPluginPackages,
  getLocalService: api.getLocalService,
  ensureLocalService: api.ensureLocalService,
  listAgentSessions: api.listAgentSessions,
}));

const toasts = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock("sonner", () => ({ toast: toasts }));

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { resetWorkbench } from "@/features/plugins/workbench/workbenchSession";
import { readHint } from "@/test/hint";

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    }),
  });
});

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  resetWorkbench();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:tab:ai-studio", "create");
  api.getWorkflowLibrary.mockReset();
  api.getWorkflowLibrary.mockResolvedValue({
    workflows: [{ path: "人像/古风.json" }], editor: { kind: "comfyui", url: "http://127.0.0.1:8188" },
  });
  api.listPluginPackages.mockReset();
  api.listPluginPackages.mockResolvedValue([{ instances: [{ id: "i1", name: "ComfyUI · 本机" }] }]);
  api.getLocalService.mockReset();
  api.getLocalService.mockResolvedValue({ state: "running" });
  api.ensureLocalService.mockReset();
  api.listAgentSessions.mockReset();
  api.listAgentSessions.mockResolvedValue(AGENT_SESSIONS);
  toasts.error.mockReset();
});

function row(id: string, title: string, origin: Record<string, string> = {}) {
  const at = "2026-10-08T00:00:00Z";
  return {
    id, workspace_id: "w1", title, kind: "image", provider_profile_id: null, model: "", is_mine: true, shared: false,
    origin_kind: "studio", origin_id: "", origin_name: "", origin_state: "ok", ...origin, created_at: at, updated_at: at,
  };
}

/** 一条自己开的、一条在 ComfyUI 里开出来的(后面这条才有「回到那里」)。 */
const SESSIONS = [
  row("s-mine", "海边的灯塔"),
  row("s-comfy", "", { origin_kind: "comfyui", origin_id: "i1/人像/古风.json", origin_name: "人像/古风" }),
];

/** 对话分区那一列(「对话记录」)的一段对话:它的家在那台 ComfyUI 上的一张开出来的工作流。 */
const AGENT_SESSIONS = [{
  id: "a1", workspace_id: "w1", title: "整理素材库", is_mine: true, shared: false,
  home_kind: "comfyui", home_id: "i1/人像/古风.json", home_name: "人像/古风", home_state: "ok",
  created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z",
}];

function renderStudio() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (url.includes("/api/generation/sessions")) return json(SESSIONS);
    return json([]);
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <AiStudio workspace={{ id: "w1", name: "W" } as never} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
}

/** 展开最下面那一摞「来自别处」(当前开着的那条在里面时本来就是展开的),把 ComfyUI 那条的「回到那里」交出来。 */
async function comfyArrow(openComfyWorkbench: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
  renderStudio();
  await screen.findByRole("button", { name: /海边的灯塔/ });
  const aside = document.querySelector("[data-session-aside]") as HTMLElement;
  const toggle = within(aside).getByRole("button", { name: /createFromElsewhere/ });
  if (toggle.getAttribute("aria-expanded") === "false") fireEvent.click(toggle);
  const title = await within(aside).findByRole("button", { name: /ComfyUI《人像\/古风》/ });
  return within(title.closest("[data-session-row]") as HTMLElement).getByRole("button", { name: "回到那里" });
}

/** 对话分区的那一列(「对话记录」):一段家在那台 ComfyUI 上的对话,把它的「回到那里」交出来。 */
async function chatComfyArrow(openComfyWorkbench: ReturnType<typeof vi.fn>) {
  localStorage.setItem("mosael:tab:ai-studio", "chat");
  vi.stubGlobal("mosaelBrowser", { openComfyWorkbench, onComfyWorkbench: () => () => undefined });
  renderStudio();
  const title = await screen.findByRole("button", { name: /整理素材库/ });
  return within(title.closest("[data-session-row]") as HTMLElement).getByRole("button", { name: "回到那里" });
}

describe("「回到那里」去 ComfyUI 工作台:点下去当场就有反馈", () => {
  it("服务停着:当场就是「正在启动…」,起好、开完之前不去开;连点只叫一次桥;成了收掉", async () => {
    //: 服务停着:这一下要等它起好(第一次启动最久)
    api.getLocalService.mockResolvedValue({ state: "stopped" });
    let serviceReady: (value?: unknown) => void = () => undefined;
    api.ensureLocalService.mockReturnValue(new Promise((resolve) => (serviceReady = resolve)));
    let opened: (value: unknown) => void = () => undefined;
    const openComfyWorkbench = vi.fn().mockReturnValue(new Promise((resolve) => (opened = resolve)));

    const arrow = await comfyArrow(openComfyWorkbench);
    const line = arrow.closest("[data-session-row]") as HTMLElement;
    fireEvent.click(arrow);
    //: 连点第二次(落在同一颗上):不去第二次
    fireEvent.click(arrow);

    //: 桥还没被叫(服务还在起),界面上已经在说「正在启动…」了
    const spinning = await screen.findByRole("button", { name: "正在启动…" });
    expect(spinning).toHaveAttribute("aria-busy", "true");
    expect(openComfyWorkbench, "等它起好再开").not.toHaveBeenCalled();
    expect(api.ensureLocalService).toHaveBeenCalledTimes(1);
    //: 真要去起本机服务了:这一颗点不了的原因里把「第一次启动可能要一两分钟」说全(onStarting 一路传到了这一行;
    //: 点不了的按钮的说明挂在外面那层壳上,见 Hint)
    await waitFor(() => expect(line.querySelector("[data-hint-disabled]")).toBeTruthy());
    expect(await readHint(within(line).getByRole("button", { name: "正在启动…" })))
      .toContain("正在启动本机服务,第一次启动可能要一两分钟…");

    serviceReady({ state: "running" });
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledTimes(1));
    //: 桥的 promise 还没 resolve:圈还转着(不写百分比,只说正在)
    const stillOpening = screen.getByRole("button", { name: "正在启动…" });
    expect(stillOpening).toHaveAttribute("aria-busy", "true");

    opened({ ok: true, outcome: "opened" });
    //: 成了:这一行恢复原样(箭头、名字都回来了)
    await waitFor(() => expect(screen.getByRole("button", { name: "回到那里" })).not.toHaveAttribute("aria-busy"));
    expect(screen.queryByRole("button", { name: "正在启动…" })).toBeNull();
    expect(toasts.error).not.toHaveBeenCalled();
  });

  it("服务已经在跑:桥没回话之前箭头就转着,回来了就收掉", async () => {
    let opened: (value: unknown) => void = () => undefined;
    const openComfyWorkbench = vi.fn().mockReturnValue(new Promise((resolve) => (opened = resolve)));

    const arrow = await comfyArrow(openComfyWorkbench);
    fireEvent.click(arrow);

    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledTimes(1));
    expect(api.ensureLocalService, "已经在跑就不去起它").not.toHaveBeenCalled();
    //: 还没跳过去:界面上已经转着、说着「正在启动…」
    expect(screen.getByRole("button", { name: "正在启动…" })).toHaveAttribute("aria-busy", "true");

    opened({ ok: true, outcome: "opened" });
    await waitFor(() => expect(screen.getByRole("button", { name: "回到那里" })).not.toHaveAttribute("aria-busy"));
  });

  it("没开成:圈收掉、恢复原样,原因只用一条 toast 说,还能再去", async () => {
    let failed: (value: unknown) => void = () => undefined;
    const openComfyWorkbench = vi.fn().mockReturnValue(new Promise((resolve) => (failed = resolve)));

    const arrow = await comfyArrow(openComfyWorkbench);
    fireEvent.click(arrow);
    expect(await screen.findByRole("button", { name: "正在启动…" })).toHaveAttribute("aria-busy", "true");

    failed({ ok: false, error: "前台正被另一个页面占着" });

    await waitFor(() => expect(toasts.error).toHaveBeenCalledTimes(1));
    expect(toasts.error).toHaveBeenCalledWith("前台正被另一个页面占着");
    //: 不留一个转不完的圈:还是原来那颗「回到那里」
    await waitFor(() => expect(screen.getByRole("button", { name: "回到那里" })).not.toHaveAttribute("aria-busy"));
    expect(screen.queryByRole("button", { name: "正在启动…" })).toBeNull();
    //: 再点一次照旧能去(没有被卡住)
    fireEvent.click(screen.getByRole("button", { name: "回到那里" }));
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledTimes(2));
  });
});

describe("「对话记录」里那些家在那台 ComfyUI 上的对话:同一颗箭头,一样当场说话", () => {
  it("点下去当场是「正在启动…」,起好了才去开,开完了收掉", async () => {
    api.getLocalService.mockResolvedValue({ state: "stopped" });
    let serviceReady: (value?: unknown) => void = () => undefined;
    api.ensureLocalService.mockReturnValue(new Promise((resolve) => (serviceReady = resolve)));
    let opened: (value: unknown) => void = () => undefined;
    const openComfyWorkbench = vi.fn().mockReturnValue(new Promise((resolve) => (opened = resolve)));

    const arrow = await chatComfyArrow(openComfyWorkbench);
    fireEvent.click(arrow);

    expect(await screen.findByRole("button", { name: "正在启动…" })).toHaveAttribute("aria-busy", "true");
    expect(openComfyWorkbench, "等它起好再开").not.toHaveBeenCalled();

    serviceReady({ state: "running" });
    await waitFor(() => expect(openComfyWorkbench).toHaveBeenCalledTimes(1));
    //: 桥还没回话:圈还在
    expect(screen.getByRole("button", { name: "正在启动…" })).toHaveAttribute("aria-busy", "true");

    opened({ ok: true, outcome: "opened" });
    await waitFor(() => expect(screen.getByRole("button", { name: "回到那里" })).not.toHaveAttribute("aria-busy"));
    expect(toasts.error).not.toHaveBeenCalled();
  });
});
