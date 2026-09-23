/**
 * 浮层不许落进顶栏、不许被推出窗口。
 *
 * 真机(2026-09-23):工作流节点里的素材下拉(>8 项,走带搜索的 Popover)向上展开,
 * 顶部几项跑出窗口,搜索框一起看不见;窗口里的那几项压在顶栏上,点不动。
 *
 * 两个原因,各有一处约定:
 * - Radix 只知道视口、不知道顶栏;而顶栏在桌面端是拖拽区,拖拽区由系统先截走输入,z-index 无效。
 *   → 所有带定位的浮层默认用 FLOATING_COLLISION_PADDING(顶部让出顶栏),样式里再统一 no-drag。
 * - 带搜索的下拉只写了列表 300px,浮层整体没有按可用高度限高。
 *   → PopoverContent 按 available-height 限高并自己滚;带搜索的那份让列表滚、搜索框不动。
 *
 * 越界不会报错,只会「看得见、点不动」—— 所以钉在源码上。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const UI = import.meta.dirname;
const read = (name: string) => readFileSync(join(UI, name), "utf8");

describe("浮层的边界", () => {
  it.each(["popover.tsx", "select.tsx", "context-menu.tsx", "tooltip.tsx"])(
    "%s 的浮层默认让出顶栏",
    (file) => {
      expect(read(file)).toContain("collisionPadding={FLOATING_COLLISION_PADDING}");
    },
  );

  it("右键菜单的子菜单也让出顶栏(它是另一个定位的浮层)", () => {
    expect(read("context-menu.tsx").match(/collisionPadding=\{FLOATING_COLLISION_PADDING\}/g)).toHaveLength(2);
  });

  it("顶部边距不小于顶栏高度", async () => {
    const { FLOATING_COLLISION_PADDING } = await import("./floating");
    const { WINDOW_CHROME_HEIGHT } = await import("@/lib/windowChrome");
    expect(FLOATING_COLLISION_PADDING.top).toBeGreaterThanOrEqual(WINDOW_CHROME_HEIGHT);
  });

  it("PopoverContent 按可用高度限高,内容多了在里面滚", () => {
    const source = read("popover.tsx");
    expect(source).toContain("max-h-[var(--radix-popover-content-available-height)]");
    expect(source).toContain("overflow-y-auto");
  });

  it("带搜索的下拉:列表限高扣掉可用高度,搜索框不跟着滚", () => {
    const source = read("searchable-select.tsx");
    expect(source).toMatch(/max-h-\[min\(300px,calc\(var\(--radix-popover-content-available-height/);
    expect(source).toContain('"p-0 overflow-hidden"');
  });

  it("所有带定位的浮层在桌面端都不是拖拽区", () => {
    const styles = readFileSync(join(UI, "..", "..", "app", "styles.css"), "utf8");
    expect(styles).toMatch(/\.is-desktop \[data-radix-popper-content-wrapper\]\s*\{\s*-webkit-app-region:\s*no-drag;\s*\}/);
  });
});
