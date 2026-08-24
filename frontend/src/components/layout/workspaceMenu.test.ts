/**
 * 工作区切换器上的「重命名 / 删除」谁能点。
 *
 * 这两项此前只在设置 → 团队与成员里,而那是**成员管理**的地方 —— 一个只想改个名的人不会
 * 想到去点它。现在切换器每一行也挂了右键菜单,于是同一个动作有了两个入口,门槛必须一致,
 * 否则界面会在两处给出两种答案:改名要 admin 及以上,删除只有 owner(和 TeamSection 同源)。
 *
 * 还钉一条只在这个入口才存在的约束:**列表只剩一个工作区时不许删**。设置页那个按钮在当前
 * 工作区上下文里,删完还能靠 WorkspaceGate 兜底;而这里能删的是任意一行,删到一个不剩的话,
 * 界面会落到一个没有工作区可选的状态。
 */
import { describe, expect, it } from "vitest";

import { workspaceMenuState as menuState } from "@/components/layout/workspaceMenu";

describe("工作区右键菜单的门槛", () => {
  it("viewer / editor 改不了名,也删不掉", () => {
    for (const role of ["viewer", "editor"]) {
      const s = menuState(role, 3);
      expect(s.renameDisabled, `${role} 竟然能改名`).toBe(true);
      expect(s.deleteDisabled, `${role} 竟然能删`).toBe(true);
    }
  });

  it("admin 能改名,但删不掉 —— 删除只有 owner", () => {
    const s = menuState("admin", 3);
    expect(s.renameDisabled).toBe(false);
    expect(s.deleteDisabled, "admin 能删工作区了").toBe(true);
  });

  it("owner 两样都能", () => {
    const s = menuState("owner", 3);
    expect(s.renameDisabled).toBe(false);
    expect(s.deleteDisabled).toBe(false);
  });

  it("只剩一个工作区时,owner 也不许删", () => {
    expect(menuState("owner", 1).deleteDisabled, "删到一个不剩,界面会没有工作区可选").toBe(true);
    expect(menuState("owner", 2).deleteDisabled).toBe(false);
  });

  it("角色缺失按最低权限处理,不按最高", () => {
    for (const role of [null, undefined, "somethingNew"]) {
      const s = menuState(role, 3);
      expect(s.renameDisabled, `role=${role} 被当成了有权限`).toBe(true);
      expect(s.deleteDisabled).toBe(true);
    }
  });
});
