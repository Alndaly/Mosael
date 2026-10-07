import { describe, expect, it, vi } from "vitest";

import { WORKBENCH_VERSION, workbenchCallScript, workbenchInstallScript, workbenchPollScript } from "./comfyWorkbench";
import { POLL_MS, WorkbenchSessions } from "./comfyWorkbenchSessions";

const ORIGIN = "http://192.168.3.15:8188";
const PARTITION = "persist:pool-comfyui-c1";

const answer = (overrides: Record<string, unknown> = {}) => ({
  version: WORKBENCH_VERSION,
  capabilities: { selection: true, setWidget: true, refreshCombos: true, export: true, dirty: true, save: true, events: true,
                  marks: true },
  workflow: { path: "workflows/a.json", name: "a", temporary: false, modified: false },
  selection: { count: 0, node: null },
  clientId: "abc",
  events: [],
  ...overrides,
});

/** 一个手动推进的时钟 + 一个按脚本回答的假驱动。 */
function harness(replies: (script: string) => unknown) {
  const queued: (() => void)[] = [];
  const driver = { evaluate: vi.fn(async (script: string) => replies(script)) };
  let visible = true;
  const emit = vi.fn();
  const sessions = new WorkbenchSessions({
    driver: () => driver,
    visible: () => visible,
    emit,
    schedule: (callback, ms) => {
      expect(ms).toBe(POLL_MS);
      queued.push(callback);
      return 0 as unknown as ReturnType<typeof setTimeout>;
    },
  });
  const tick = async () => {
    queued.shift()?.();
    await vi.waitFor(() => expect(queued.length).toBeGreaterThan(0), { timeout: 200 }).catch(() => undefined);
  };
  return { sessions, driver, emit, tick, hide: () => (visible = false), queued };
}

