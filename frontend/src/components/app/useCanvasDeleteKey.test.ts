/**
 * 棘轮:**每块 React Flow 画布的删除键都走 useCanvasDeleteKey**。
 *
 * React Flow 自带的删除键听整个 document,只放过输入框和 `.nokey`:焦点停在浮在节点上的面板
 * 按钮上、或者在 Portal 到 body 的下拉选项上时按 Backspace,删掉的是正在编辑的那一格。工作流
 * 编辑器修过一遍之后,画板还是老样子 —— 规矩只写在一处的话,新画布照抄旧写法就又回来了。
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

export const RATCHET = true;

const SRC = join(import.meta.dirname, "..", "..");

function sources(): Array<{ path: string; text: string }> {
  return readdirSync(SRC, { recursive: true, encoding: "utf8" })
    .filter((path) => path.endsWith(".tsx") && !path.includes(".test."))
    .map((path) => ({ path: path.split(/[\\/]/).join("/"), text: readFileSync(join(SRC, path), "utf8") }));
}

describe("React Flow 画布的删除键", () => {
  const canvases = sources().filter(({ text }) => /<ReactFlow\b/.test(text));

  it("找得到画布(找不到说明这条棘轮失效了)", () => {
    expect(canvases.map(({ path }) => path)).toEqual(
      expect.arrayContaining(["features/boards/BoardCanvas.tsx", "features/workflows/WorkflowsView.tsx"]),
    );
  });

  it.each(canvases.map(({ path, text }) => [path, text]))(
    "%s 关掉自带的删除键,改用 useCanvasDeleteKey",
    (_path, text) => {
      expect(text).toMatch(/deleteKeyCode=\{null\}/);
      expect(text).toMatch(/useCanvasDeleteKey\(/);
    },
  );
});
