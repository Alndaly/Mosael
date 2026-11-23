/**
 * 缓存键的第一段(键族)只有一份名单:`queryKeys.QUERY_FAMILIES`;内联写的 `queryKey: [` 只减不增。
 *
 * 此前工厂只管住了它已有的族,工厂外的族等于自动豁免:`resourceKeys` 引用的四个前缀没有任何地方拥有,
 * 改了一处内联键名,写入之后的失效就悄悄断了 —— 过编译、过测试。现在:
 *   · 任何键位置上的第一段都得在名单里(改名会在这里红,而不是在用户那里「不刷新」);
 *   · 名单里的每一族都真的有人用(死名字会让人以为它还在起作用);
 *   · 每个文件里内联的 `queryKey: [` 不比清单(inlineQueryKeys.baseline.json)多,也不许新文件写 ——
 *     新代码用工厂;某个文件少了,把清单里那个数改小。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import baseline from "./inlineQueryKeys.baseline.json";
import { QUERY_FAMILIES } from "./queryKeys";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");
//: 键的位置:`queryKey: [`、`setQueryData([` / `getQueryData([`,以及名字里带 key / prefix 的常量。
const KEY_HEAD =
  /(?:queryKey:\s*|QueryData(?:<[^>]*>)?\(\s*|\b(?:const|let)\s+\w*(?:[Kk]ey|[Pp]refix)\w*\s*=\s*(?:React\.useMemo\(\(\)\s*=>\s*)?)\[\s*"([a-z][a-z0-9-]*)"/g;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

const files = sources(SRC).map((path) => ({ path: relative(SRC, path), text: readFileSync(path, "utf8") }));
const families = new Set<string>(QUERY_FAMILIES);

describe("缓存键族", () => {
  it("键位置上的第一段都在名单里", () => {
    const unknown = files.flatMap(({ path, text }) =>
      [...text.matchAll(KEY_HEAD)].map((m) => m[1]).filter((head) => !families.has(head)).map((head) => `${path}: ${head}`),
    );
    expect(unknown, "这些键族不在 queryKeys.QUERY_FAMILIES 里(改名了?新族就加进名单)").toEqual([]);
  });

  it("名单里的每一族都有人用", () => {
    const used = new Set(files.flatMap(({ path, text }) => (path === "api/queryKeys.ts" ? [] : [...text.matchAll(/"([a-z][a-z0-9-]*)"/g)].map((m) => m[1]))));
    const factory = files.find(({ path }) => path === "api/queryKeys.ts")!.text;
    const declaredInFactories = new Set([...factory.slice(0, factory.indexOf("QUERY_FAMILIES")).matchAll(/\[\s*"([a-z][a-z0-9-]*)"/g)].map((m) => m[1]));
    const dead = QUERY_FAMILIES.filter((family) => !used.has(family) && !declaredInFactories.has(family));
    expect(dead, "名单里没人用的键族").toEqual([]);
  });

  it("内联的 queryKey 只减不增", () => {
    const allowed = baseline as Record<string, number>;
    const grown = files.flatMap(({ path, text }) => {
      const count = (text.match(/queryKey:\s*\[/g) ?? []).length;
      return count > (allowed[path] ?? 0) ? [`${path}: ${allowed[path] ?? 0} → ${count}`] : [];
    });
    expect(grown, "这些文件多了内联的 queryKey —— 用 api/queryKeys 的工厂").toEqual([]);
  });
});
