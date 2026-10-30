import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 官网的 TanStack Query 契约。
//:
//: 这一单修的是「改了昵称 / 头像,站头不刷新」:站头原先在挂载时用 useEffect 问一次
//: `/me` 与 `unread-count`,之后再也没有人通知它。现在全站只有一份查询缓存,改资料 / 退出
//: 登录 / 标已读都经 `invalidateQueries` 指名刷新 —— 这里盯住四件事:
//:
//:   ① 库与 Provider 真的在(`package.json` + [locale] 根布局的 client wrapper),默认值有理由;
//:   ② 查询键只在 `lib/queryKeys.ts` 定义,业务代码不写裸数组;
//:   ③ 站头 / 个人页 / 通知列表不再是 useEffect 取数,而是 hook;
//:   ④ **真的跑一遍** invalidation:保存资料、退出登录、改分享、标已读都收到预期的键。
//:
//: 仓库里没有 JSX 运行器,所以纯逻辑模块(`queryKeys` / `query-invalidation` / `query-client`)
//: 直接 import 跑;组件仍看源码结构。
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
const sourceUrl = (relative) => pathToFileURL(path.join(SRC, relative)).href;

/** 去掉注释再看:注释里说「不再用 useEffect」不算实现。 */
const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

/** 导入一个源码里的纯 .ts 模块;文件还没写时红在「缺少」上,而不是一个 ERR_MODULE_NOT_FOUND。 */
async function importSource(relative) {
  const file = path.join(SRC, relative);
  assert.ok(fs.existsSync(file), `缺少 ${path.join("src", relative)}`);
  return import(sourceUrl(relative));
}

const walk = (dir) =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });

const PKG = JSON.parse(read("package.json"));
const LAYOUT = "src/app/[locale]/layout.tsx";
const PROVIDER = "src/app/[locale]/query-provider.tsx";
const QUERY_KEYS = "src/lib/queryKeys.ts";
const QUERY_CLIENT = "src/lib/query-client.ts";
const INVALIDATION = "src/lib/query-invalidation.ts";
const QUERIES = "src/lib/queries.ts";
const NAV = "src/components/account/account-nav.tsx";
const PROFILE = "src/components/account/dashboard-profile.tsx";
const NOTIFICATIONS = "src/components/account/dashboard-notifications.tsx";
const ACCOUNT_PAGE = "src/app/[locale]/(auth)/account/page.tsx";
const DANGER_ZONE = "src/components/account/account-danger-zone.tsx";
const LOGIN = "src/components/account/login-form.tsx";
const SIGNUP = "src/components/account/signup-form.tsx";
const BROWSE = "src/components/community/browse.tsx";
const UPLOAD = "src/components/community/upload-form.tsx";
const IDENTITY = "src/components/community/identity-form.tsx";
const SHARES_PANEL = "src/components/account/dashboard-shares.tsx";

/** 打桩的 QueryClient:只记下每次 invalidateQueries 收到的键。 */
function stubClient() {
  const calls = [];
  const removals = [];
  return {
    calls,
    removals,
    invalidateQueries(filters) {
      calls.push(filters.queryKey);
      return Promise.resolve();
    },
    removeQueries(filters) {
      removals.push(filters.queryKey);
    },
  };
}

test("① 装了 @tanstack/react-query,Provider 挂在能盖住 (site) 与 (auth) 的根布局上", async () => {
  assert.ok(PKG.dependencies["@tanstack/react-query"], "website/package.json 里没有 @tanstack/react-query");

  assert.ok(exists(PROVIDER), `缺少 ${PROVIDER}([locale] 根布局的 client wrapper)`);
  const provider = read(PROVIDER);
  assert.match(provider, /^"use client";/m, "query-provider 不是 client component");
  assert.match(provider, /QueryClientProvider/, "client wrapper 里没有 QueryClientProvider");
  assert.match(provider, /createQueryClient/, "Provider 没有从 lib/query-client 取同一个工厂");
  assert.ok(exists(QUERY_CLIENT), `缺少 ${QUERY_CLIENT}`);

  const layout = read(LAYOUT);
  assert.doesNotMatch(layout, /^"use client";/m, "根布局被改成了 client component(SC 的 metadata / generateStaticParams 会丢)");
  assert.match(layout, /import \{ QueryProvider \} from "\.\/query-provider"/, "根布局没有引入 QueryProvider");
  assert.match(layout, /<QueryProvider>/, "根布局没有挂 QueryProvider");
  // 必须包住两组页面共用的东西(toast / skip link 都在这一层):Provider 在 <body> 里、children 外层。
  assert.ok(layout.indexOf("<QueryProvider>") < layout.indexOf("{children}"), "QueryProvider 没有包住 children");
});

