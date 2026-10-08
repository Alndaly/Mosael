/**
 * 原生视图亮着时,渲染层必须画着和它配套的那一圈:工作台是顶栏加右边那一列,普通网页是内嵌浏览器的顶栏。
 *
 * 主窗口换了一份文档(重新加载、HMR 整页刷新、出错后「重新加载」、渲染进程崩了),工作台那一页 —— 开的是哪个连接、在哪个
 * 工作区、哪个页签 —— 是渲染层自己的状态,新的那一份里没有、认领不了它的 ComfyUI 视图;留着就是维护者截图里那块没有顶栏、
 * 没有那一列的画布。所以主进程在换文档时收起工作台的视图、停掉工作台会话(智能体的 comfy_* 工具随之说「先在工作台里打开」);
 * 普通网页留着,它的顶栏照补播的视图状态画得回来。
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const driver = {
    evaluate: vi.fn(async (script: string) =>
      script.includes("bridge.readGraph") ? { ok: true, graph: { workflow: { nodes: [] }, selection: [], modified: false } } : null),
  };
  const views = {
    visibleAccountId: null as string | null,
    attachWindow: vi.fn(),
    focusTarget: () => null,
    openView: vi.fn(async ({ viewId }: { viewId: string }) => {
      views.visibleAccountId = viewId;
    }),
    hide: vi.fn(() => {
      views.visibleAccountId = null;
    }),
    existingDriver: vi.fn(() => driver),
  };
  return { views, driver };
});
vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));
vi.mock("./accountViews", () => ({ createSharedViews: () => mocks.views, destroySharedViews: vi.fn() }));
vi.mock("./floatLayer", () => ({ FloatLayer: class { warm() {} hide() {} destroy() {} } }));
vi.mock("./comfyViews", () => ({ comfyViewOpening: vi.fn(), comfyViewShown: vi.fn(), setComfyNavigation: vi.fn() }));
vi.mock("./comfyEditor", () => ({ comfyReady: () => "true", openWorkflowInPage: vi.fn(), newWorkflowInPage: vi.fn() }));
vi.mock("./adapters", () => ({ createAdapter: vi.fn() }));
vi.mock("./log", () => ({ plog: vi.fn() }));
vi.mock("./publishBackend", () => ({
  markDue: vi.fn(async () => {}), heartbeat: vi.fn(async () => {}), claimTask: vi.fn(async () => ({ task: null })),
  claimCheck: vi.fn(async () => ({ account: null })),
}));

import {
  comfyWorkbenchCall,
  openComfyWorkbench,
  openPoolLogin,
  releaseWorkbenchView,
  startPublishWorker,
  stopPublishWorker,
} from "./publishWorker";

const PARTITION = "persist:pool-comfyui-c1";

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  mocks.views.visibleAccountId = null;
  // 主窗口:开着、看得见(工作台在窗口藏起来时会暂停轮询,见 comfyWorkbenchSessions 的 paused)。
  startPublishWorker({ window: { isDestroyed: () => false, isVisible: () => true, isMinimized: () => false } as never });
});
afterEach(() => {
  stopPublishWorker();
  vi.clearAllTimers();
  vi.useRealTimers();
});

it("工作台开着、主窗口换了一份文档:收起那个 ComfyUI 视图、停掉工作台会话 —— 不留一块没有顶栏和那一列的画布", async () => {
  await openComfyWorkbench({ partition: PARTITION, url: "http://127.0.0.1:28188", name: "ComfyUI", path: null, fresh: false });
  expect(mocks.views.visibleAccountId).toBe(PARTITION);
  expect((await comfyWorkbenchCall({ partition: PARTITION, call: { op: "readGraph" } })).ok, "工作台会话在").toBe(true);

  releaseWorkbenchView();
  expect(mocks.views.hide).toHaveBeenCalledTimes(1);
  expect(mocks.views.visibleAccountId).toBeNull();
  expect(await comfyWorkbenchCall({ partition: PARTITION, call: { op: "readGraph" } }), "会话停了:桥不再接活")
    .toEqual({ ok: false, error: "closed" });
});

it("前台是普通网页(没有工作台会话):留着,它的顶栏照补播的状态画得回来 —— 当普通网页打开的 ComfyUI 连接也一样", async () => {
  await openPoolLogin({ partition: "persist:pool-profile-p1", url: "https://example.com", name: "档案" });
  releaseWorkbenchView();
  expect(mocks.views.hide).not.toHaveBeenCalled();

  mocks.views.visibleAccountId = null;
  await openPoolLogin({ partition: PARTITION, url: "http://127.0.0.1:28188", name: "ComfyUI" });
  releaseWorkbenchView();
  expect(mocks.views.hide).not.toHaveBeenCalled();
  expect(mocks.views.visibleAccountId).toBe(PARTITION);
});

it("什么都没亮着:什么都不做", () => {
  releaseWorkbenchView();
  expect(mocks.views.hide).not.toHaveBeenCalled();
});