describe("工作台会话(主进程这一侧)", () => {
  it("开了就轮询,大约每 300ms 一次;内容没变、也没有新事件就不发", async () => {
    let state = answer();
    const h = harness((script) => (script === workbenchPollScript(ORIGIN) ? state : true));
    h.sessions.start(PARTITION, ORIGIN);
    await vi.waitFor(() => expect(h.emit).toHaveBeenCalledTimes(1));
    expect(h.emit.mock.calls[0][1].workflow).toEqual({ path: "a.json", name: "a", temporary: false, modified: false,
                                                      key: "workflows/a.json", revision: 0 });
    await h.tick();
    expect(h.emit, "一模一样就不再发").toHaveBeenCalledTimes(1);
    state = answer({ workflow: { path: "workflows/a.json", name: "a", temporary: false, modified: true } });
    await h.tick();
    expect(h.emit).toHaveBeenCalledTimes(2);
    state = answer({ workflow: { path: "workflows/a.json", name: "a", temporary: false, modified: true },
                     events: [{ type: "executing", at: 1, promptId: "p1", node: "3" }] });
    await h.tick();
    expect(h.emit, "有新事件就发").toHaveBeenCalledTimes(3);
  });

  it("桥不在(页面刚载入、刷新过)就重新注入;前端没就绪就不注入,等下一拍", async () => {
    let ready = false;
    const h = harness((script) => {
      if (script === workbenchPollScript(ORIGIN)) return { error: "missing" };
      if (script.startsWith("!!(")) return ready;
      return "installed";
    });
    h.sessions.start(PARTITION, ORIGIN);
    await vi.waitFor(() => expect(h.queued.length).toBe(1));
    expect(h.driver.evaluate.mock.calls.map(([script]) => script)).not.toContain(workbenchInstallScript(ORIGIN));
    ready = true;
    await h.tick();
    await vi.waitFor(() => expect(h.driver.evaluate.mock.calls.map(([script]) => script)).toContain(workbenchInstallScript(ORIGIN)));
    expect(h.emit).not.toHaveBeenCalled();
  });

  it("视图收起就停,告诉渲染层会话结束了;之后的调用不做", async () => {
    const h = harness(() => answer());
    h.sessions.start(PARTITION, ORIGIN);
    await vi.waitFor(() => expect(h.emit).toHaveBeenCalledTimes(1));
    h.hide();
    await h.tick();
    expect(h.emit).toHaveBeenLastCalledWith(PARTITION, null);
    expect(h.sessions.active(PARTITION)).toBe(false);
    await expect(h.sessions.call(PARTITION, { op: "save" })).resolves.toEqual({ ok: false, error: "closed" });
  });

  it("面板要做的事:按会话的来源拼写死的调用脚本,回答规整过", async () => {
    const h = harness((script) => (script === workbenchPollScript(ORIGIN) ? answer() : { ok: true, value: "b.safetensors" }));
    h.sessions.start(PARTITION, ORIGIN);
    const one = { op: "setWidget", node: "4", widget: "ckpt_name", value: "b.safetensors" } as const;
    await expect(h.sessions.call(PARTITION, one)).resolves.toEqual({ ok: true, value: "b.safetensors" });
    expect(h.driver.evaluate).toHaveBeenCalledWith(workbenchCallScript(ORIGIN, one), expect.any(Number));
    h.driver.evaluate.mockRejectedValueOnce(new Error("page went away"));
    await expect(h.sessions.call(PARTITION, { op: "export" })).resolves.toEqual({ ok: false, error: "failed", message: "page went away" });
  });

  it("同一张换了地方:内容一样也发,只发一次(ADR 0044 §9)", async () => {
    const moved = { from: { path: "workflows/Unsaved Workflow.json", name: "Unsaved Workflow", temporary: true },
                    to: { path: "workflows/a.json", name: "a", temporary: false } };
    let state = answer();
    const h = harness((script) => (script === workbenchPollScript(ORIGIN) ? state : true));
    h.sessions.start(PARTITION, ORIGIN);
    await vi.waitFor(() => expect(h.emit).toHaveBeenCalledTimes(1));
    expect(h.emit.mock.calls[0][1]).toMatchObject({ renames: [], openedBy: null });
    state = answer({ renames: [moved] });
    await h.tick();
    expect(h.emit).toHaveBeenCalledTimes(2);
    expect(h.emit.mock.calls[1][1].renames).toEqual([{
      from: { path: "", name: "Unsaved Workflow", temporary: true, key: "workflows/Unsaved Workflow.json" },
      to: { path: "a.json", name: "a", temporary: false, key: "workflows/a.json" },
    }]);
    state = answer();
    await h.tick();
    expect(h.emit, "桥那边已经取走了,下一拍没有就不再发").toHaveBeenCalledTimes(2);
  });

  it("智能体开的新标签页:是哪段对话开的不进页面,开好之后随下一次状态报一次(ADR 0044 §6)", async () => {
    const opened = { path: "workflows/Qwen 编辑.json", name: "Qwen 编辑", temporary: true };
    const h = harness((script) => (script === workbenchPollScript(ORIGIN) ? answer() : { ok: true, workflow: opened, created: {} }));
    h.sessions.start(PARTITION, ORIGIN);
    await vi.waitFor(() => expect(h.emit).toHaveBeenCalledTimes(1));
    const call = { op: "openWorkflow", graph: { nodes: [] }, name: "Qwen 编辑", path: null, ops: [], openedBy: "s1" } as const;
    await expect(h.sessions.call(PARTITION, call)).resolves.toMatchObject({ ok: true, workflow: opened });
    const scripts = h.driver.evaluate.mock.calls.map(([script]) => script as string);
    const { openedBy: _, ...pageCall } = call;
    expect(scripts).toContain(workbenchCallScript(ORIGIN, pageCall));
    expect(scripts.some((script) => script.includes("openedBy") || script.includes('"s1"')), "会话 id 不进页面").toBe(false);
    await h.tick();
    expect(h.emit, "内容一样也发").toHaveBeenCalledTimes(2);
    expect(h.emit.mock.calls[1][1].openedBy).toEqual({
      sessionId: "s1", workflow: { path: "", name: "Qwen 编辑", temporary: true, key: "workflows/Qwen 编辑.json" },
    });
    await h.tick();
    expect(h.emit, "只报一次").toHaveBeenCalledTimes(2);
    await h.sessions.call(PARTITION, { ...call, openedBy: undefined });
    await h.tick();
    expect(h.emit, "不是智能体开的:没什么要报").toHaveBeenCalledTimes(2);
  });
});