test("① 默认值写清理由:staleTime / refetchOnWindowFocus / retry(401 不重试)", async () => {
  const source = read(QUERY_CLIENT);
  assert.match(source, /staleTime:/, "没有设置 staleTime(每次挂载都会重拉)");
  assert.match(source, /refetchOnWindowFocus:\s*true/, "没有从后台回来时刷新登录态");
  assert.match(source, /retry:/, "没有设置 retry 策略");
  // 理由要写进代码,不能只有数字。
  assert.match(source, /staleTime[\s\S]{0,200}(切页|重拉|重复)/, "staleTime 没有写清楚为什么");
  assert.match(source, /refetchOnWindowFocus[\s\S]{0,200}(登录态|站头|后台)/, "refetchOnWindowFocus 没有写清楚为什么");
  assert.match(source, /retry[\s\S]{0,200}401/, "retry 没有写清楚 401 为什么不重试");

  const { createQueryClient, retryUnlessUnauthorized } = await importSource("lib/query-client.ts");
  const client = createQueryClient();
  const queries = client.getDefaultOptions().queries ?? {};
  assert.ok(Number(queries.staleTime) > 0, "默认 staleTime 不是正数");
  assert.equal(queries.refetchOnWindowFocus, true, "默认 refetchOnWindowFocus 不是 true");
  assert.equal(typeof queries.retry, "function", "默认 retry 不是一个按错误判断的函数");

  const { CloudApiError } = await importSource("lib/cloud.ts");
  const unauthorized = new CloudApiError("unauthorized", { en: "no", zh: "没登录" }, 401);
  const serverError = new CloudApiError("boom", { en: "boom", zh: "炸了" }, 500);
  assert.equal(retryUnlessUnauthorized(0, unauthorized), false, "401 被安排重试了(重试一万次也不会变成已登录)");
  assert.equal(retryUnlessUnauthorized(0, serverError), true, "5xx 第一次就不重试,偶发故障会直接变成错误态");
  assert.equal(retryUnlessUnauthorized(2, serverError), false, "5xx 重试没有上限");
  // QueryClient 也认这条策略(不是只有导出函数里写着)。
  const retry = queries.retry;
  assert.equal(retry(0, unauthorized), false, "QueryClient 的默认 retry 没有挡住 401");
});

