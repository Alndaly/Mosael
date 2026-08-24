/**
 * 画不出来时的那块提示,必须在监视器的**最上层**。
 *
 * 线上现象:「重新生成代理」按钮点不到,指针落在别的层上。原因是提示写的是 z-[3],而变换手柄是
 * z-[4]、文字片段的拖动层同为 z-[3] 但在 DOM 里更靠后 —— 两者都压在它上面。
 *
 * 真正的修法有两半,这条棘轮守的是第一半(层级),第二半在 Monitor 里:画面出不来时那些操作层
 * 干脆不渲染 —— 你没法去拖一个看不见的东西。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const HERE = import.meta.dirname;
const monitor = readFileSync(join(HERE, "..", "Monitor.tsx"), "utf8");
const overlay = readFileSync(join(HERE, "PreviewUnavailable.tsx"), "utf8");

const zIndexes = (code: string): number[] =>
  [...code.matchAll(/z-\[(\d+)\]/g)].map((m) => Number(m[1]));

describe("预览不可用时的层级", () => {
  it("提示层高于监视器里所有层", () => {
    const overlayZ = Math.max(...zIndexes(overlay));
    const monitorZ = Math.max(...zIndexes(monitor));
    expect(overlayZ).toBeGreaterThan(monitorZ);
  });

  it("**画不出来时不渲染操作层** —— 光靠 z 不够:它们仍会吃掉滚轮与拖拽", () => {
    // 变换手柄与文字拖动层都必须挂上这个条件。
    expect(monitor).toContain("onSetTransform && !previewBlock");
    expect(monitor).toContain("{!previewBlock &&\n            activeTextClips.map(");
  });
});
