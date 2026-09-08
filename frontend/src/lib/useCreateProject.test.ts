/**
 * 新项目的默认名字。
 *
 * 钉两件真出过的错:词干**不能是欢迎语**(「第一个项目」被当成词干,于是第六个项目叫
 * 「第一个项目 6」),序号**不能取"现有几个"**(删掉一个再建就撞名)。
 */
import { describe, expect, it } from "vitest";

import { nextProjectName } from "./useCreateProject";

const named = (...names: string[]) => names.map((name) => ({ name }));

describe("默认项目名", () => {
  it("第一个不带序号", () => {
    // 一个工作区里只有一个项目时,「未命名项目 1」里的那个 1 什么也没说明。
    expect(nextProjectName("未命名项目", [])).toBe("未命名项目");
  });

  it("重名时才往后排", () => {
    expect(nextProjectName("未命名项目", named("未命名项目"))).toBe("未命名项目 2");
    expect(nextProjectName("未命名项目", named("未命名项目", "未命名项目 2"))).toBe("未命名项目 3");
  });

  it("删掉中间那个之后,补回它的空位而不是撞名", () => {
    // 序号取"现有几个"的话:三个删掉第二个 → 还剩 2 个 → 下一个叫「未命名项目 3」,
    // 而「未命名项目 3」还在。这正是要防的。
    const left = named("未命名项目", "未命名项目 3");
    expect(nextProjectName("未命名项目", left)).toBe("未命名项目 2");
  });

  it("用户改过名字的项目不占位", () => {
    expect(nextProjectName("未命名项目", named("宣传片", "开箱视频"))).toBe("未命名项目");
  });
});
