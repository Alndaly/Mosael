/**
 * 让位声明(P2):多个浮层同时要求让位时,谁都不该被另一个「顶掉」;拆开也只撤自己那一条。
 */
import { describe, expect, it } from "vitest";

// CommonJS is intentional: publishWorker 加载的是同一份。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createHostLayers } = require("./hostLayers.cjs") as {
  createHostLayers: () => {
    set: (id: string, claim: { kind: string; active: boolean; width?: number }) => {
      reasons: string[];
      panelsHidden: boolean;
      insetRight: number;
    };
    clear: (id: string) => { reasons: string[]; panelsHidden: boolean; insetRight: number };
    size: () => number;
  };
};

describe("让位声明", () => {
  it("同时开着的浮层各自生效:看大图(overlay)+ 页面列表变形(cover)都要让开", () => {
    const layers = createHostLayers();
    layers.set("preview", { kind: "overlay", active: true });
    const after = layers.set("page-list", { kind: "cover", active: true });
    expect(after.reasons.sort()).toEqual(["cover", "overlay"]);
  });

  it("撤掉一个不影响另一个(这是「谁都不被顶掉」的反面案例)", () => {
    const layers = createHostLayers();
    layers.set("preview", { kind: "overlay", active: true });
    layers.set("page-list", { kind: "cover", active: true });
    const after = layers.clear("preview");
    expect(after.reasons).toEqual(["cover"]);
  });

  it("同一个 id 关掉 = 不再让位;后写的声明覆盖前一条", () => {
    const layers = createHostLayers();
    layers.set("modals", { kind: "panels", active: true });
    expect(layers.directives().panelsHidden).toBe(true);
    layers.set("modals", { kind: "panels", active: false });
    expect(layers.directives().panelsHidden).toBe(false);
  });

  it("右侧让位取最大的那一条;不认识的让法当场报错(而不是悄悄忽略)", () => {
    const layers = createHostLayers();
    layers.set("sidebar", { kind: "inset", active: true, width: 320 });
    const after = layers.set("inspector", { kind: "inset", active: true, width: 480 });
    expect(after.insetRight).toBe(480);
    expect(() => layers.set("x", { kind: "sneaky", active: true })).toThrow(/unknown kind/);
  });
  it("弹窗开关只改覆盖原因,右侧栏声明不会被弹窗归零", () => {
    const layers = createHostLayers();
    layers.set("comfy-workbench-column", { kind: "inset", active: true, width: 420 });
    layers.set("preview", { kind: "overlay", active: true });
    expect(layers.directives().insetRight).toBe(420);
    expect(layers.directives().reasons).toEqual(["overlay"]);
    layers.set("preview", { kind: "overlay", active: false });
    expect(layers.directives().insetRight).toBe(420);
    expect(layers.directives().reasons).toEqual([]);
    layers.set("comfy-workbench-column", { kind: "inset", active: false, width: 0 });
    expect(layers.directives().insetRight).toBe(0);
  });
});
