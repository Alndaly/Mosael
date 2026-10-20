import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 「我的」控制台(/[locale]/dashboard)的契约。
//:
//: 这一个页面要同时做四件事:概览统计、我的分享(能删)、个人信息(能改)、通知空态。
//: 断言分两层:
//:   - **真的跑一遍**纯逻辑(统计求和、删除后剩哪些、tab 归一化、登录回跳),而不是用正则猜;
//:   - 结构层只盯「该在的还在、不该出现的没出现」—— email 只许出现在个人信息那一块,
//:     通知不许编数据,四个 tab 的地址必须能直接打开。
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

const { LOCALES } = await import("../src/i18n/config.ts");
const { getMessages } = await import("../src/i18n/messages.ts");
// cloud.ts 没有 next/headers,可以直接 import:统计求和在真数据上跑。
const { sumShareStats } = await import("../src/lib/cloud.ts");

/** 控制台的纯逻辑;文件还不存在时留空,断言自己给出「还没有」的红,而不是一个 TypeError。 */
let utils = null;
try {
  utils = await import("../src/components/account/dashboard-utils.ts");
} catch {
  utils = null;
}
function dashboardUtils() {
  assert.ok(utils, "还没有 dashboard-utils.ts(四个 tab / 登录回跳 / 删除后剩哪些)");
  return utils;
}

const DASHBOARD_PAGE = "src/app/[locale]/(site)/dashboard/page.tsx";
const ACCOUNT_PAGE = "src/app/[locale]/(auth)/account/page.tsx";
const ACCOUNT_NAV = "src/components/account/account-nav.tsx";
const DASHBOARD_HEADER = "src/components/account/dashboard-header.tsx";
const DASHBOARD_VIEW = "src/components/account/dashboard-view.tsx";
const DASHBOARD_OVERVIEW = "src/components/account/dashboard-overview.tsx";
const DASHBOARD_SHARES = "src/components/account/dashboard-shares.tsx";
const DASHBOARD_PROFILE = "src/components/account/dashboard-profile.tsx";
const DASHBOARD_NOTIFICATIONS = "src/components/account/dashboard-notifications.tsx";

const DASHBOARD_COMPONENTS = [
  DASHBOARD_HEADER,
  DASHBOARD_VIEW,
  DASHBOARD_OVERVIEW,
  DASHBOARD_SHARES,
  DASHBOARD_PROFILE,
  DASHBOARD_NOTIFICATIONS,
];

const shares = {
  three: [
    {
      id: "s1",
      stats: { downloads: 10, likes: 2, favorites: 1, comments: 3 },
    },
    {
      id: "s2",
      stats: { downloads: 4, likes: 5, favorites: 0, comments: 1 },
    },
    {
      id: "s3",
      stats: { downloads: 1, likes: 0, favorites: 7, comments: 6 },
    },
  ],
};

