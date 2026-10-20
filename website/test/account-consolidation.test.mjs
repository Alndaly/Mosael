import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 账号页并进控制台之后的契约(维护者:「为何系统账号只有这么一个页面 应该和普通账号一样支持
//: 所有操作 不过注意 账号类型应该要在合适位置补充对应 badge 信息」)。
//:
//:  ① 控制台「个人信息」底部有危险区:删号走 `DELETE /me`,两次点击才真的删;删完
//:     viewer / unread / notifications / sharesByMe 全部失效,再回首页(站头立刻变成「登录」)。
//:     —— 这里用只记录调用的桩 QueryClient **真的跑一遍** invalidation,不看注释。
//:  ② `/account` 只剩一个永久跳转,页脚改指控制台,但路由仍留在 `(auth)` 组(地址不拆)。
//:  ③ 官方账号在控制台页头带「官方」徽标 —— 与分享卡片同一枚(BadgeCheck + 同一个词);
//:     普通账号不带。仓库里没有 JSX 运行器,组件看源码结构,判断逻辑真的跑一遍。
//:
//: 「先红后绿」:这份文件是在实现之前写的 —— 缺文件 / 缺函数 / 缺跳转时,下面的断言先红。
const ROOT = path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "src");

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) {
      return nextResolve(pathToFileURL(path.join(SRC, `${specifier.slice(2)}.ts`)).href, context);
    }
    if (/^\.\.?\//.test(specifier) && !path.extname(specifier) && context.parentURL?.includes("/src/")) {
      return nextResolve(`${specifier}.ts`, context);
    }
    return nextResolve(specifier, context);
  },
});

const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const exists = (relative) => fs.existsSync(path.join(ROOT, relative));

/** 缺文件时红在「缺少……」上,而不是一个 ENOENT。 */
function readSource(relative) {
  assert.ok(exists(relative), `缺少 ${relative}`);
  return read(relative);
}

const ACCOUNT_PAGE = "src/app/[locale]/(auth)/account/page.tsx";
const DASHBOARD_PAGE = "src/app/[locale]/(site)/dashboard/page.tsx";
const DASHBOARD_VIEW = "src/components/account/dashboard-view.tsx";
const DASHBOARD_HEADER = "src/components/account/dashboard-header.tsx";
const DASHBOARD_PROFILE = "src/components/account/dashboard-profile.tsx";
const DANGER_ZONE = "src/components/account/account-danger-zone.tsx";
const FOOTER = "src/components/site-footer.tsx";

const { LOCALES } = await import("../src/i18n/config.ts");
const { getMessages } = await import("../src/i18n/messages.ts");

