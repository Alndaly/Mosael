/**
 * 棘轮:**底下那几层不许认识功能模块**。
 *
 * `components/`(通用件与外壳)、`lib/`、`api/`、`stores/` 是给所有功能用的;它们一旦 import
 * `features/…`,方向就反了 —— 改一个功能会把外壳拖下水,而"这个通用件到底通不通用"再也说不清。
 * 审查时找到四处:任务详情弹窗认识工作流的失败详情、确认卡中心认识智能体、接口层认识 3D 场景的
 * 渲染类型,以及整整一个 `components/agent/`(它其实就是智能体这个功能本身)。
 *
 * 唯一的组合根是 `app/` —— 那里 import 谁都可以,页面装配本来就是它的活。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");
//: 除了 app/(组合根)和 features/ 自己。
const LOWER_LAYERS = ["components", "lib", "api", "stores", "design"];

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) out.push(...sources(path));
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(path);
  }
  return out;
}

describe("分层", () => {
  it("components / lib / api / stores 不 import features", () => {
    const offenders: string[] = [];
    for (const layer of LOWER_LAYERS) {
      for (const path of sources(join(SRC, layer))) {
        const text = readFileSync(path, "utf8");
        for (const match of text.matchAll(/from "(@\/features\/[^"]+)"/g)) {
          offenders.push(`${path.slice(SRC.length + 1)} → ${match[1]}`);
        }
      }
    }
    expect(offenders, "把它挪进对应的 feature,或者把通用的那部分留在 components").toEqual([]);
  });
});
