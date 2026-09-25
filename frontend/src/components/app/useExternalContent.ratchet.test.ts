/**
 * TipTap 编辑器从外面接内容只走 `useExternalContent`,不在 `useEffect` 里直接 `setContent`。
 *
 * 直接写的那种在英文下没有任何毛病;中文输入法组词时它会把组词中的字盖掉、字母上屏
 * (见 useExternalContent 开头那段)。它在 diff 里就是一行 effect,靠人眼挡不住。
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..", "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.tsx?$/.test(entry.name) && !entry.name.includes(".test.") ? [full] : [];
  });
}

/** 每个 `useEffect(` / `useLayoutEffect(` 调用的整段(括号配平)。 */
function effectBodies(code: string): string[] {
  const bodies: string[] = [];
  const start = /\buse(Layout)?Effect\(/g;
  for (let match = start.exec(code); match; match = start.exec(code)) {
    let depth = 0;
    let at = match.index + match[0].length - 1;
    for (; at < code.length; at += 1) {
      if (code[at] === "(") depth += 1;
      else if (code[at] === ")" && --depth === 0) break;
    }
    bodies.push(code.slice(match.index, at + 1));
  }
  return bodies;
}

describe("TipTap 编辑器从外面接内容", () => {
  it("没有 effect 直接 setContent(走 useExternalContent)", () => {
    const offenders = sourceFiles(SRC).filter((file) =>
      effectBodies(readFileSync(file, "utf8")).some((body) => /\.setContent\(/.test(body)),
    );
    expect(offenders.map((file) => file.slice(SRC.length + 1))).toEqual([]);
  });
});