test("② 查询键只在 lib/queryKeys.ts 定义:业务代码里没有裸数组键", async () => {
  assert.ok(exists(QUERY_KEYS), `缺少 ${QUERY_KEYS}`);
  const keys = await importSource("lib/queryKeys.ts");
  assert.ok(keys.queryKeys, "queryKeys 没有导出");

  // 每个键一处定义;拼出来的是可读的数组,不是散落在组件里的字符串。
  assert.deepEqual(keys.queryKeys.viewer(), ["viewer"]);
  assert.deepEqual(keys.queryKeys.profile(), keys.queryKeys.viewer(), "个人页另开了一份 /me 缓存(同一份数据应当只有一个来源)");
  assert.deepEqual(keys.queryKeys.unread(), ["notifications", "unread"]);
  assert.deepEqual(keys.queryKeys.notifications(), ["notifications", "list"]);
  assert.deepEqual(keys.queryKeys.sharesByMe("ada"), ["shares", "by-me", "ada"]);
  assert.deepEqual(keys.queryKeys.sharesByMe(), ["shares", "by-me"], "my-shares 没有分组键,改资料时无法一次刷掉所有 handle 的那份");
  assert.deepEqual(keys.queryKeys.shareList("workflow"), ["shares", "list", "workflow"]);
  assert.deepEqual(keys.queryKeys.shareList(), ["shares", "list"], "列表没有分组键,删分享时无法按 kind 刷新");

  const files = walk(SRC).filter((file) => /\.(ts|tsx)$/.test(file));
  const offenders = [];
  for (const file of files) {
    const relative = path.relative(ROOT, file);
    if (relative === QUERY_KEYS) continue;
    const text = fs.readFileSync(file, "utf8");
    // queryKey: ["..."] / queryKey: [`...`] —— 裸字面量键;键必须经 queryKeys。
    if (/queryKey:\s*\[/.test(text)) offenders.push(`${relative}: queryKey 直接写数组`);
    if (/invalidateQueries\(\s*\{\s*queryKey:\s*\[/.test(text)) offenders.push(`${relative}: invalidateQueries 直接写数组`);
  }
  assert.deepEqual(offenders, [], `业务代码里出现了裸字符串键:\n${offenders.join("\n")}`);

  // QueryClient 也只在工厂里 new 一次,组件里不许各建一个。
  const clientOwners = files
    .filter((file) => path.relative(ROOT, file) !== QUERY_CLIENT && /new QueryClient\(/.test(fs.readFileSync(file, "utf8")))
    .map((file) => path.relative(ROOT, file));
  assert.deepEqual(clientOwners, [], `QueryClient 在 ${clientOwners.join(", ")} 里又 new 了一次`);
});

test("③ 站头 / 个人页 / 通知改成了 hook;账号页只剩跳转", async () => {
  assert.ok(exists(QUERIES), `缺少 ${QUERIES}(useViewer / useUnreadCount / useMyShares / useNotifications)`);
  const queries = read(QUERIES);
  for (const hook of ["useViewer", "useUnreadCount", "useMyShares", "useNotifications"]) {
    assert.match(queries, new RegExp(`export function ${hook}\\(`), `lib/queries.ts 里没有 ${hook}`);
  }
  assert.match(queries, /queryKey: queryKeys\.viewer\(\)/, "useViewer 没有用集中定义的 viewer 键");
  assert.match(queries, /queryKey: queryKeys\.unread\(\)/, "useUnreadCount 没有用集中定义的 unread 键");
  assert.match(queries, /infiniteQuery|useInfiniteQuery/, "通知列表没有按页取(游标翻页丢了)");

  const nav = read(NAV);
  assert.match(nav, /import \{[^}]*useViewer[^}]*\} from "@\/lib\/queries"/, "站头没有用 useViewer");
  assert.match(nav, /import \{[^}]*useUnreadCount[^}]*\} from "@\/lib\/queries"/, "站头没有用 useUnreadCount");
  assert.doesNotMatch(stripComments(nav), /useEffect/, "站头还在用 useEffect 取数(改了昵称/头像后不会刷新)");
  assert.doesNotMatch(stripComments(nav), /cloudAccount\.me\(/, "站头还在自己问 /me");
  assert.doesNotMatch(stripComments(nav), /cloudNotifications\.unreadCount\(/, "站头还在自己问 unread-count");

  const profile = read(PROFILE);
  assert.match(profile, /useViewer\(\)/, "个人页没有读 useViewer()");
  assert.doesNotMatch(stripComments(profile), /useEffect/, "个人页还在用 useEffect 问 /me(和站头成了两份数据)");

  const notifications = read(NOTIFICATIONS);
  assert.match(notifications, /useNotifications\(/, "通知分区没有用 useNotifications");
  assert.doesNotMatch(stripComments(notifications), /useEffect/, "通知分区还在用 useEffect 取列表");
  assert.doesNotMatch(stripComments(notifications), /cloudNotifications\.list\(/, "通知分区还留着手写取数");

  // 账号页已经收成永久跳转:它自己不该再取任何身份数据(取数只在控制台那一侧)。
  const account = stripComments(read(ACCOUNT_PAGE));
  assert.doesNotMatch(account, /useViewer\(|useEffect|cloudAccount\.me\(/, "账号页跳转还在自己问 /me");
  assert.match(account, /permanentRedirect\(/, "账号页没有收敛成跳转");

  for (const [name, relative] of [
    ["登录", LOGIN],
    ["注册", SIGNUP],
  ]) {
    assert.match(read(relative), /invalidateAfterAuth\(/, `${name}成功后没有刷新 viewer(登录后站头还是「登录」)`);
  }
});

test("④ 保存资料 → invalidate viewer(站头首字母 / 色块 / aria-label 跟着变)", async () => {
  assert.ok(exists(INVALIDATION), `缺少 ${INVALIDATION}(改完资料该刷哪几份缓存)`);
  const { invalidateAfterProfileSave } = await importSource("lib/query-invalidation.ts");
  const keys = await importSource("lib/queryKeys.ts");

  const client = stubClient();
  await invalidateAfterProfileSave(client);
  const received = client.calls.map((key) => JSON.stringify(key));
  assert.ok(
    received.includes(JSON.stringify(keys.queryKeys.viewer())),
    `保存资料后没有 invalidate viewer,收到的是 ${received.join(" / ")}`,
  );
  assert.ok(
    received.includes(JSON.stringify(keys.queryKeys.sharesByMe())),
    "保存资料后没有 invalidate 我的分享(作者名还是旧昵称)",
  );

  // 保存成功那条路径必须真的调用它(不是只定义了 helper)。
  const profile = read(PROFILE);
  assert.match(profile, /invalidateAfterProfileSave\(/, "个人信息保存成功后没有调用 invalidateAfterProfileSave");
  assert.match(profile, /cloudProfile\.update\([\s\S]{0,900}?invalidateAfterProfileSave\(/, "保存请求回来了却没有刷新缓存");
  // 第一次起名字(社区上传 / 评论前的 IdentityForm)也改的是同一份资料。
  assert.match(read(IDENTITY), /invalidateAfterProfileSave\(/, "IdentityForm 改完名字没有刷新 viewer");
});

test("⑤ 退出登录 → invalidate viewer(不刷的话站头还挂着上一个账号)", async () => {
  const { invalidateAfterSignOut } = await importSource("lib/query-invalidation.ts");
  const keys = await importSource("lib/queryKeys.ts");

  const client = stubClient();
  await invalidateAfterSignOut(client);
  const received = client.calls.map((key) => JSON.stringify(key));
  assert.ok(received.includes(JSON.stringify(keys.queryKeys.viewer())), `退出登录后没有 invalidate viewer,收到 ${received.join(" / ")}`);
  assert.ok(received.includes(JSON.stringify(keys.queryKeys.unread())), "退出登录后角标还留着上一个账号的未读数");
  assert.ok(
    client.removals.some((key) => JSON.stringify(key) === JSON.stringify(keys.queryKeys.admin())),
    "退出登录后管理台缓存没有被移除(下一个人还能看到上一个管理员的账号 / 订单 / 审计)",
  );

  // 个人信息里那个「退出」还要刷 viewer。
  const profile = read(PROFILE);
  assert.match(profile, /invalidateAfterSignOut\(/, "个人信息退出登录后没有刷新 viewer");
  assert.match(profile, /cloudAccount\.logout\([\s\S]{0,500}?invalidateAfterSignOut\(/, "个人信息退出请求回来了却没有刷新缓存");

  // 删号走的是同一个 helper:DELETE /me 之后所有属于这个账号的缓存都要失效。
  const danger = read(DANGER_ZONE);
  assert.match(danger, /invalidateAfterSignOut\(/, "删号后没有刷新 viewer / 角标 / 通知 / 我的分享");
  assert.match(danger, /cloudAccount\.deleteAccount\([\s\S]{0,500}?invalidateAfterSignOut\(/, "删号请求回来了却没有刷新缓存");
});

test("⑤b 管理台走 react-query:分组键、按影响面失效、退出时移除", async () => {
  const keys = await importSource("lib/queryKeys.ts");
  assert.deepEqual(keys.queryKeys.admin(), ["admin"]);
  assert.deepEqual(keys.queryKeys.adminUsers(), ["admin", "users"]);
  assert.deepEqual(keys.queryKeys.adminProviders(), ["admin", "providers"]);
  assert.deepEqual(keys.queryKeys.adminUsage(14), ["admin", "usage", 14]);

  const hooks = read("src/lib/admin-queries.ts");
  for (const hook of ["useAdminUsers", "useAdminProviders", "useAdminChannels", "useAdminUsage"]) {
    assert.match(hooks, new RegExp(`export function ${hook}\\(`), `缺少 ${hook}`);
  }
  assert.match(hooks, /queryKey: queryKeys\.adminUsers\(\)/, "账号查询没有用集中定义的键");

  const consoleSource = stripComments(read("src/components/admin/admin-console.tsx"));
  assert.doesNotMatch(consoleSource, /useEffect/, "管理台还在用 useEffect 手写首屏取数");
  assert.doesNotMatch(consoleSource, /Promise\.all\(\s*\[\s*cloudAdmin\./, "管理台还在用 Promise.all 自己拼取数");
  assert.match(consoleSource, /useAdminOverview\(\)/, "概览没有走 useQuery");
  assert.match(consoleSource, /useAdminProviders\(\)/, "供应商没有走 useQuery");
  const { adminInvalidation } = await importSource("lib/admin-queries.ts");
  assert.deepEqual(adminInvalidation.provider, [
    ["admin", "providers"],
    ["admin", "channels"],
    ["admin", "models"],
    ["admin", "overview"],
    ["admin", "audit"],
  ]);
  assert.match(consoleSource, /invalidate\(\.\.\.adminInvalidation\.provider\)/, "改供应商没有走统一的失效表");
  assert.match(consoleSource, /invalidateQueries/, "管理动作完成后没有失效缓存");
  assert.match(consoleSource, /adminInvalidation\.all/, "刷新按钮没有用整组前缀");
});

test("⑥ 列表:失败不重试、成功不重复拉(staleTime),并且用 useQuery 包起来", async () => {
  const browse = read(BROWSE);
  assert.match(browse, /function useListedShares/, "三组共用的分享取数规则被搬走了");
  assert.match(browse, /useQuery\(/, "分享列表没有用 useQuery(仍是 useEffect 取数)");
  // 插件 / 工作流仍走 queryKeys.shareList(kind, locale);board 没有独立的 ShareListKind,
  // 键挂在同一个分组前缀下,上传 / 删除画布时也会按整组失效。
  assert.match(browse, /queryKey: listKey\(kind, locale\)/, "分享列表没有用集中定义的键(按 kind + locale 分开缓存)");
  assert.match(browse, /queryKeys\.shareList\(kind, locale\)/, "插件 / 工作流的列表键没有走 queryKeys.shareList");
  assert.match(
    browse,
    /\[\.\.\.queryKeys\.shareList\(\), "board", locale\]/,
    "画布列表的键没有挂在 queryKeys.shareList() 的分组前缀下",
  );
  assert.match(browse, /retry:\s*false/, "列表失败会重试到天荒地老");
  assert.match(browse, /staleTime:/, "列表没有 staleTime,每次切页都会重拉");
  assert.match(browse, /fetchListedShares/, "列表没有复用 fetchListedShares 的「失败退化成空数组」规则");

  const keys = await importSource("lib/queryKeys.ts");
  assert.deepEqual(keys.queryKeys.shareList("plugin", "zh"), ["shares", "list", "plugin", "zh"]);
  assert.deepEqual(keys.queryKeys.shareList("workflow", "en"), ["shares", "list", "workflow", "en"]);
  assert.deepEqual([...keys.queryKeys.shareList(), "board", "zh"], ["shares", "list", "board", "zh"], "画布键的语言段丢了");
});

test("⑦ 更新用户信息后该刷新的清单:每条都有对应的 invalidateQueries", async () => {
  const invalidation = read(INVALIDATION);
  // 清单本身要写进代码注释,而不是只活在这次对话里。
  for (const marker of ["改昵称/短名/头像", "上传/删除分享", "标已读"]) {
    assert.ok(invalidation.includes(marker), `invalidation 注释里没有这条清单:${marker}`);
  }
  for (const marker of ["viewer", "我的分享", "概览", "该 kind 的列表", "unread", "通知列表"]) {
    assert.ok(invalidation.includes(marker), `清单没有说清要刷新的对象:${marker}`);
  }

  const {
    invalidateAfterProfileSave,
    invalidateAfterShareChange,
    invalidateAfterMarkRead,
  } = await importSource("lib/query-invalidation.ts");
  const keys = await importSource("lib/queryKeys.ts");
  const has = (client, key) => client.calls.some((call) => JSON.stringify(call) === JSON.stringify(key));

  // 改资料:viewer(站头)+ 我的分享(作者名)。
  const profileSave = stubClient();
  await invalidateAfterProfileSave(profileSave);
  assert.ok(has(profileSave, keys.queryKeys.viewer()), "改资料没有刷 viewer");
  assert.ok(has(profileSave, keys.queryKeys.sharesByMe()), "改资料没有刷我的分享里的作者名");

  // 上传 / 删除分享:我的分享 + 该 kind 的列表(概览的数字由我的分享求和,一并刷新)。
  for (const kind of ["plugin", "workflow"]) {
    const shareChange = stubClient();
    await invalidateAfterShareChange(shareChange, kind);
    assert.ok(has(shareChange, keys.queryKeys.sharesByMe()), `上传/删除 ${kind} 分享后没有刷我的分享`);
    assert.ok(has(shareChange, keys.queryKeys.shareList(kind)), `上传/删除 ${kind} 分享后没有刷该 kind 的列表`);
  }

  // 标已读:unread(站头角标)+ 通知列表。
  const markRead = stubClient();
  await invalidateAfterMarkRead(markRead);
  assert.ok(has(markRead, keys.queryKeys.unread()), "标已读后没有刷 unread");
  assert.ok(has(markRead, keys.queryKeys.notifications()), "标已读后没有刷通知列表");

  // 调用点:删除在控制台、上传在上传页、标已读在通知分区。
  assert.match(read(SHARES_PANEL), /invalidateAfterShareChange\(/, "删除分享成功后没有刷新列表 / 统计");
  assert.match(read(UPLOAD), /invalidateAfterShareChange\(/, "上传成功后没有刷新我的分享 / 该 kind 的列表");
  assert.match(read(NOTIFICATIONS), /invalidateAfterMarkRead\(/, "标已读后没有刷新 unread / 通知列表");
});
