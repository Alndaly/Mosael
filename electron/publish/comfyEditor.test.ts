import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

import { comfyOpenWorkflowScript, comfyReady, openWorkflowInPage } from "./comfyEditor";

const ORIGIN = "http://192.168.3.15:8188";

interface FakeWorkflow {
  isLoaded: boolean;
  activeState: unknown;
  load: () => Promise<void>;
}

/** 一页假的 ComfyUI 前端:只有脚本碰得到的那几样(工作流仓库、loadGraphData、location)。 */
function comfyPage(origin: string, workflows: Record<string, FakeWorkflow>) {
  const store = {
    syncWorkflows: vi.fn(async () => undefined),
    getWorkflowByPath: vi.fn((path: string) => workflows[path] ?? null),
  };
  const app = { extensionManager: { workflow: store }, loadGraphData: vi.fn(async () => undefined) };
  const context = vm.createContext({ window: { app }, location: { origin } });
  const run = (script: string) => vm.runInContext(script, context) as Promise<unknown>;
  return { store, app, run };
}

function savedWorkflow(isLoaded = false): FakeWorkflow {
  const workflow: FakeWorkflow = {
    isLoaded,
    activeState: { nodes: [{ id: 1, type: "KSampler" }], links: [] },
    load: vi.fn(async () => {
      workflow.isLoaded = true;
    }),
  };
  return workflow;
}

describe("在编辑器里打开一张存着的工作流", () => {
  it("先同步工作流列表,找到 workflows/<路径> 那一张,载入后在画布上打开", async () => {
    const workflow = savedWorkflow();
    const page = comfyPage(ORIGIN, { "workflows/人像/古风 女孩.json": workflow });

    await expect(page.run(comfyOpenWorkflowScript("人像/古风 女孩.json", ORIGIN))).resolves.toBe("opened");

    expect(page.store.syncWorkflows).toHaveBeenCalledBefore(page.store.getWorkflowByPath);
    expect(workflow.load).toHaveBeenCalledOnce();
    const [state, clean, restore, target] = page.app.loadGraphData.mock.calls[0] as unknown[];
    expect(state).toEqual(workflow.activeState);
    expect(state, "交给画布的是一份拷贝,前端自己的那份不被改").not.toBe(workflow.activeState);
    expect([clean, restore, target]).toEqual([true, true, workflow]);
  });

  it("已经开着(可能改过没存)的不重新载入,改动留着", async () => {
    const workflow = savedWorkflow(true);
    const page = comfyPage(ORIGIN, { "workflows/a.json": workflow });

    await expect(page.run(comfyOpenWorkflowScript("a.json", ORIGIN))).resolves.toBe("opened");
    expect(workflow.load).not.toHaveBeenCalled();
  });

  it("那台机器上没有这张(被别处删了 / 改了名)就说没找到,不动画布", async () => {
    const page = comfyPage(ORIGIN, {});

    await expect(page.run(comfyOpenWorkflowScript("gone.json", ORIGIN))).resolves.toBe("missing");
    expect(page.app.loadGraphData).not.toHaveBeenCalled();
  });

  it("视图停在别的站点上就什么都不做", async () => {
    const page = comfyPage("https://example.com", { "workflows/a.json": savedWorkflow() });

    await expect(page.run(comfyOpenWorkflowScript("a.json", ORIGIN))).resolves.toBe("elsewhere");
    expect(page.store.syncWorkflows).not.toHaveBeenCalled();
  });

  it("路径原样当字符串嵌进脚本,带引号也只是名字的一部分", async () => {
    const tricky = 'a"); window.hacked = true; ("b.json';
    const page = comfyPage(ORIGIN, { [`workflows/${tricky}`]: savedWorkflow() });

    await expect(page.run(comfyOpenWorkflowScript(tricky, ORIGIN))).resolves.toBe("opened");
    expect(page.store.getWorkflowByPath).toHaveBeenCalledWith(`workflows/${tricky}`);
  });

  it("就绪的判据:来源对得上、前端的工作流仓库和 loadGraphData 都在", () => {
    const ready = (origin: string, app: unknown) =>
      vm.runInContext(`!!(${comfyReady(ORIGIN)})`, vm.createContext({ window: { app }, location: { origin } }));
    const full = { extensionManager: { workflow: {} }, loadGraphData: () => undefined };

    expect(ready(ORIGIN, full)).toBe(true);
    expect(ready(ORIGIN, undefined), "前端还没起来").toBe(false);
    expect(ready(ORIGIN, { loadGraphData: () => undefined }), "工作区还没装好").toBe(false);
    expect(ready("https://example.com", full), "别的站点").toBe(false);
  });
});

describe("视图里的流程", () => {
  function driver(here: string, ready = true) {
    return {
      evaluate: vi.fn(async (expression: string) => (expression === "location.origin" ? here : "opened")),
      waitForFunction: vi.fn(async () => ready),
      goto: vi.fn(async () => ({ outcome: "loaded" as const })),
    };
  }
  const request = { url: `${ORIGIN}/`, path: "a.json" };

  it("已经停在这台 ComfyUI 上:等前端就绪,跑打开脚本", async () => {
    const page = driver(ORIGIN);

    await expect(openWorkflowInPage(page, request)).resolves.toBe("opened");
    expect(page.goto).not.toHaveBeenCalled();
    expect(page.evaluate).toHaveBeenLastCalledWith(comfyOpenWorkflowScript("a.json", ORIGIN), expect.any(Number));
  });

  it("视图刚建、还在载入(about:blank)就等,不重复导航", async () => {
    const page = driver("null");

    await expect(openWorkflowInPage(page, request)).resolves.toBe("opened");
    expect(page.goto).not.toHaveBeenCalled();
  });

  it("用户在这个视图里点去了别的站点:先回到这台 ComfyUI", async () => {
    const page = driver("https://example.com");

    await openWorkflowInPage(page, request);
    expect(page.goto).toHaveBeenCalledWith(`${ORIGIN}/`);
  });

  it("前端一直没就绪(比如要先登录):说没就绪,不跑脚本", async () => {
    const page = driver(ORIGIN, false);

    await expect(openWorkflowInPage(page, request)).resolves.toBe("notReady");
    expect(page.evaluate).toHaveBeenCalledTimes(1);
  });
});
