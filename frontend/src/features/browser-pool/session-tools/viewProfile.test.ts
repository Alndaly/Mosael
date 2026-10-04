/**
 * 前台视图对应的浏览器池档案:按分区认 —— 借登录态下载、用当前档案跑模板都靠它。
 */
import { describe, expect, it } from "vitest";

import { profileForPartition } from "./viewProfile";

describe("档案按分区认", () => {
  const profiles = [
    { id: "p-pool", partition: "persist:pool-p-pool" },
    { id: "p-account", partition: "persist:mosael-acc-1" },
  ] as never[];

  it("池档案、发布账号的档案都按视图的分区认出来", () => {
    expect(profileForPartition(profiles, "persist:pool-p-pool")?.id).toBe("p-pool");
    expect(profileForPartition(profiles, "persist:mosael-acc-1")?.id).toBe("p-account");
  });

  it("RPA 的临时会话、没报分区的视图没有档案", () => {
    expect(profileForPartition(profiles, "ephemeral-rpa-3")).toBeNull();
    expect(profileForPartition(profiles, null)).toBeNull();
    expect(profileForPartition(undefined, "persist:pool-p-pool")).toBeNull();
  });
});