test("① 四个 tab 都在,未登录 307 到 login?next=dashboard", () => {
  assert.ok(exists(DASHBOARD_PAGE), `缺少控制台页面 ${DASHBOARD_PAGE}`);
  const page = read(DASHBOARD_PAGE);

  // 和 upload 页同一套:服务端判断会话,未登录 redirect(307)带 next。
  assert.match(page, /export const dynamic = "force-dynamic"/, "控制台依赖会话,必须是动态页");
  assert.match(page, /redirect\(dashboardLoginHref\(locale\)\)/, "未登录没有 redirect 到带 next 的登录页");
  assert.doesNotMatch(page, /router\.push|useRouter/, "门禁写成了客户端跳转,首屏会先闪一下内容");

  // 私有页:不进搜索索引,但仍然要有 <head>。
  assert.match(page, /export async function generateMetadata/, "控制台没有 generateMetadata");
  assert.match(page, /pageMetadata\(/, "控制台没有走 pageMetadata");
  assert.match(page, /index:\s*false/, "控制台是私有页,应当 noindex");

  const lib = dashboardUtils();
  for (const tab of ["overview", "shares", "profile", "notifications"]) {
    assert.equal(lib.normalizeDashboardTab(tab), tab, `${tab} 不是可识别的 tab`);
    assert.equal(lib.dashboardTabHref("zh", tab), `/zh/dashboard?tab=${tab}`, `${tab} 的地址不对`);
  }
  for (const junk of [undefined, "", "nope", "Overview"]) {
    assert.equal(lib.normalizeDashboardTab(junk), "", `非法 tab ${String(junk)} 没有被忽略`);
  }
  // 地址里重复的 tab 只认第一个(next 的 searchParams 是数组)。
  assert.equal(lib.normalizeDashboardTab(["shares", "profile"]), "shares");
  //: 设备分区已经拆掉:旧书签(甚至 `/account?user_code=` 的转发目标)不再是合法 tab。
  assert.equal(lib.normalizeDashboardTab("devices"), "", "devices 仍然是合法 tab");
  assert.equal(
    lib.dashboardLoginHref("zh"),
    "/zh/login?next=%2Fzh%2Fdashboard",
    "未登录的回跳地址不是 /zh/login?next=/zh/dashboard",
  );
  assert.equal(lib.dashboardLoginHref("en"), "/en/login?next=%2Fen%2Fdashboard");

  // 四个 tab 由同一份清单渲染,地址可直接打开(Link 带 href,不是只换 state)。
  const header = read(DASHBOARD_HEADER);
  assert.match(header, /DASHBOARD_TABS\.map/, "tab 不是从同一份清单渲染的");
  assert.match(header, /href=\{dashboardTabHref\(/, "tab 只有 onClick、没有可打开的地址");
  assert.match(header, /aria-current=\{/, "当前 tab 没有 aria-current");
  for (const tab of ["overview", "shares", "profile", "notifications"]) {
    assert.match(page + read(DASHBOARD_VIEW), new RegExp(tab), `页面没有渲染 ${tab} 分区`);
  }
});

test("② 概览的五个数字 = 分享 stats 求和(不是编的)", () => {
  const total = sumShareStats(shares.three);
  assert.deepEqual(total, { downloads: 15, likes: 7, favorites: 8, comments: 10 }, "求和结果不对");
  assert.equal(sumShareStats([]).downloads, 0, "没有分享时下载数不是 0");
  assert.equal(sumShareStats([]).comments, 0, "没有分享时评论数不是 0");

  // 顺序不影响求和,额外字段也不会被算进去。
  assert.deepEqual(sumShareStats([...shares.three].reverse()), total, "求和依赖顺序");
  assert.deepEqual(
    sumShareStats([{ id: "x", stats: { downloads: 2, likes: 0, favorites: 0, comments: 0 }, title: "t" }]),
    { downloads: 2, likes: 0, favorites: 0, comments: 0 },
  );

  const view = read(DASHBOARD_VIEW);
  const overview = read(DASHBOARD_OVERVIEW);
  assert.match(view, /sumShareStats\(shares\)/, "控制台没有从分享列表求和");
  assert.match(overview, /totals\.downloads/, "概览没有显示总下载");
  assert.match(overview, /totals\.likes/, "概览没有显示总点赞");
  assert.match(overview, /totals\.favorites/, "概览没有显示总收藏");
  assert.match(overview, /totals\.comments/, "概览没有显示总评论");
  assert.match(overview, /shares\.length/, "概览没有显示分享数");
  // 最近 3 条:截断而不是全部。
  assert.match(overview, /\.slice\(0,\s*3\)/, "概览的「最近分享」不是 3 条");
});

test("③ 我的分享:先确认、成功后移除、失败显示后端文案", () => {
  const lib = dashboardUtils();
  const remaining = lib.withoutShare(shares.three, "s2");
  assert.deepEqual(remaining.map((share) => share.id), ["s1", "s3"], "删除后没有就地移除那一条");
  assert.equal(shares.three.length, 3, "withoutShare 改动了原数组");
  assert.equal(lib.withoutShare(shares.three, "missing").length, 3, "删不存在的 id 反而少了一条");

  const panel = read(DASHBOARD_SHARES);
  assert.match(panel, /cloudShares\.remove\(/, "删除没有走 DELETE /shares/{id}");
  assert.match(panel, /confirming/, "删除前没有二次确认");
  assert.match(panel, /onRemoved\(/, "删除成功后没有就地移除");
  assert.match(panel, /failure instanceof CloudApiError \? failure\.text\(locale\)/, "失败没有显示后端文案");
  assert.match(panel, /role="alert"/, "删除失败没有播报区域");
  assert.match(panel, /查看|view/i, "分享行没有「查看」入口");
  assert.match(panel, /localePath\(locale, `\/community\/\$\{/, "「查看」没有指向这条分享");
  assert.match(panel, /localePath\(locale, "\/community\/upload"\)/, "没有分享时没有去上传的入口");
});

test("④ 个人信息:PUT /me,409 两种 handle 冲突都显示后端原话", () => {
  const panel = read(DASHBOARD_PROFILE);
  assert.match(panel, /cloudProfile\.update\(/, "保存没有走 PUT /me");
  // handle_taken / handle_reserved 交给后端文案,不在前端另写一套。
  assert.match(panel, /failure\.code === "handle_taken"/, "没有单独处理 handle_taken");
  assert.match(panel, /failure\.code === "handle_reserved"/, "没有单独处理 handle_reserved");
  assert.match(panel, /failure\.text\(locale\)/, "409 没有原样显示后端文案");
  assert.match(panel, /display_name/, "没有 display_name 字段");
  assert.match(panel, /handle/, "没有 handle 字段");
  assert.match(panel, /InitialTile/, "没有头像预览");
  // 预览和顶栏 / 社区卡片共用 components/community/tile.tsx 的 --tile-* 色相。
  assert.match(read("src/components/community/tile.tsx"), /--tile-/, "色块组件用的不是 --tile-* 那组 token");
  assert.match(panel, /signOut|signingOut/, "个人信息里没有退出登录");

  // 硬要求:email 只许出现在「个人信息」那一块(注释里提到不算)。
  const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  for (const relative of [
    ...DASHBOARD_COMPONENTS,
    "src/components/account/dashboard-name-prompt.tsx",
    DASHBOARD_PAGE,
    "src/components/account/dashboard-utils.ts",
  ]) {
    if (!exists(relative)) continue;
    const source = stripComments(read(relative));
    if (/email/i.test(source)) {
      assert.equal(relative, DASHBOARD_PROFILE, `${relative} 里出现了 email,它只该在个人信息里显示本人那一处`);
    }
  }

  for (const locale of LOCALES) {
    const copy = getMessages(locale).dashboard;
    for (const key of ["displayName", "handle", "save", "saving", "saved", "email", "signOut"]) {
      assert.ok(copy[key], `${locale} 缺 dashboard.${key}`);
    }
  }
});

test("⑤ 设备绑定整体移除:没有设备分区;/account 收成跳转,删除账号在控制台", () => {
  // 云端设备绑定已经拆掉(cloud /devices、/device/* 都不存在了),控制台不再有设备分区。
  assert.ok(!exists("src/components/account/dashboard-devices.tsx"), "设备分区组件还在");
  for (const relative of [DASHBOARD_HEADER, DASHBOARD_VIEW, DASHBOARD_PAGE]) {
    assert.doesNotMatch(read(relative), /devices?\b/i, `${relative} 仍然提到设备`);
  }
  assert.doesNotMatch(read("src/components/account/dashboard-utils.ts"), /devices/, "tab 清单里还有 devices");
  assert.doesNotMatch(read("src/lib/cloud.ts"), /devices|revokeDevice|approveDevice/, "cloud 客户端还在调设备接口");

  // /account 只剩一个永久跳转(路由仍在 (auth) 组,地址不拆);不再处理桌面绑定带来的 user_code。
  assert.ok(exists(ACCOUNT_PAGE), "/account 被删了,旧地址与第三方回调会断");
  const page = read(ACCOUNT_PAGE);
  assert.match(page, /permanentRedirect\(/, "/account 还没有收敛成跳转");
  assert.match(page, /\/\$\{locale\}\/dashboard/, "/account 没有跳到控制台");
  assert.doesNotMatch(page, /user_code|tab=devices/, "/account 还在处理设备绑定回跳");

  // 登录回跳与删号都搬到了控制台:登录表单仍固定去 /account,由它的 308 落到这里。
  assert.match(read(DASHBOARD_PAGE), /ResumeLoginReturn/, "登录后回跳没有搬到控制台");
  assert.match(read(DASHBOARD_PROFILE), /<AccountDangerZone/, "「个人信息」底部没有接上删除账号");
});

test("⑥ 通知接上云端列表(空态仍是零条分支、不造假),没有 handle 时个人信息高亮", () => {
  const zh = getMessages("zh").dashboard;
  const en = getMessages("en").dashboard;
  assert.equal(
    zh.notificationsEmpty,
    "还没有通知。有人评论或点赞你的分享时会出现在这里。",
    "通知空态不是约定的那句话",
  );
  assert.ok(en.notificationsEmpty.length > 0, "英文通知空态是空的");

  const panel = read(DASHBOARD_NOTIFICATIONS);
  assert.match(panel, /notificationsEmpty/, "通知分区没有用空态文案");
  assert.doesNotMatch(panel, /即将上线|敬请期待|coming soon|coming_soon|还在做|TODO/i, "通知写了「即将上线」之类的话");
  // 列表的数据只能来自云端:走的是和 cloudShares 并列的 cloudNotifications,不造假条目、不拉别的接口。
  // 取数在 lib/queries.ts 的 useNotifications 里,分区只消费 hook。
  assert.match(read("src/lib/queries.ts"), /cloudNotifications\.list\(/, "通知取数没有接 /notifications");
  assert.match(panel, /useNotifications\(/, "通知分区没有用 useNotifications");
  assert.match(panel, /\.map\(/, "通知分区没有渲染条目");
  assert.doesNotMatch(panel, /cloudShares|cloudAccount/, "通知分区在拉不属于它的接口");
  assert.doesNotMatch(panel, /display_name:\s*"/, "通知分区写死了假数据");

  const lib = dashboardUtils();
  assert.equal(lib.defaultDashboardTab(false), "profile", "没有 handle 时没有默认停在个人信息");
  assert.equal(lib.defaultDashboardTab(true), "overview", "有 handle 时默认不是概览");

  const page = read(DASHBOARD_PAGE);
  assert.match(page, /defaultDashboardTab\(/, "页面没有按「有没有 handle」决定首屏 tab");
  const view = read(DASHBOARD_VIEW);
  assert.match(view, /hasHandle=\{hasHandle\}/, "分区没有拿到「有没有 handle」");
  const prompt = read("src/components/account/dashboard-name-prompt.tsx");
  assert.match(prompt, /noHandleTitle/, "没有一句「先起个名字」");
  assert.match(prompt, /noHandleBody/, "没有说明为什么要先起名字");
  assert.match(prompt, /goToProfile/, "没有去个人信息起名的入口");
  // 没有 handle 时概览不空着:那里换成的就是这句提示,不是一屏 0。
  assert.match(read(DASHBOARD_OVERVIEW), /NamePrompt/, "没有 handle 时概览是空的");
  assert.match(read(DASHBOARD_SHARES), /NamePrompt/, "没有 handle 时我的分享是空的");
});

test("⑦ 顶栏头像进新控制台,不再去 /account", () => {
  const nav = read(ACCOUNT_NAV);
  assert.match(nav, /href=\{`\/\$\{locale\}\/dashboard`\}/, "顶栏头像没有指向 /[locale]/dashboard");
  assert.doesNotMatch(nav, /href=\{`\/\$\{locale\}\/account`\}/, "顶栏头像还在去 /account");
  // 未登录那颗「登录」按钮不受影响。
  assert.match(nav, /\/\$\{locale\}\/login/);
});

test("⑧ 文案中英同键;控制台不写第二套 fetch", () => {
  const zh = getMessages("zh").dashboard;
  const en = getMessages("en").dashboard;
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort(), "中英 dashboard 文案键不一致");
  for (const key of [
    "title",
    "tabOverview",
    "tabShares",
    "tabProfile",
    "tabNotifications",
    "sharesCount",
    "totalDownloads",
    "totalLikes",
    "totalFavorites",
    "totalComments",
    "recentShares",
    "noShares",
    "notificationsEmpty",
    "noHandleTitle",
    "noHandleBody",
    "goToProfile",
  ]) {
    assert.ok(zh[key], `中文缺 dashboard.${key}`);
    assert.ok(en[key], `英文缺 dashboard.${key}`);
  }

  for (const relative of DASHBOARD_COMPONENTS) {
    assert.ok(exists(relative), `缺少 ${relative}`);
    const source = read(relative);
    assert.doesNotMatch(source, /\bfetch\s*\(/, `${relative} 自己写了一套 fetch`);
  }
  const page = read(DASHBOARD_PAGE);
  assert.doesNotMatch(page, /\bfetch\s*\(/, "页面自己写了一套 fetch");
  assert.match(page, /loadViewer/, "页面没有复用会话读取");
  assert.match(page, /loadUserShares/, "页面没有复用按人列分享的服务端取数");
});
