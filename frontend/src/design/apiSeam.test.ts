/**
 * 棘轮:**接口的路径只写在 `api/domains/*` 里**,而且这个数字只减不增。
 *
 * 界面里现拼 `/api/…` 的代价不是审美:改一个接口要满仓库找字符串,拼错一个只在运行时变成 404,
 * 而返回值是 `any`——加一个字段、改一个名字,编译器一个字都不会说。有名字的函数还顺带把
 * 「这一条要不要带工作区」「查询串怎么编码」收在一处(调度页 8 处手拼路由就是这么收掉的)。
 *
 * 所以这里不是禁止,是**不许再多**:新代码走 `api/domains/*`,存量随手迁一块少一块。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");
//: 存量。**只减不增** —— 迁完一块就把这个数字改小。
const BASELINE = 58;

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (entry === "node_modules" || entry === "api" || entry === "generated") continue;
    if (statSync(path).isDirectory()) out.push(...sources(path));
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(path);
  }
  return out;
}

describe("接口接缝", () => {
  it("界面里现拼的 /api 路径只减不增", () => {
    const raw = /\bapi(<[^>]*>)?\(\s*(`|")\/api\//g;
    let count = 0;
    const worst: [string, number][] = [];
    for (const path of sources(SRC)) {
      const hits = (readFileSync(path, "utf8").match(raw) ?? []).length;
      if (hits) worst.push([path.slice(SRC.length + 1), hits]);
      count += hits;
    }
    worst.sort((a, b) => b[1] - a[1]);
    expect(
      count,
      `现拼路径最多的几处:${worst.slice(0, 5).map(([f, n]) => `${f}(${n})`).join("、")}。` +
        "新代码请加到 api/domains/*;迁完记得把 BASELINE 改小。",
    ).toBeLessThanOrEqual(BASELINE);
  });

  // 绕过 transport 直接 fetch 后端,丢的不只是路径:401 不会登出、掉线不会说「连不上」、
  // 报错体不会被读出来、请求头少了语言和客户端版本。流(SSE)和二进制也各有 transport 的入口
  // (`apiStream`、`apiBlob`),所以这一条是零,不是存量。
  it("界面里没有绕过 transport 直连后端的 fetch", () => {
    const bypass = /\bfetch\(\s*`\$\{API_BASE\}/;
    const offenders = sources(SRC)
      .filter((path) => bypass.test(readFileSync(path, "utf8")))
      .map((path) => path.slice(SRC.length + 1));
    expect(offenders, "改用 api/domains/* 里的函数(底下是 api / apiBlob / apiStream)").toEqual([]);
  });
});
