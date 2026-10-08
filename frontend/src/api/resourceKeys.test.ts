/**
 * 「数据种类 → 缓存键」那张表(ADR 0053)。
 *
 * 一次操作改了什么由后端那一侧声明(任务的 `affects`、需要确认的工具的 `writes`),词表在 backend/app/domain/resources.py;
 * 换成缓存键只有 api/resourceKeys 这一张表。这里守两件事:
 *
 * 1. 后端的每一个词这张表里都有,而且给了键 —— 漏了,那种数据被改之后界面不刷新,而谁都不会报错;
 * 2. 表里写的每个键都真有查询在用 —— 写错一个字母(`publish-task`)同样是静悄悄地不刷新。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { RESOURCE_QUERY_KEYS } from "./resourceKeys";

const SRC = join(import.meta.dirname, "..");
const OPENAPI = join(SRC, "..", "..", "backend", "openapi.json");

type Schema = { properties?: Record<string, { items?: { enum?: string[] } }> };
const schemas = (JSON.parse(readFileSync(OPENAPI, "utf8")) as { components: { schemas: Record<string, Schema> } }).components.schemas;
/** 后端两处声明用的词:确认卡上的 `writes`,任务目录里的 `affects`。 */
const vocabulary = (schema: string, field: string) => schemas[schema]?.properties?.[field]?.items?.enum ?? [];

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "generated" ? [] : sources(full);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && entry.name !== "resourceKeys.ts" ? [full] : [];
  });
}

/**
 * 有查询在用的键的第一段:写在 `queryKey: ["…"` 里的,和键工厂里 `["…", …] as const` 的(api/queryKeys、各领域自己的
 * `*Keys`)。只认字面量 —— 拼出来的键这里看不见,那种就别往这张表里写。
 */
const rootsInUse = new Set<string>();
for (const file of sources(SRC)) {
  const text = readFileSync(file, "utf8");
  for (const m of text.matchAll(/queryKey:\s*\[\s*"([^"]+)"/g)) rootsInUse.add(m[1]);
  for (const m of text.matchAll(/\[\s*"([^"]+)"[^\]\n]*\]\s*as const/g)) rootsInUse.add(m[1]);
}

describe("数据种类 → 缓存键", () => {
  it("后端的每一个词都有缓存键,表里没有后端不说的词", () => {
    const writes = vocabulary("ConfirmationOut", "writes");
    const affects = vocabulary("JobKindOut", "affects");
    expect(writes.length, "openapi.json 里没读到 ConfirmationOut.writes 的词表").toBeGreaterThan(5);
    expect([...affects].sort(), "任务和确认卡该是同一套词(backend/app/domain/resources.py)").toEqual([...writes].sort());
    expect(Object.keys(RESOURCE_QUERY_KEYS).sort()).toEqual([...writes].sort());
    const empty = Object.entries(RESOURCE_QUERY_KEYS).filter(([, keys]) => keys.length === 0).map(([word]) => word);
    expect(empty, "这几种数据没给缓存键:被改了也不会刷新").toEqual([]);
  });

  it("表里写的每个键都真有查询在用", () => {
    expect(rootsInUse.size, "一个查询键都没扫到,多半是扫描的写法过期了").toBeGreaterThan(30);
    const dead = Object.entries(RESOURCE_QUERY_KEYS).flatMap(([word, keys]) =>
      keys.filter((key) => !rootsInUse.has(key)).map((key) => `${word} → ${key}`),
    );
    expect(dead, "没有哪个查询用这个键(写错了,或者那份数据换了键)").toEqual([]);
  });
});
