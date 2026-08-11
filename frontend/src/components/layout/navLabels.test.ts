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

import { NAV_ITEMS, STUDIO_VIEWS, navLabelKey } from "@/components/layout/navLabels";

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
