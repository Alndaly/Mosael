/**
 * 后端时间戳**只在 `lib/time.parseServerTime` 一处**补时区。
 *
 * 后端给的是 UTC、不带时区标记的 ISO 串,直接 `new Date()` 会被当成本地时间。「补 Z」这一行曾在
 * 十三个文件里各抄一份,其中工作流执行历史那份写成 `endsWith("Z") || includes("+")`:遇到
 * `-05:00` 这种负偏移会再补一个 Z,解析成 Invalid Date。这里钉住行为,并拦下一处再手写。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { elapsedSecondsBetween, formatTimecode, parseServerTime } from "@/lib/time";

const SRC = join(import.meta.dirname, "..");
const OWNER = join(SRC, "lib", "time.ts");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "generated" ? [] : sourceFiles(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

describe("parseServerTime", () => {
  it("没有时区标记的按 UTC 读", () => {
    expect(parseServerTime("2026-09-28T08:00:00").toISOString()).toBe("2026-09-28T08:00:00.000Z");
  });

  it("已带 Z 或偏移的原样读,负偏移也不再补 Z", () => {
    expect(parseServerTime("2026-09-28T08:00:00Z").toISOString()).toBe("2026-09-28T08:00:00.000Z");
    expect(parseServerTime("2026-09-28T08:00:00+08:00").toISOString()).toBe("2026-09-28T00:00:00.000Z");
    expect(parseServerTime("2026-09-28T08:00:00-05:00").toISOString()).toBe("2026-09-28T13:00:00.000Z");
  });

  it("耗时按同一规则算两端", () => {
    expect(elapsedSecondsBetween("2026-09-28T08:00:00", "2026-09-28T08:00:30Z")).toBe(30);
  });
});

describe("formatTimecode", () => {
  it("MM:SS.d", () => {
    expect(formatTimecode(0)).toBe("00:00.0");
    expect(formatTimecode(75.26)).toBe("01:15.2");
    expect(formatTimecode(-1.5)).toBe("-00:01.5");
  });
});

describe("补时区只有一处", () => {
  it("别处不再手写「补 Z」", () => {
    const offenders = sourceFiles(SRC)
      .filter((path) => path !== OWNER)
      .filter((path) => /\}Z`|\+ ?["']Z["']/.test(readFileSync(path, "utf8")))
      .map((path) => path.slice(SRC.length + 1));
    expect(offenders, "读后端时间戳用 lib/time 的 parseServerTime").toEqual([]);
  });
});
