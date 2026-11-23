/**
 * 执行器的平台清单与站点契约(`contracts/platform-contracts.json`)是同一份事实。
 *
 * 登录入口、发布页、标题上限由 `platforms.ts` 直接读契约,类型检查保证执行器认的每个平台在契约里
 * 都有一项;这里再钉住反方向 —— 契约(后端认的平台)里有、执行器却不认的平台,发布任务会落到
 * mock 上静默"成功"。
 */
import { describe, expect, it, vi } from "vitest";

import siteContracts from "../../../contracts/platform-contracts.json";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { PLATFORM_DEFINITIONS, resolvePlatform } = await import("./platforms");

describe("执行器平台清单 = 站点契约", () => {
  it("两边认的平台一样多、一个不差(mock 只在执行器里)", () => {
    const executor = PLATFORM_DEFINITIONS.map((one) => one.id).filter((id) => id !== "mock");
    expect(new Set(executor)).toEqual(new Set(Object.keys(siteContracts.platforms)));
  });

  it("登录入口、发布页、标题上限取的就是契约里那一项", () => {
    for (const [id, site] of Object.entries(siteContracts.platforms)) {
      const definition = resolvePlatform(id);
      expect(definition.id).toBe(id);
      expect(definition.loginUrl).toBe(site.loginUrl);
      expect(definition.publishUrl).toBe(site.publishUrl);
      expect(definition.titleMaxLength).toBe(site.limits.titleMax);
    }
  });
});
