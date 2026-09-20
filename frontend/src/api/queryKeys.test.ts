/**
 * 素材缓存的键:取数可以细,失效必须粗。
 *
 * React Query 按**前缀**匹配失效,所以「用哪种形状的键」不是风格问题:剪辑页按
 * `["assets", 工作区, 项目]` 取数,首页按 `["assets", 工作区]` 取数,而剪辑页失效时也写三段
 * —— 三段匹配不到两段,于是在剪辑页导入一段素材,首页的素材列表不会刷新,停在旧数据上。
 *
 * 这条测试盯两件事:键工厂的前缀关系成立,以及**没有人再写内联的 `["assets", …]`**
 * (写了就又绕过了这份约定,而且照样能过编译、能过测试)。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { assetKeys } from "./queryKeys";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

describe("素材缓存的键", () => {
  it("失效用的键是取数用的键的前缀", () => {
    const all = assetKeys.all("ws");
    for (const key of [assetKeys.list("ws"), assetKeys.list("ws", "project")]) {
      expect(key.slice(0, all.length), `${JSON.stringify(key)} 不以 ${JSON.stringify(all)} 开头`).toEqual([...all]);
    }
    // 反过来不成立,这正是问题所在:三段的键匹配不到两段的缓存。
    expect(assetKeys.list("ws", "project").length).toBeGreaterThan(all.length);
  });

  it("不同工作区之间互不影响", () => {
    expect(assetKeys.all("a")).not.toEqual(assetKeys.all("b"));
  });

  it("失效一律用最短前缀 —— 没有人用 list() 去失效", () => {
    const offenders: string[] = [];
    for (const path of sources(SRC)) {
      const code = readFileSync(path, "utf8");
      for (const [line] of code.matchAll(/(?:invalidate|remove|cancel)Queries\(\{[^}]*assetKeys\.list\([^}]*\}/g)) {
        offenders.push(`${path.slice(SRC.length + 1)}: ${line.slice(0, 80)}`);
      }
    }
    expect(offenders, "失效要用 assetKeys.all():list() 更长,匹配不到按工作区取数的那些缓存").toEqual([]);
  });

  it("没有人再写内联的素材键", () => {
    const offenders = sources(SRC)
      .filter((path) => !path.endsWith(join("api", "queryKeys.ts")))
      .filter((path) => /queryKey:\s*\["assets"/.test(readFileSync(path, "utf8")))
      .map((path) => path.slice(SRC.length + 1));
    expect(offenders, "改用 assetKeys —— 内联写法正是当初两种形状各写各的起点").toEqual([]);
  });
});
