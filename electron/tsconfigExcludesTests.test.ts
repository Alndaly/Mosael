/**
 * `electron/tsconfig.json` 必须把测试文件排除在外。
 *
 * 那份配置是给**主进程产品代码**做类型检查的闸(esbuild 只打包、不看类型)。测试文件
 * import `vitest`,而 vitest 是 frontend 的 devDependency —— pnpm 的严格 node_modules
 * 布局下,从 electron/ 这个目录解析不到它。
 *
 * 后果很阴:本地的 node_modules 是扁平的,解析得到,`pnpm typecheck:electron` 全绿;
 * CI 用 --frozen-lockfile 装出严格布局,同一条命令报 `Cannot find module 'vitest'`。
 * 于是本地看不出问题,推了 tag 才炸(v0.18.5 就是这么挂的)。
 *
 * 测试自己的类型由 vitest 跑的时候负责:它跑得起来,就说明依赖解析得到。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const CONFIG = path.resolve(__dirname, "tsconfig.json");

function readConfig(): { include?: string[]; exclude?: string[] } {
  // tsconfig 允许注释和尾逗号,而这份文件用 "// 说明" 这种键放注释,所以直接 JSON.parse 就行。
  return JSON.parse(fs.readFileSync(CONFIG, "utf8"));
}

describe("electron 的类型检查配置", () => {
  it("把测试文件排除掉了", () => {
    const exclude = readConfig().exclude ?? [];
    expect(exclude.some((pattern) => pattern.includes("*.test.ts"))).toBe(true);
  });

  it("include 里没有直接点名测试文件 —— 那会绕过 exclude 的本意", () => {
    const include = readConfig().include ?? [];
    expect(include.filter((pattern) => pattern.includes("test"))).toEqual([]);
  });
});
