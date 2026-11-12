import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const consoleSource = read("src/components/admin/admin-console.tsx");
const messages = read("src/i18n/messages.ts");

/**
 * 管理台有自己的侧栏，不继承公开站点的 AccountNav；退出入口必须和 dashboard 一样
 * 出现在账号块下面，而不是只能回到个人控制台才能退出。
 */
test("管理台侧栏有退出登录、清缓存并回到登录页", () => {
  assert.match(consoleSource, /cloudAccount\.logout\(/, "管理台没有调用退出接口");
  assert.match(consoleSource, /invalidateAfterSignOut\(queryClient\)/, "退出后没有清 viewer / 未读缓存");
  assert.match(consoleSource, /router\.push\(`\/\$\{locale\}\/login`\)/, "退出后没有回到登录页");
  assert.match(consoleSource, /copy\.signOut/, "管理台没有退出文案");
  assert.match(consoleSource, /copy\.signingOut/, "管理台没有退出中状态");
  assert.match(consoleSource, /<LogOut\b/, "管理台退出入口没有图标");
  assert.match(messages, /adminFallback: "管理员",\n\s+signOut: "退出登录"/, "中文 admin 文案缺少 signOut");
  assert.match(messages, /adminFallback: "Admin",\n\s+signOut: "Sign out"/, "英文 admin 文案缺少 signOut");
});
