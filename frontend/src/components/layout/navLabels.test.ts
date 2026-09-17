/**
 * **每个页面都得有自己的名字。**
 *
 * 真机上 `#/admin` 的面包屑写着「首页」:侧栏是 `[...SECONDARY_NAV, ADMIN_NAV]` 拼出来的,
 * 而面包屑只查 `[...PRIMARY_NAV, ...SECONDARY_NAV]` —— ADMIN_NAV 不在里面,于是 `?? "navHome"`
 * 这个兜底接住了它,页面顶上就写着别的页面的名字。
 *
 * 又是同一个形状:**同一份清单在两处各列一遍,其中一处漏了一项**。所以这里不是补一个
 * ADMIN_NAV 进去就完事 —— 判据是"每一个 StudioView 都查得到标签",下一个新页面漏了照样红。
 */

import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { NAV_ITEMS, STUDIO_VIEWS, navItemsAt, navLabelKey } from "@/components/layout/navLabels";

describe("导航标签", () => {
  it("每个视图都查得到自己的标签", () => {
    for (const view of STUDIO_VIEWS) {
      const found = NAV_ITEMS.find((item) => item.view === view);
      expect(found, `${view} 没有导航标签 —— 面包屑会退回「首页」,页面顶上写着别的页面的名字`).toBeTruthy();
    }
  });

  it("admin 有自己的名字,不是「首页」", () => {
    expect(navLabelKey("admin")).toBe("navAdmin");
  });

  it("查不到的视图不会假装成首页", () => {
    expect(navLabelKey("nope" as never)).toBeNull();
  });
});

describe("页面清单只有一份", () => {
  /* 命令面板曾经自己抄了一份页面清单,漏掉了笔记、3D 场景、画板、管理 —— ⌘K 里跳不过去。
     侧栏的图标表、App.tsx 里那串 `view === "…"` 也是同一个形状。判据是**那几个地方不再各写
     一份**,而不是"现在恰好对得上"。 */
  const read = (rel: string) => readFileSync(join(import.meta.dirname, rel), "utf-8");

  it("命令面板不再自己列页面", () => {
    const source = read("CommandPalette.tsx");
    expect(source).toContain("NAV_ITEMS");
    expect(source).not.toMatch(/view:\s*"home"/);
  });

  it("侧栏不再自己记图标", () => {
    const source = read("AppShell.tsx");
    expect(source).not.toMatch(/Record<StudioView,\s*React\.ReactNode>/);
  });

  it("App 不再一页一页地写 view === …", () => {
    const source = read("../../app/App.tsx");
    expect(source).not.toMatch(/view === "(home|media|editor|settings)" &&/);
  });

  it("设置在侧栏底部,声明里也这么说", () => {
    //: 此前它被标成 primary,侧栏渲染时再特判滤掉 —— 声明和实际位置不一致。
    expect(navItemsAt("footer").map((item) => item.view)).toEqual(["settings"]);
    expect(navItemsAt("primary").some((item) => item.view === "settings")).toBe(false);
  });

  it("每一页都有图标和搜索词", () => {
    for (const item of NAV_ITEMS) {
      expect(item.icon, item.view).toBeTruthy();
      expect(item.keywords.length, item.view).toBeGreaterThan(0);
    }
  });
});
