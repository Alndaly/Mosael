/**
 * 去某一张画板只走 `lib/deepLink` 的 `openBoard`,没人再手写 `#/boards?board=…`。
 *
 * 手写的那种只改 hash:目标页还没挂载时够用,人已经在画板页上时(开着画板 A,从确认中心点「回到那里」去画板 B、智能体说
 * 「带你去看看」)点了没反应;而没被接住的参数留在地址里,下一次列表变化把人拽到 B 上,新建的那张板反倒没打开。
 * `goToPlace`、App 的智能体带路、3D 场景「送到画板」、资产「在哪里用过」都这么写过。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { blankComments } from "@/design/jsxSource";

const SRC = join(import.meta.dirname, "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry) && !entry.includes(".test.") ? [path] : [];
  });
}

describe("去某一张画板", () => {
  it("画板的地址只在 lib/deepLink 里拼", () => {
    const offenders = sources(SRC)
      .filter((path) => !path.endsWith(join("lib", "deepLink.ts")))
      .filter((path) => /boards\?board=/.test(blankComments(readFileSync(path, "utf8"))))
      .map((path) => relative(SRC, path));
    expect(offenders, "改用 openBoard(id)(要一个 href 就用 boardHref(id))").toEqual([]);
  });

  it("扫得到东西 —— 别变成空转", () => {
    expect(blankComments(readFileSync(join(SRC, "lib", "deepLink.ts"), "utf8"))).toMatch(/boards\?board=/);
  });
});
