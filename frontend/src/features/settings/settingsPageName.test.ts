/**
 * 设置里那一页的旧名字(设+音+色那种组合,见下面的 `OLD`)**一个字符都不许再留在源码里**。
 *
 * 改名只改看得见的那三处(侧栏、页头、页说明)是不够的:指路文案里只要还剩一句「去设置的『那一页』
 * 里换」,用户就会照着一个**已经不存在的地方**去找 —— 上一版有 12 处指路还引着旧节名,就是这么坏的。
 * 旧名在下面拆成片段拼:整串写在文档里,这条测试就会把自己算成一处残留。
 *
 * 所以这条扫的是前台与后端的全部源码(不含 CHANGELOG、docs、website:那几处归各自的改动所有,
 * 见交付说明)。旧名在测试里用片段拼出来,免得这条测试自己成了唯一命中的那一处。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

//: 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const REPO = join(import.meta.dirname, "..", "..", "..", "..");
const FRONTEND_SRC = join(import.meta.dirname, "..", "..");
const BACKEND_APP = join(REPO, "backend", "app");
const CODE = /\.(?:ts|tsx|py)$/;

/** 旧页名拆成片段:`["配音","与","音色"]` —— 整串写在这里,这条测试就会把自己算成一处残留。 */
const OLD = {
  zh: ["配音", "与", "音色"].join(""),
  en: ["Dubbing", "&", "voices"].join(" "),
};

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === "node_modules" || entry.name === "__pycache__") return [];
    const path = join(dir, entry.name);
    if (statSync(path).isDirectory()) return sources(path);
    return CODE.test(entry.name) ? [path] : [];
  });
}

function offenders(needle: string): string[] {
  return [...sources(FRONTEND_SRC), ...sources(BACKEND_APP)]
    .filter((path) => readFileSync(path, "utf8").includes(needle))
    .map((path) => path.slice(REPO.length + 1));
}

describe("设置页的旧名字", () => {
  it(`「${OLD.zh}」在前后端源码里一个都不剩`, () => {
    expect(offenders(OLD.zh)).toEqual([]);
  });

  it(`英文旧名(${OLD.en})也一样`, () => {
    expect(offenders(OLD.en)).toEqual([]);
  });

  it("这道棘轮扫得到东西 —— 别变成空转", () => {
    //: 扫的是真源码:两个目录都在,而且能读到几千个文件里的一部分。
    expect(sources(FRONTEND_SRC).length).toBeGreaterThan(100);
    expect(sources(BACKEND_APP).length).toBeGreaterThan(100);
    //: 判据要真的能命中:拿现在**确实存在**的一句文案当探针。
    expect(offenders("这个工作区的音色")).not.toEqual([]);
  });
});
