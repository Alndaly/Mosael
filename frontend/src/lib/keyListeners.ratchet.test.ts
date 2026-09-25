/**
 * 全局键盘监听只经 `lib/shortcuts.listenKeys` 挂。
 *
 * 它替每个 handler 守一条规矩:输入法组词期间的按键归输入法(回车上屏、Esc 放弃组词、空格选词),
 * 不交给快捷键。裸写 `addEventListener("keydown", …)` 就绕过了这条 —— 而它在 diff 里只有一行,
 * 打英文的人永远测不出来。批注模式的 Esc 就是这么在捕获阶段把「放弃组词」吃成了「退出批注模式」。
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const HOME = join("lib", "shortcuts.ts");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

const stripComments = (code: string): string =>
  code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

/** 每个 `onKeyDown={…}` / `onKeyDownCapture={…}` 的整段(花括号配平)和它所在的行。 */
function keyDownHandlers(code: string): { line: number; body: string }[] {
  const found: { line: number; body: string }[] = [];
  const start = /onKeyDown(Capture)?=\{/g;
  for (let match = start.exec(code); match; match = start.exec(code)) {
    let depth = 0;
    let at = match.index + match[0].length - 1;
    for (; at < code.length; at += 1) {
      if (code[at] === "{") depth += 1;
      else if (code[at] === "}" && --depth === 0) break;
    }
    found.push({ line: code.slice(0, match.index).split("\n").length, body: code.slice(match.index, at + 1) });
  }
  return found;
}

describe("组件上的 onKeyDown", () => {
  //: 认 Enter / Escape 的那种最容易出事:组词时回车是「按拼音上屏」、Esc 是「放弃组词」,
  //: 被当成「提交」「取消编辑」的话,字没打完就提交了 / 整段编辑被撤掉了。
  it("认 Enter / Escape 的,都先问 isImeKeystroke(或自己判 isComposing)", () => {
    const offenders = sourceFiles(SRC).flatMap((file) =>
      keyDownHandlers(readFileSync(file, "utf8"))
        .filter(({ body }) => /["'](Enter|Escape)["']/.test(body) && !/isImeKeystroke|isComposing/.test(body))
        .map(({ line }) => `${file.slice(SRC.length + 1)}:${line}`),
    );
    expect(offenders).toEqual([]);
  });
});

describe("全局键盘监听", () => {
  it("没有地方绕过 listenKeys 直接挂 keydown / keyup / keypress", () => {
    const offenders = sourceFiles(SRC)
      .filter((file) => file.slice(SRC.length + 1) !== HOME)
      .filter((file) => /addEventListener\(\s*["'`]key(down|up|press)["'`]/.test(stripComments(readFileSync(file, "utf8"))));
    expect(offenders.map((file) => file.slice(SRC.length + 1))).toEqual([]);
  });
});
