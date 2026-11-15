/**
 * 棘轮:**后端时间一律经过 `parseServerTime` 解析**。
 *
 * 后端交回的时间是 UTC、不带时区标记的 ISO 串(`2026-11-15 11:39:52`)。`Date.parse` / `new Date(…)` 直接吃它,浏览器
 * 当成本地时间:东八区差整整 8 小时。2026-11-15 智能体「后台任务」写着「已跑 480m 20s」,点开详情却是「39 秒前开始」——
 * 计时那一处直接 `Date.parse(job.created_at)`;任务中心悬停的时间、节点包「装好了待重启」的判断也是同一个错。
 * `lib/time.parseServerTime` 早就在了,只是没人非走它不可。所以收成一条:除了 `lib/time.ts` 自己,源码里不许直接
 * `Date.parse(`,也不许 `new Date(<…>_at)` / `new Date(<…>.timestamp)` 这种把后端字段直接塞进去的写法。
 */
export const RATCHET = true;

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const HOME = "lib/time.ts";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") && !path.endsWith(".d.ts") ? [path] : [];
  });
}

//: 按秒存的数字时间戳(`deleted_at * 1000`)不是 ISO 串,不在此列。
const RAW = [/\bDate\.parse\(/, /new Date\((?![^)]*\* ?1000)[^)]*(?:_at|\.timestamp)\b[^)]*\)/];

describe("后端时间", () => {
  it("除了 lib/time.ts,没有一处直接 Date.parse / new Date(后端时间字段)", () => {
    const offenders: string[] = [];
    for (const path of sources(SRC)) {
      const rel = path.slice(SRC.length + 1).replaceAll("\\", "/");
      if (rel === HOME) continue;
      readFileSync(path, "utf8").split("\n").forEach((line, index) => {
        const code = line.trimStart();
        if (code.startsWith("//") || code.startsWith("*")) return;
        if (RAW.some((pattern) => pattern.test(line))) offenders.push(`${rel}:${index + 1}  ${code}`);
      });
    }
    expect(offenders, "后端时间改走 lib/time.parseServerTime(它补上 Z 再解析)").toEqual([]);
  });
});
