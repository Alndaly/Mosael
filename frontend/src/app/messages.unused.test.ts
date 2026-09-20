/**
 * 文案表里**不留没人用的条目**。
 *
 * 清理那一轮扫出 218 个:删掉的功能留下的(`filter_bw` 早被 `colorPreset_*` 取代)、改版后
 * 没人引用的空状态、以及一批重命名前的旧名字。中英各一份,合起来四百多行。
 *
 * 它们不会报错,只是让这张两千多条的表越来越难信:找一个键时分不清哪些还活着,
 * 翻译时也要跟着翻一遍死条目。
 *
 * **判定是保守的**(宁可漏判,不可误删):一个键只要在任何一处以字面量出现、被模板拼出来
 * (`t(`studioPrompt${kind}Text`)`)、或者是后端发过来的消息键,就算用着。第一版没把不带下划线
 * 的模板片段算进去,于是把 `studioPromptEditText` 判成了死键 —— 是 tsc 把它挡了下来。
 * 漏判的代价只是少删几条;误删的代价是界面上直接显示键名。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");
const MESSAGES = join(SRC, "app", "messages.ts");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && path !== MESSAGES ? [path] : [];
  });
}

/** 模板里**每一段字面量**都是线索:`studioPrompt${kind}Text` 给出 studioPrompt 和 Text。 */
function templateFragments(code: string): Set<string> {
  const found = new Set<string>();
  for (const [, template] of code.matchAll(/`([^`]*\$\{[^`]*)`/g)) {
    for (const part of template.split(/\$\{[^}]*\}/)) {
      const piece = part.trim();
      if (piece.length >= 3 && /^\w+$/.test(piece)) found.add(piece);
    }
  }
  for (const [, prefix] of code.matchAll(/["'](\w{3,})["']\s*\+/g)) found.add(prefix);
  return found;
}

describe("文案表", () => {
  const messages = readFileSync(MESSAGES, "utf8");
  const keys = [...messages.matchAll(/^ {4}(\w+):/gm)].map((one) => one[1]);
  const code = sources(SRC).map((path) => readFileSync(path, "utf8")).join("\n");
  const fragments = templateFragments(code);

  it("没有没人用的条目", () => {
    const unused = [...new Set(keys)].filter((key) => {
      if (new RegExp(`["'\`]${key}["'\`]`).test(code)) return false;
      if ([...fragments].some((piece) => key.startsWith(piece) || key.endsWith(piece))) return false;
      return true;
    });
    // 后端发过来的消息键(job/workflow 的 i18n)由 backend 那侧的棘轮盯着,不在这张表里。
    expect(unused, "这些文案没人用了 —— 删掉它们,或者说明它是从哪儿拼出来的").toEqual([]);
  });

  it("这道棘轮扫得到东西 —— 别变成空转", () => {
    expect(keys.length).toBeGreaterThan(2000);
    expect(fragments.size).toBeGreaterThan(10);
  });
});
