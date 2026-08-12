/**
 * 无边框窗顶栏给系统按钮让位的规则,**只能有一份**。
 *
 * 这条棘轮是被一个真实 bug 换来的:应用里有三处顶栏(AppShell、素材对比、内嵌浏览器工具栏),
 * 每处都手写了「让开 88px」和「全屏时改回去」两条类。发布视图那条只写了前一半 —— 非全屏正常,
 * 全屏时左边空出 88px 没人认领,而它看起来和另外两处一模一样,所以没人发现。
 *
 * 现在这条规则住在 `lib/windowChrome.ts`,且把 `:not(.is-fullscreen)` 写进选择器本身,不再需要
 * 配对的第二条类。这个测试拦的就是「下一处顶栏又手写一遍」。
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const OWNER = join(SRC, "lib", "windowChrome.ts");

/** 让位用的两个魔数 —— macOS 红绿灯宽、Windows 三键宽。 */
const INSETS = ["pl-[88px]", "pr-[148px]"];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) ? [full] : [];
  });
}

describe("窗口装饰让位", () => {
  it("让位的尺寸只写在 windowChrome.ts 里", () => {
    const offenders = sourceFiles(SRC)
      .filter((file) => file !== OWNER && !file.endsWith("windowChrome.test.ts"))
      .filter((file) => INSETS.some((inset) => readFileSync(file, "utf8").includes(inset)));
    expect(offenders.map((f) => f.slice(SRC.length + 1))).toEqual([]);
  });

  it("**全屏由选择器自己排除**,不靠第二条类去改回来", () => {
    const source = readFileSync(OWNER, "utf8");
    for (const inset of INSETS) {
      expect(source, `${inset} 必须写在 :not(.is-fullscreen) 变体里`).toMatch(
        new RegExp(`:not\\(\\.is-fullscreen\\)_&\\]:${inset.replace(/[[\]]/g, "\\$&")}`),
      );
    }
    // 有了 :not() 就不该再出现「全屏时改回去」的补丁类;它一旦回来,配对遗漏的老毛病也就回来了。
    expect(source).not.toContain(".is-fullscreen_&]");
  });
});
