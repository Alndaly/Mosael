/**
 * 拖柄长什么样,**全应用只有一份定义**。
 *
 * 剪辑页和对话页早就长成同一个样子:骑在 8px 列间隙正中、7px 的热区里一根 36px 的短竖条、
 * 常显、悬停变主色。我给插件/设置/定时页加拖柄时照着"印象"写了第三份 —— 写成了整条高、
 * 悬停才现、还偏了 3px。
 *
 * 「看起来不一样」这件事没有任何别的测试拦得住:类型是对的、渲染是对的、点了也能拖。
 * 所以这里盯的是**有没有人又手写了一份**。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { HANDLE_COLUMN, HANDLE_PILL, HANDLE_ROW, HANDLE_SIZE, handleOffset } from "./useResizableSidebar";

const SRC = join(import.meta.dirname, "..");
const DEFINITION = join(SRC, "lib", "useResizableSidebar.ts");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

describe("拖柄只有一份定义", () => {
  it("没有别处手写那根短竖条", () => {
    // 判据:`before:h-9 before:w-0.5`(竖条)或 `before:h-0.5 before:w-9`(横条)——
    // 那是这根条子的形状,写死在别处就是又抄了一份。
    const offenders = sources(SRC)
      .filter((path) => path !== DEFINITION)
      .filter((path) => {
        const code = readFileSync(path, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
        return /before:h-9\s+before:w-0\.5|before:h-0\.5\s+before:w-9/.test(code);
      })
      .map((path) => path.slice(SRC.length + 1));
    expect(offenders).toEqual([]);
  });

  it("拖柄的外观、方向、位置是拼出来的,不是各写各的", () => {
    expect(HANDLE_COLUMN).toContain(HANDLE_PILL);
    expect(HANDLE_ROW).toContain(HANDLE_PILL);
    expect(HANDLE_COLUMN).toContain("cursor-col-resize");
    expect(HANDLE_ROW).toContain("cursor-row-resize");
  });

  it("停靠的栏之间只有分割线、没有缝 —— 手柄压在线上", () => {
    // 判据:用到可拖侧栏的页面,它那个 `relative grid` 容器上不该再有列间距。
    // 有的话,手柄要么悬在离线几像素的空白里,要么每页一个样(这一轮就是这么被发现的)。
    // 画布上的浮动卡片(RightDockResizeHandle)不是停靠栏,卡片之间本来就有缝。
    const offenders = sources(SRC)
      .filter((path) => /useResizableSidebar|useSidePanels/.test(readFileSync(path, "utf8")))
      .filter((path) => !readFileSync(path, "utf8").includes("RightDockResizeHandle"))
      .filter((path) => /["`]relative grid[^"`]*\bgap-\d/.test(readFileSync(path, "utf8")))
      .map((path) => path.slice(SRC.length + 1));
    expect(offenders).toEqual([]);
    expect(handleOffset(300)).toBe(300 - HANDLE_SIZE / 2);
  });

  it("这道棘轮扫得到东西 —— 别变成空转", () => {
    expect(sources(SRC).length).toBeGreaterThan(50);
  });
});
