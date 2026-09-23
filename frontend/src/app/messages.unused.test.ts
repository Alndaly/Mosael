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
  // 源码里所有被引号包住的单词,**扫一遍**收进集合。此前是每个键各编一条正则、各扫一遍全部
  // 源码(两千多个键 × 几 MB),单跑 1.8s,全量并行时常撞 5s 超时 —— 失败原因是「慢」,
  // 而不是「有没人用的文案」,这比不测更糟。判据不变:键被 ' " ` 之一包住地出现过(收尾的引号用前瞻,不吃掉 —— 紧挨着的
  // 两个 `"a""b"` 共用中间那个引号,吃掉的话后一个就漏了)。
  const quoted = new Set([...code.matchAll(/["'`](\w+)(?=["'`])/g)].map((one) => one[1]));

  it("没有没人用的条目", () => {
    const unused = [...new Set(keys)].filter((key) => {
      if (quoted.has(key)) return false;
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