test("① 控制台个人信息底部有危险区:说清不可恢复 + 二次确认 + DELETE /me", () => {
  const profile = readSource(DASHBOARD_PROFILE);
  assert.match(profile, /<AccountDangerZone/, "「个人信息」底部没有危险区");

  const zone = readSource(DANGER_ZONE);
  // 形态照搬 `(auth)/account` 那一块:同一套警告配色与图标,不是自己发明的一版。
  assert.match(zone, /border-destructive\/25/, "危险区没有沿用账号页的警告描边");
  assert.match(zone, /bg-destructive\/\[0\.04\]/, "危险区没有沿用账号页的警告底色");
  assert.match(zone, /ShieldAlert/, "危险区没有沿用账号页的警示图标");
  assert.match(zone, /copy\.dangerZone/, "危险区没有标题");
  assert.match(zone, /copy\.deleteConfirm/, "没有说清「删除后不能恢复」");
  assert.match(zone, /copy\.deleteAccount/, "没有「删除账号」按钮");
  assert.match(zone, /confirming/, "删除前没有二次确认");
  assert.match(zone, /cloudAccount\.deleteAccount\(/, "删除没有走 DELETE /me");
});

test("① 删号后 viewer / unread / notifications / sharesByMe 失效,并跳首页(桩断言)", async () => {
  const { invalidateAfterSignOut } = await import("../src/lib/query-invalidation.ts");
  const { queryKeys } = await import("../src/lib/queryKeys.ts");

  // 桩:只记录收到了哪些 key,和 `lib/query-invalidation.ts` 的 `InvalidationClient` 同形。
  const calls = [];
  await invalidateAfterSignOut({
    invalidateQueries: async ({ queryKey }) => {
      calls.push(JSON.stringify(queryKey));
    },
  });
  for (const [label, key] of [
    ["viewer", queryKeys.viewer()],
    ["unread", queryKeys.unread()],
    ["notifications", queryKeys.notifications()],
    ["sharesByMe", queryKeys.sharesByMe()],
  ]) {
    assert.ok(calls.includes(JSON.stringify(key)), `删号后没有让 ${label} 失效,收到的是 ${calls.join(" / ")}`);
  }

  const zone = readSource(DANGER_ZONE);
  assert.match(
    zone,
    /cloudAccount\.deleteAccount\([\s\S]{0,600}?invalidateAfterSignOut\(queryClient\)/,
    "删除请求回来了,却没有让站头 / 角标 / 通知 / 我的分享失效",
  );
  assert.match(zone, /router\.push\(`\/\$\{locale\}`\)/, "删号后没有回首页");

  // 官方号也是它自己的账号:不按账号类型加闸。
  assert.doesNotMatch(zone, /official/i, "删号按账号类型做了特殊对待");
});

test("② /account 收敛成永久跳转,路由仍留在 (auth) 组", () => {
  assert.ok(exists(ACCOUNT_PAGE), "/account 路由被删了 —— 地址要保留");
  const page = readSource(ACCOUNT_PAGE);
  assert.match(page, /permanentRedirect\(/, "/account 不是永久跳转(用户说 permanent 也接受,但要说明理由)");
  assert.match(page, /`\/\$\{locale\}\/dashboard/, "/account 没有跳到控制台");
  assert.doesNotMatch(page, /AccountShell|AccountView/, "/account 还在画账号页");

  // 登录表单仍固定去 /account(由它 308 过来),「登录后回到刚才那一页」得在控制台接住。
  assert.match(readSource(DASHBOARD_PAGE), /ResumeLoginReturn/, "登录回跳没有在控制台落地");
});

test("② 页脚「账号」改指控制台", () => {
  const footer = readSource(FOOTER);
  assert.match(
    footer,
    /t\.account\.account,\s*href:\s*localePath\(locale,\s*"\/dashboard"\)/,
    "页脚「账号」没有指到 /dashboard",
  );
  assert.doesNotMatch(footer, /localePath\(locale,\s*"\/account"\)/, "页脚还在指 /account");
});

test("③ 官方账号显示「官方」徽标,普通账号不显示", async () => {
  // 逻辑真的跑一遍:只有 `official === true`(云端 `public_user()` 的布尔值)才算官方。
  const utils = await import("../src/components/account/dashboard-utils.ts");
  assert.equal(typeof utils.showsOfficialBadge, "function", "dashboard-utils 里还没有「是不是官方账号」的判断");
  assert.equal(utils.showsOfficialBadge({ official: true }), true, "官方账号没有被认出来");
  for (const ordinary of [{ official: false }, {}, null, undefined, { official: undefined }]) {
    assert.equal(utils.showsOfficialBadge(ordinary), false, `普通账号被当成了官方:${JSON.stringify(ordinary)}`);
  }

  const header = readSource(DASHBOARD_HEADER);
  assert.match(header, /showsOfficialBadge\(/, "页头没有按 official 决定要不要画徽标");
  // 视觉语言照分享卡片那枚:同一个 BadgeCheck、同一句 community.official。
  assert.match(header, /BadgeCheck/, "官方徽标没有沿用分享卡片的 BadgeCheck 图标");
  assert.match(header, /getMessages\(locale\)\.community\.official/, "官方徽标没有复用社区里那枚「官方」的文字");
  assert.match(header, /aria-hidden/, "徽标的图标没有对读屏隐藏(读屏只该念文字「官方」)");
  // 徽标是「文字」不是纯图标,而且排在名字之后:读屏按自然顺序念「名字 官方」。
  assert.match(header, /\{officialLabel\}/, "徽标里没有文字,只是纯图标");
  assert.match(header, /identity\?\.display_name[\s\S]*\{officialLabel\}/, "徽标没有排在名字之后");

  const view = readSource(DASHBOARD_VIEW);
  assert.match(view, /identity=\{currentViewer\}/, "控制台页头没有拿到当前身份(官方标记来自 /me)");
});

test("④ 只给账号页用的 account* 文案键删掉了(中英同删)", () => {
  // 删之前逐条 grep 过:这些键的唯一使用者是 `(auth)/account` 页与 `account-view.tsx`。
  const DELETED = [
    "accountTitle",
    "accountSeoTitle",
    "accountLede",
    "dangerZone",
    "deleteAccount",
    "deleteConfirm",
    "deleteYes",
    "cancel",
    "deleting",
    "loading",
    "loginRequired",
    "retry",
    "signedInLabel",
    "accountIdentity",
    "loadFailed",
    "signOut",
    "signingOut",
    "emailVerified",
  ];
  for (const locale of LOCALES) {
    const copy = getMessages(locale).account;
    for (const key of DELETED) {
      assert.equal(copy[key], undefined, `${locale} 的 account.${key} 已经没人用了,还留在 messages.ts`);
    }
  }

  // 还有人用的不能顺手删。`account` 是页脚那一项,`OAuth*` 仍由登录结果的 toast 使用。
  for (const locale of LOCALES) {
    const copy = getMessages(locale).account;
    for (const key of ["account", "loginTitle", "signupTitle", "actionFailed", "formErrorTitle", "backToSite", "oauthCreated", "oauthExisting"]) {
      assert.ok(copy[key], `${locale} 的 account.${key} 还有人用,被误删了`);
    }
  }

  // 危险区那几句话搬进了控制台文案。
  for (const locale of LOCALES) {
    const copy = getMessages(locale).dashboard;
    for (const key of ["dangerZone", "deleteAccount", "deleteConfirm"]) {
      assert.ok(copy[key], `${locale} 缺 dashboard.${key}`);
    }
  }
});
