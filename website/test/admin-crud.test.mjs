import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const consoleSource = read("src/components/admin/admin-console.tsx");
const cloud = read("src/lib/cloud.ts");

/** 管理台必须能改公开资料、删用户、删没有引用的套餐。 */
test("管理台有用户资料编辑、用户删除与套餐删除", () => {
  assert.match(cloud, /updateUser: \(id: string/, "客户端没有 updateUser");
  assert.match(cloud, /deleteUser: \(id: string\)/, "客户端没有 deleteUser");
  assert.match(cloud, /deletePlan: \(slug: string\)/, "客户端没有 deletePlan");
  assert.match(consoleSource, /cloudAdmin\.updateUser\(/, "管理台没有保存用户资料");
  assert.match(consoleSource, /cloudAdmin\.deleteUser\(/, "管理台没有删除用户");
  assert.match(consoleSource, /cloudAdmin\.deletePlan\(/, "管理台没有删除套餐");
  assert.match(consoleSource, /copy\.deleteUserConfirm/, "删除用户没有二次确认");
  assert.match(consoleSource, /copy\.deletePlanConfirm/, "删除套餐没有二次确认");
  assert.match(consoleSource, /cloudAdmin\.adjustCredits\(/, "管理台没有增减积分");
  assert.match(consoleSource, /cloudAdmin\.banUser\(/, "管理台没有封禁账号");
  assert.match(consoleSource, /cloudAdmin\.unbanUser\(/, "管理台没有解封账号");
  assert.match(consoleSource, /copy\.banConfirm/, "封禁账号没有二次确认");
  assert.match(cloud, /ipBans: \(\)/, "客户端没有 IP 封禁列表");
  assert.match(consoleSource, /cloudAdmin\.banIp\(/, "管理台没有封禁 IP");
  assert.match(consoleSource, /cloudAdmin\.unbanIp\(/, "管理台没有解除 IP 封禁");
});
