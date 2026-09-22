import { readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import * as client from "@/api/client";
import * as transport from "@/api/transport";

/**
 * `@/api/client` 这个桶要**收全** `api/domains/` 下的每一个模块。
 *
 * 此前它漏了两块:`notes.ts` 和 `scenes.ts` 只能直接 import(实测 22 / 18 处),而
 * `boards` / `assets` / `collaboration` 两条路都有。于是仓库里并存两种 import 约定,
 * 没有一句话说清哪种是对的 —— 新来的人抄哪一处都"对"。
 *
 * 更要命的是**校验这个桶的测试原本是一份手抄清单**:15 个 `import * as`,而 `collaboration`
 * 和 `plugins` 在桶里却不在清单上。新增一个 domain 忘了加进桶、或加进桶忘了加进清单,
 * 都不会红 —— 一份手抄的清单只能证明"抄的时候是对的"。
 *
 * 现在它**读目录**。扫描面跟着 `api/domains/` 自己长,加一个模块这条就立刻问你它进桶了没有。
 */

const DOMAINS = path.resolve(__dirname, "domains");

function domainNames(): string[] {
  return readdirSync(DOMAINS)
    .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
    .map((name) => name.replace(/\.ts$/, ""))
    .sort();
}

const modules = import.meta.glob<Record<string, unknown>>("./domains/*.ts", { eager: true });

function moduleOf(name: string): Record<string, unknown> {
  const found = modules[`./domains/${name}.ts`];
  if (!found) throw new Error(`没加载到 api/domains/${name}.ts`);
  return found;
}

describe("unified API client assembly", () => {
  it("扫描面自己长 —— 读到的模块数和目录对得上", () => {
    // 这条先站住:glob 匹配不到东西的话,下面那些断言会全部天然成立。
    expect(domainNames().length).toBeGreaterThanOrEqual(18);
    expect(Object.keys(modules).sort()).toEqual(domainNames().map((name) => `./domains/${name}.ts`));
  });

  it("re-exports the transport seam", () => {
    expect(client.api).toBe(transport.api);
    expect(client.setAuthToken).toBe(transport.setAuthToken);
  });

  it.each(domainNames())("桶里有 %s 的每一个导出,而且是同一个东西", (name) => {
    const source = moduleOf(name);
    const exported = Object.keys(source).filter((key) => key !== "default");
    // 一个一个导出都没有的模块不该在这儿 —— 多半是文件放错了地方。
    expect(exported.length).toBeGreaterThan(0);
    for (const key of exported) {
      // `toBe` 而不是 `toBeDefined`:两个模块导出同名的东西时,`export *` 在 ESM 里会
      // **静默丢掉**那个名字 —— 而"有这个名字"和"是那个函数"在那时答案不同。
      expect(client[key as keyof typeof client], `client.ts 里的 ${key} 不是 domains/${name} 的那个`)
        .toBe(source[key]);
    }
  });
});
