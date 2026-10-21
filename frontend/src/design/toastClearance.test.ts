/**
 * 提示条让开贴底输入区的**机制**是接好的(components/app/toastClearance),随时可以启用:
 * 贴底输入区挂 `data-toast-avoid`、伸进右下角那一列大半,提示条就抬到它上沿之上。
 *
 * **当前一个输入区都没挂**(维护者定):提示条就该待在窗口右下角,短暂盖住输入区一角没关系 ——
 * AI Studio 的输入卡、各页智能体面板都**有意不挂**。机制留着备用(后续加新表面时可能重新启用),
 * 这条棘轮守的是「Toaster 的 offset 跟着 useToastClearance 走」这一头别被人随手拔掉 ——
 * 拔了再启用时就静默失效。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { readSource, tsxSources } from "@/design/jsxSource";

describe("提示条让开贴底输入区的机制", () => {
  it("机制在:量偏移的 hook 和纯函数都在", () => {
    const src = readSource("components/app/toastClearance.ts");
    expect(src).toMatch(/export function useToastClearance\(\)/);
    expect(src).toMatch(/export function toastBottomOffset\(/);
  });

  it("提示条那一头确实在用这条规则(Toaster 的 offset 跟着 useToastClearance 走)", () => {
    const app = readSource("app/App.tsx");
    expect(app).toMatch(/useToastClearance\(\)/);
    expect(app).toMatch(/<Toaster[\s\S]*?offset=\{\{\s*bottom\s*\}\}/);
  });

  it("当前没有输入区挂 data-toast-avoid(有意不避让;机制备用,别删)", () => {
    const carriers = tsxSources().filter((rel) => /\bdata-toast-avoid\b/.test(readSource(rel)));
    expect(carriers).toEqual([]);
  });
});
