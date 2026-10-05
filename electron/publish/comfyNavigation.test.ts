import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

import { NAVIGATION_KEYS, NAVIGATION_SETTING, navigationScript, settingsWriteVerdict } from "./comfyNavigation";

const ORIGIN = "http://192.168.3.15:8188";

/**
 * 一页假的 ComfyUI 前端,只有脚本碰得到的那一样:设置仓库(`extensionManager.setting`)。和 1.53.10 的前端一样,`set` 先在本地
 * 换好值、再写回服务器 —— 写回被主进程拦下时 `set` 报错,本地的值已经换了。
 */
function settingsPage(origin: string, opts: { options?: unknown[] | null; value?: string; persist?: "ok" | "blocked" } = {}) {
  const values: Record<string, unknown> = { [NAVIGATION_SETTING]: opts.value ?? "legacy" };
  const settings = opts.options === null ? {} : {
    [NAVIGATION_SETTING]: {
      id: NAVIGATION_SETTING,
      options: opts.options ?? [{ value: "standard", text: "Standard (New)" }, { value: "legacy", text: "Drag Navigation" },
                                { value: "custom", text: "Custom" }],
    },
  };
  const set = vi.fn(async (key: string, value: unknown) => {
    values[key] = value;
    if (opts.persist === "blocked") throw new TypeError("Failed to fetch");
  });
  const setting = { settings, get: (key: string) => values[key], set };
  const context = vm.createContext({ window: { app: { extensionManager: { setting } } }, location: { origin } });
  return { set, values, run: (script: string) => vm.runInContext(script, context) as Promise<unknown> };
}

describe("操控方式的脚本", () => {
  it("触控板 = standard、鼠标 = legacy,经前端自己的设置仓库设", async () => {
    const page = settingsPage(ORIGIN);
    await expect(page.run(navigationScript(ORIGIN, "trackpad"))).resolves.toBe("applied");
    expect(page.set).toHaveBeenCalledExactlyOnceWith(NAVIGATION_SETTING, "standard");
    await expect(page.run(navigationScript(ORIGIN, "mouse"))).resolves.toBe("applied");
    expect(page.values[NAVIGATION_SETTING]).toBe("legacy");
  });

  it("已经是要的那个就不再设(不发写回)", async () => {
    const page = settingsPage(ORIGIN, { value: "standard" });
    await expect(page.run(navigationScript(ORIGIN, "trackpad"))).resolves.toBe("applied");
    expect(page.set).not.toHaveBeenCalled();
  });

  it("写回服务器被主进程拦下(set 报错):本地已经换好,照样算设好了", async () => {
    const page = settingsPage(ORIGIN, { persist: "blocked" });
    await expect(page.run(navigationScript(ORIGIN, "trackpad"))).resolves.toBe("applied");
    expect(page.values[NAVIGATION_SETTING]).toBe("standard");
  });

  it("这版前端没有这个设置、或者没有这一项可选值、或者没有设置仓库:什么都不做,说不支持", async () => {
    const missing = settingsPage(ORIGIN, { options: null });
    await expect(missing.run(navigationScript(ORIGIN, "trackpad"))).resolves.toBe("unsupported");
    expect(missing.set).not.toHaveBeenCalled();
    const older = settingsPage(ORIGIN, { options: ["legacy", "custom"] });
    await expect(older.run(navigationScript(ORIGIN, "trackpad"))).resolves.toBe("unsupported");
    const bare = vm.createContext({ window: { app: { extensionManager: {} } }, location: { origin: ORIGIN } });
    await expect(vm.runInContext(navigationScript(ORIGIN, "mouse"), bare)).resolves.toBe("unsupported");
  });

  it("视图停在别的站点上就什么都不做;来源经 JSON 编码,带引号也只是一个对不上的字符串", async () => {
    const page = settingsPage("https://example.com");
    await expect(page.run(navigationScript(ORIGIN, "trackpad"))).resolves.toBe("elsewhere");
    await expect(page.run(navigationScript('x"); window.app = null; ("', "trackpad"))).resolves.toBe("elsewhere");
    expect(page.set).not.toHaveBeenCalled();
  });
});

describe("设置写回的闸", () => {
  const post = (url: string, body?: unknown) =>
    settingsWriteVerdict({ method: "POST", url, body: body === undefined ? null : JSON.stringify(body) });

  it("一个键的写回:操控方式和它联动的两个拦下,别的设置照常写", () => {
    for (const key of NAVIGATION_KEYS) {
      expect(post(`${ORIGIN}/api/settings/${encodeURIComponent(key)}`, "standard"), key).toEqual({ action: "block" });
    }
    expect(post(`${ORIGIN}/api/settings/Comfy.ColorPalette`, "dark")).toEqual({ action: "allow" });
    expect(post(`${ORIGIN}/api/settings/${encodeURIComponent("Comfy.Canvas.NavigationModeX")}`, "x")).toEqual({ action: "allow" });
  });

  it("批量写回:全是那几个键就拦;混着别的键就拦下、补发剩下的;一个都没有就放行", () => {
    expect(post(`${ORIGIN}/api/settings`, {
      "Comfy.Canvas.LeftMouseClickBehavior": "select", "Comfy.Canvas.MouseWheelScroll": "panning",
    })).toEqual({ action: "block" });
    expect(post(`${ORIGIN}/api/settings`, { "Comfy.Canvas.MouseWheelScroll": "panning", "Comfy.Queue.QPOV2": false }))
      .toEqual({ action: "reissue", body: JSON.stringify({ "Comfy.Queue.QPOV2": false }) });
    expect(post(`${ORIGIN}/api/settings`, { "Comfy.Queue.QPOV2": false })).toEqual({ action: "allow" });
  });

  it("读放行;不是设置那条路放行;读不出 body 放行", () => {
    expect(settingsWriteVerdict({ method: "GET", url: `${ORIGIN}/api/settings/${NAVIGATION_SETTING}` })).toEqual({ action: "allow" });
    expect(post(`${ORIGIN}/api/userdata/workflows%2Fa.json`, { nodes: [] })).toEqual({ action: "allow" });
    expect(post(`${ORIGIN}/api/settingsx/${NAVIGATION_SETTING}`, "x")).toEqual({ action: "allow" });
    expect(settingsWriteVerdict({ method: "POST", url: `${ORIGIN}/api/settings`, body: "not json" })).toEqual({ action: "allow" });
    expect(post(`${ORIGIN}/api/settings`, ["Comfy.Canvas.NavigationMode"])).toEqual({ action: "allow" });
  });

  it("ComfyUI 挂在子路径下(反向代理)也认得;PUT 一样算写", () => {
    expect(post(`https://lab.example.com/comfy/api/settings/${NAVIGATION_SETTING}`, "standard")).toEqual({ action: "block" });
    expect(settingsWriteVerdict({ method: "PUT", url: `${ORIGIN}/api/settings/${NAVIGATION_SETTING}`, body: '"x"' }))
      .toEqual({ action: "block" });
  });
});
