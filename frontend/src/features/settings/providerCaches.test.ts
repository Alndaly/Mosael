import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { invalidateProviderDependents } from "./providerCaches";

describe("供应商连接变了,跟着它走的缓存一起失效", () => {
  it("默认模型的下拉、生成选择器、每个连接的模型列表都不停在旧的那一份", async () => {
    // 此前连接列表(启停、删除)和授权弹窗没让 generation-options 失效:停掉一个连接之后,
    // AI 工作台的模型选择器里还是它的模型,要刷新整页才对。
    const qc = new QueryClient();
    const dependents = [
      ["provider-profiles"],
      ["provider-models", "profile-1"],
      ["provider-defaults"],
      ["capability-models", "image"],
      ["generation-options", "image"],
    ];
    for (const key of dependents) qc.setQueryData(key, []);
    qc.setQueryData(["provider-vendors"], []);

    await invalidateProviderDependents(qc);

    for (const key of dependents) expect(qc.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    expect(qc.getQueryState(["provider-vendors"])?.isInvalidated).toBe(false);
  });
});
