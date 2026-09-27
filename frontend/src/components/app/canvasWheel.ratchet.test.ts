/**
 * 每一块 React Flow 画布的滚轮都走 `canvasWheelProps`(canvasInputMode.ts)。
 *
 * 缺省的「按住 ⌘ 滚动 = 缩放」靠 keydown / keyup 记着 ⌘,抬起被系统吞掉时它就卡在「按着」:触控板双指滑动
 * 变成缩放(用户撞上过)。新加一块画布要是自己写 panOnScroll / zoomOnScroll,就又把这个键带回来了。
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..", "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name) ? [full] : [];
  });
}

/** `<ReactFlow …>` 开标签的全文:花括号配平,只认花括号外面的那个 `>`(属性里的 `=>` 不算)。 */
function openingTags(code: string): string[] {
  const tags: string[] = [];
  for (const start of code.matchAll(/<ReactFlow\b/g)) {
    let depth = 0;
    for (let i = start.index; i < code.length; i += 1) {
      const char = code[i];
      if (char === "{") depth += 1;
      else if (char === "}") depth -= 1;
      else if (char === ">" && depth === 0) {
        tags.push(code.slice(start.index, i + 1));
        break;
      }
    }
  }
  return tags;
}

it("每一块 <ReactFlow> 画布的滚轮都走 canvasWheelProps,不自己写 panOnScroll / zoomOnScroll", () => {
  const offenders: string[] = [];
  let canvases = 0;
  for (const file of sourceFiles(SRC)) {
    const code = readFileSync(file, "utf8");
    for (const tag of openingTags(code)) {
      canvases += 1;
      if (!tag.includes("canvasWheelProps(") || /\b(panOnScroll|zoomOnScroll|zoomActivationKeyCode)=/.test(tag)) {
        offenders.push(file.slice(SRC.length + 1));
      }
    }
  }
  expect(canvases, "找得到画布 —— 否则下面那句是在空处断言").toBeGreaterThanOrEqual(2);
  expect(offenders).toEqual([]);
});
