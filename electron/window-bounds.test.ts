/**
 * 主窗口照上次的位置、大小打开(window-bounds.cjs),但要对得上此刻的显示器。
 */
import { createRequire } from "node:module";

import { describe, expect, it } from "vitest";

const { placeWindow } = createRequire(import.meta.url)("./window-bounds.cjs") as {
  placeWindow: (
    saved: unknown,
    displays: { workArea: { x: number; y: number; width: number; height: number } }[],
    defaults: { width: number; height: number; minWidth: number; minHeight: number },
  ) => { bounds: { x?: number; y?: number; width: number; height: number }; maximized: boolean };
};

const DEFAULTS = { width: 1440, height: 900, minWidth: 980, minHeight: 640 };
const MAC = { workArea: { x: 0, y: 25, width: 1728, height: 1092 } };
const EXTERNAL = { workArea: { x: 1728, y: 0, width: 2560, height: 1415 } };
const SMALL = { workArea: { x: 0, y: 0, width: 1366, height: 728 } };

describe("主窗口放哪", () => {
  it("没存过、存的是坏的:默认大小,主屏居中", () => {
    for (const saved of [null, "garbage", { x: "1" }, { x: 1, y: 2, width: Number.NaN, height: 3 }]) {
      expect(placeWindow(saved, [MAC], DEFAULTS)).toEqual({ bounds: { x: 144, y: 121, width: 1440, height: 900 }, maximized: false });
    }
  });

  it("上次摆在哪就放回哪,最大化照旧", () => {
    const saved = { x: 2000, y: 100, width: 1600, height: 1000, maximized: true };
    expect(placeWindow(saved, [MAC, EXTERNAL], DEFAULTS)).toEqual({ bounds: { x: 2000, y: 100, width: 1600, height: 1000 }, maximized: true });
  });

  it("那块外接屏拔了:回到主屏居中", () => {
    const saved = { x: 2000, y: 100, width: 1600, height: 1000, maximized: false };
    expect(placeWindow(saved, [MAC], DEFAULTS).bounds).toEqual({ x: 144, y: 121, width: 1440, height: 900 });
  });

  it("屏比上次小(1366×768 的笔记本):夹进工作区,位置跟着挪回来,不超出屏幕", () => {
    const saved = { x: 300, y: 200, width: 1440, height: 900, maximized: false };
    const { bounds } = placeWindow(saved, [SMALL], DEFAULTS);
    expect(bounds).toEqual({ x: 0, y: 0, width: 1366, height: 728 });
  });

  it("默认大小放不下的小屏上,第一次打开也不超出屏幕", () => {
    expect(placeWindow(null, [SMALL], DEFAULTS).bounds).toEqual({ x: 0, y: 0, width: 1366, height: 728 });
  });

  it("只露出屏幕边上一条:算看不见,回主屏居中", () => {
    const saved = { x: 1700, y: 100, width: 1200, height: 800 };
    expect(placeWindow(saved, [MAC], DEFAULTS).bounds).toEqual({ x: 144, y: 121, width: 1440, height: 900 });
  });
});
