/**
 * 字幕翻译的引擎选择必须真的传到后端。
 *
 * 这条拦的是本项目反复出现的一种形状:**能力在下层做好了,入口却没接上**。
 * `translateTexts` 的 `engine` 参数有默认值(空 = 按默认),后端能力表里 Google、对话模型、翻译插件
 * 也都在 —— 于是「不接」看起来一切正常:代码能编译、翻译能出结果,只是永远走默认那一家,
 * 用户点的那一家一次都不会被调用,而且没有任何报错提示这件事。
 *
 * 所以断言的是「调用点带上了 engine」,不是「组件里有个下拉」:有下拉但没传参,正是要拦的那种。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const PANEL = readFileSync(join(import.meta.dirname, "SubtitlePanel.tsx"), "utf8");

/** 去掉注释,免得这条棘轮被「注释里提到 engine」喂饱(本仓库真出过这种空棘轮)。 */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("字幕翻译引擎", () => {
  it("engine 传给了 translateTexts,而不是吃默认值", () => {
    const body = code(PANEL);
    const call = body.match(/translateTexts\(([\s\S]*?)\);/);
    expect(call, "SubtitlePanel 应当调用 translateTexts").not.toBeNull();
    // 第四个实参就是 engine;数逗号比正则匹配变量名更难糊弄。
    expect(call![1]).toContain("engine");
  });

  it("能选的那几家照能力表列,不写死 google / ai(ADR 0032:插件也能插进来)", () => {
    const body = code(PANEL);
    expect(body).toContain("listCapabilityChoices");
    expect(body).toContain('"translation"');
    expect(body).not.toContain('value="google"');
    expect(body).not.toContain('value="ai"');
  });
});
