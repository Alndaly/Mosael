/**
 * 删一条**已经发出去**的发布记录,警告要说清后果。
 *
 * 起因:用户问「发布记录呢」——库里 20 条 publish 任务(YouTube 4、TikTok 4、小红书 7…)的
 * job 都还在,而对应的发布记录一条不剩,首页于是只统计到更早的 13 条 B 站记录。查下来删除只有
 * 「用户主动点删除」这一条路,没有任何自动删除。
 *
 * 也就是说这条路走得太顺了:确认框写的是「已产出的文件不受影响」——说的是本地文件,而真正该说
 * 的是**平台上的内容不会被撤下,但你自己那本账没了**。已发布的记录是一份对外行为的账,和一条
 * 失败重试记录不是一回事。
 */
import { describe, expect, it } from "vitest";

import { deleteWarningKey } from "./publishDeleteWarning";

describe("删除发布记录的警告", () => {
  it("已发出去的那条要说清「平台上撤不下来,账没了」", () => {
    expect(deleteWarningKey(["success"])).toBe("publishDeleteBodyPublished");
  });

  it("批量删时只要有一条发过就按发过警告 —— 顺手删最容易把成功记录一起带走", () => {
    expect(deleteWarningKey(["failed", "cancelled", "success"])).toBe("publishDeleteBodyPublished");
  });

  it("全是失败 / 取消时不吓唬人 —— 每条警告都当真,前提是它不滥用", () => {
    expect(deleteWarningKey(["failed", "cancelled", "pending"])).toBe("publishDeleteBody");
    expect(deleteWarningKey([])).toBe("publishDeleteBody");
  });
});
