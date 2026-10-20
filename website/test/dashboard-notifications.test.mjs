import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 控制台「通知」分区 + 顶栏未读角标的契约。
//:
//: 后端(7069fea97,`pre` 上已跑到 0003)给的是 `GET /notifications`、`GET
//: /notifications/unread-count`、`POST /notifications/read` 三个接口;这里盯住前端这一侧:
//:   - **真的跑一遍** `lib/cloud.ts` 的取数(打桩 `fetch`,断言 URL / 方法 / body),
//:     以及组件头部那几个纯函数(动词、点击编排),而不是用正则猜行为;
//:   - 结构层只盯「该在的还在、不该出现的没出现」:三种 kind 都有渲染分支、未读不只靠颜色、
//:     空态还是原来那句话、通知里没有 email、没有造假数据、没有轮询。
//:
//: 仓库里没有 JSX 运行器,所以和 `account-avatar.test.mjs` 同一套办法:把组件之前的纯函数
//: 切出来,当普通 TS 模块 import。
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

/** 去掉注释再看:注释里说「没有 setInterval / 没有 email」不算实现。 */
const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const PANEL = "src/components/account/dashboard-notifications.tsx";
const NAV = "src/components/account/account-nav.tsx";

const { LOCALES } = await import("../src/i18n/config.ts");
const { getMessages } = await import("../src/i18n/messages.ts");
// cloud.ts 只依赖全局 fetch,node 里可以直接 import。
const cloud = await import("../src/lib/cloud.ts");

/** 后端真实响应形状(见 cloud/domain/notifications.py 的 `_serialize_many`)。 */
const ITEMS = [
  {
    id: "n-like",
    kind: "like",
    read_at: null,
    created_at: "2026-10-19T08:00:00+00:00",
    actor: { display_name: "Ada", handle: "ada", avatar_seed: "seed-ada" },
    share: { id: "share-1", title: "Space Opera", kind: "workflow" },
  },
  {
    id: "n-fav",
    kind: "favorite",
    read_at: "2026-10-19T09:00:00+00:00",
    created_at: "2026-10-18T08:00:00+00:00",
    actor: { display_name: null, handle: "bob", avatar_seed: null },
    share: { id: "share-2", title: "Product Reel", kind: "board" },
  },
  {
    id: "n-comment",
    kind: "comment",
    read_at: null,
    created_at: "2026-10-20T08:00:00+00:00",
    actor: { display_name: "陈晨", handle: null, avatar_seed: "seed-chen" },
    share: { id: "share-3", title: "Coffee Ad", kind: "workflow" },
    comment_preview: "This is **plain** text — not markdown.",
  },
];

/** 打桩 `fetch`:记录每次调用的 URL / init,按 handler 的返回值当 JSON 响应。 */
function stubFetch(handler) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    calls.push({ url, init });
    return new Response(JSON.stringify(handler(url, init)), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  return {
    calls,
    restore() {
      globalThis.fetch = original;
    },
  };
}

/** 组件头部必须导出的纯逻辑;缺一个就红在它自己的名字上。 */
const REQUIRED_LOGIC = ["NOTIFICATION_PAGE_SIZE", "notificationName", "notificationSeed", "notificationVerb", "openNotification"];

/**
 * 把 `export function DashboardNotifications` 之前的纯函数切出来跑。
 *
 * 约定:import 之后、组件之前只放这些纯函数(和 account-nav 一样);去掉 import 与
 * `"use client"` 之后就是一个可以直接 import 的 TS 模块。
 */
async function loadLogic() {
  const panel = read(PANEL);
  const cut = panel.indexOf("export function DashboardNotifications");
  assert.notEqual(cut, -1, "dashboard-notifications 里找不到 `export function DashboardNotifications`");
  const head = panel
    .slice(0, cut)
    .split("\n")
    .filter((line) => !/^import\b/.test(line) && line.trim() !== '"use client";')
    .join("\n");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-notifications-"));
  const file = path.join(dir, "logic.ts");
  fs.writeFileSync(file, `${head}\n`, "utf8");
  const logic = await import(pathToFileURL(file).href);
  for (const name of REQUIRED_LOGIC) {
    assert.notEqual(logic[name], undefined, `dashboard-notifications 头部没有导出 \`${name}\``);
  }
  return logic;
}

test("① 列表:进分区拉一次 /notifications,三种 kind 各一条", async () => {
  const page = { items: ITEMS, next_cursor: "cursor-1", unread: 2 };
  const stub = stubFetch(() => page);
  let fetched;
  try {
    assert.ok(cloud.cloudNotifications, "lib/cloud.ts 里还没有和 cloudShares 并列的 notifications 取数");
    fetched = await cloud.cloudNotifications.list({ limit: 20 });
  } finally {
    stub.restore();
  }
  assert.equal(stub.calls.length, 1, "进分区应当只拉一次(不是每渲染一次拉一次)");
  assert.equal(stub.calls[0].url, "/api/cloud/v1/notifications?limit=20");
  assert.equal(stub.calls[0].init.method, undefined, "列表是 GET,不该带 method");
  assert.deepEqual(
    fetched.items.map((item) => item.kind),
    ["like", "favorite", "comment"],
    "三种 kind 没有原样传回来",
  );
  assert.equal(fetched.unread, 2);
  assert.equal(fetched.next_cursor, "cursor-1");

  // 三种 kind 各有一句不同的「做了什么」,来自同一个 i18n 文案区。
  const logic = await loadLogic();
  for (const locale of LOCALES) {
    const copy = getMessages(locale).dashboard;
    const verbs = ["like", "favorite", "comment"].map((kind) => logic.notificationVerb(kind, copy));
    assert.equal(new Set(verbs).size, 3, `${locale}: 三种通知的动词不是三条不同文案`);
    for (const verb of verbs) assert.ok(verb && verb.trim().length > 0, `${locale}: 通知动词是空的`);
  }

  // 结构:列表真的在渲染,评论有预览,标题链到详情。
  const panel = read(PANEL);
  assert.match(panel, /cloudNotifications\.list\(/, "通知分区没有走 lib/cloud.ts 的同一套取数");
  assert.match(panel, /items\.map\(/, "通知分区没有渲染列表");
  assert.match(panel, /<InitialTile/, "头像没有复用社区 / 个人信息那一块首字母色块");
  assert.match(panel, /item\.kind === "comment"/, "评论没有单独的渲染分支");
  assert.match(panel, /comment_preview/, "评论没有预览");
  assert.match(panel, /localePath\(locale, `\/community\/\$\{/, "分享标题没有链到 /[locale]/community/{id}");
});

test("② 未读与已读:色点 + 字重两条通道,已读的不再标一次", async () => {
  const logic = await loadLogic();
  const panel = read(PANEL);

  // 第一条通道是色点(形状),第二条是加粗 —— 不只靠颜色。
  assert.match(panel, /isUnread/, "没有区分未读 / 已读");
  assert.match(panel, /\bsize-2\b[^"]*rounded-full|rounded-full[^"]*\bsize-2\b/, "未读没有左侧色点");
  assert.match(panel, /font-semibold/, "未读没有加粗");
  assert.match(panel, /font-normal/, "已读没有回到常规字重");
  assert.match(panel, /sr-only/, "未读只有一个色点,读屏读不出来");

  // 已读的那条点开时不再发「标记已读」。
  const calls = [];
  await logic.openNotification(
    { id: "n-fav", read_at: "2026-10-19T09:00:00+00:00" },
    {
      markRead: async (ids) => {
        calls.push(["markRead", ids]);
      },
      navigate: (href) => {
        calls.push(["navigate", href]);
      },
      href: "/en/community/share-2",
    },
  );
  assert.deepEqual(calls, [["navigate", "/en/community/share-2"]], "已读的通知又被标了一次");
});

test("③ 点一条:标记这条已读,再跳到那条分享的详情", async () => {
  const logic = await loadLogic();
  const calls = [];
  await logic.openNotification(
    { id: "n-comment", read_at: null },
    {
      markRead: async (ids) => {
        calls.push(["markRead", ids]);
      },
      navigate: (href) => {
        calls.push(["navigate", href]);
      },
      href: "/zh/community/share-3",
    },
  );
  assert.deepEqual(
    calls,
    [
      ["markRead", ["n-comment"]],
      ["navigate", "/zh/community/share-3"],
    ],
    "点一条没有同时做「标记已读」和「跳详情」",
  );

  // 点击处理器把两件事都接上;带修饰键的点击留给浏览器(新标签打开)。
  const panel = read(PANEL);
  assert.match(panel, /openNotification\(/, "点击没有走可测的编排");
  assert.match(panel, /cloudNotifications\.markRead/, "点击没有调用 POST /notifications/read");
  assert.match(panel, /router\.push\(/, "点击没有跳转");
  assert.match(panel, /event\.preventDefault\(\)/, "点击没有拦下默认导航,会和 router.push 抢一次");
  assert.match(panel, /event\.metaKey \|\| event\.ctrlKey/, "带修饰键的点击(新标签)被劫持了");
});

test("④ 全部标为已读:不传 ids = 全标;没有未读时不显示", async () => {
  assert.ok(cloud.cloudNotifications, "lib/cloud.ts 里还没有 notifications 取数");
  let stub = stubFetch(() => ({ marked: 2, unread: 0 }));
  try {
    await cloud.cloudNotifications.markRead();
  } finally {
    stub.restore();
  }
  assert.equal(stub.calls[0].url, "/api/cloud/v1/notifications/read");
  assert.equal(stub.calls[0].init.method, "POST");
  assert.equal(stub.calls[0].init.body, undefined, "不传 ids 时却带了 body(ids: [] = 一条都不标)");

  // 显式空数组 = 一条都不标:前端只有「全部」这一个入口,不该误传 []。
  stub = stubFetch(() => ({ marked: 0, unread: 3 }));
  try {
    await cloud.cloudNotifications.markRead([]);
  } finally {
    stub.restore();
  }
  assert.deepEqual(JSON.parse(stub.calls[0].init.body), { ids: [] });

  const panel = read(PANEL);
  assert.match(panel, /unread > 0 &&/, "没有未读时仍然显示「全部标为已读」");
  assert.match(panel, /copy\.markAllRead/, "「全部标为已读」没有文案");
  assert.match(panel, /copy\.markingRead/, "标记进行中没有反馈");
});

test("⑤ 顶栏角标:0 不显示、>99 收成 99+,只拉一次不轮询", async () => {
  assert.equal(typeof cloud.formatUnreadBadge, "function", "lib/cloud.ts 里没有角标格式化的纯函数");
  assert.equal(cloud.formatUnreadBadge(0), null, "0 条未读时还显示角标");
  assert.equal(cloud.formatUnreadBadge(-3), null, "负数还显示角标");
  assert.equal(cloud.formatUnreadBadge(Number.NaN), null, "非数字还显示角标");
  assert.equal(cloud.formatUnreadBadge(1), "1");
  assert.equal(cloud.formatUnreadBadge(99), "99");
  assert.equal(cloud.formatUnreadBadge(100), "99+", "100 条未读没有收成 99+");
  assert.equal(cloud.formatUnreadBadge(1234), "99+");

  const stub = stubFetch(() => ({ count: 7 }));
  let result;
  try {
    assert.ok(cloud.cloudNotifications, "lib/cloud.ts 里还没有 notifications 取数");
    result = await cloud.cloudNotifications.unreadCount();
  } finally {
    stub.restore();
  }
  assert.equal(result.count, 7);
  assert.equal(stub.calls[0].url, "/api/cloud/v1/notifications/unread-count");

  const nav = read(NAV);
  assert.match(nav, /cloudNotifications\s*\n?\s*\.unreadCount\(\)/, "顶栏没有问 unread-count");
  assert.match(nav, /formatUnreadBadge\(/, "顶栏角标没有走共用的格式化函数");
  assert.match(nav, /bg-destructive/, "角标不是一个小红点 / 红色数字");
  assert.match(nav, /tabular-nums/, "角标数字没有等宽,位数一变就跳");
  assert.doesNotMatch(stripComments(nav), /setInterval|setTimeout|EventSource|WebSocket/, "顶栏角标引入了轮询");
  assert.doesNotMatch(stripComments(read(PANEL)), /setInterval|setTimeout|EventSource|WebSocket/, "通知列表引入了轮询");
});

test("⑥ 空态保留、没有 email、没有造假数据、评论不当 markdown 渲染", async () => {
  const zh = getMessages("zh").dashboard;
  assert.equal(
    zh.notificationsEmpty,
    "还没有通知。有人评论或点赞你的分享时会出现在这里。",
    "约定要保留的那句空态被改了",
  );
  assert.ok(getMessages("en").dashboard.notificationsEmpty.trim().length > 0, "英文空态是空的");

  const panel = read(PANEL);
  assert.match(panel, /copy\.notificationsEmpty/, "空态那句话没有渲染");
  assert.match(panel, /items\.length === 0/, "没有「一条都没有」的分支");
  assert.doesNotMatch(panel, /即将上线|敬请期待|coming soon/i, "通知写了「即将上线」之类的话");
  // 没有造假数据:通知只能来自接口,不许写字面量的 actor / 时间。
  assert.doesNotMatch(panel, /display_name:\s*"/, "通知里写死了假人名");
  assert.doesNotMatch(panel, /created_at:\s*"/, "通知里写死了假时间");
  assert.doesNotMatch(panel, /cloudShares|cloudAccount/, "通知分区拉了别的接口");
  // 公开身份只有三列,页面上不该出现 email(**注释里说明「没有 email」不算**)。
  assert.doesNotMatch(stripComments(panel), /email/i, "通知分区出现了 email");
  // 类型层:通知的 actor 是 CloudIdentity(公开三列),不是连 email 一起回来的 CloudUser。
  const cloudSource = read("src/lib/cloud.ts");
  const typesStart = cloudSource.indexOf("/** 通知的三种来由。");
  const typesEnd = cloudSource.indexOf("export type CloudNotificationQuery");
  assert.ok(typesStart !== -1 && typesEnd > typesStart, "cloud.ts 里找不到通知的类型段");
  assert.match(cloudSource.slice(typesStart, typesEnd), /actor:\s*CloudIdentity/, "通知 actor 不是公开身份三列");
  assert.doesNotMatch(stripComments(cloudSource.slice(typesStart, typesEnd)), /email/i, "通知类型里带了 email");
  // 数据层:三种 kind 的每一条、每个字段都扫一遍,不允许出现 email 字段或 email 样的值。
  const keysDeep = (value, out = []) => {
    if (Array.isArray(value)) {
      for (const entry of value) keysDeep(entry, out);
      return out;
    }
    if (value && typeof value === "object") {
      for (const [key, entry] of Object.entries(value)) {
        out.push(key);
        keysDeep(entry, out);
      }
    }
    return out;
  };
  for (const key of keysDeep(ITEMS)) {
    assert.doesNotMatch(key, /email/i, `通知字段里出现了 ${key}`);
  }
  assert.deepEqual(
    Object.keys(ITEMS[0].actor).sort(),
    ["avatar_seed", "display_name", "handle"],
    "通知 actor 不是公开三列",
  );
  assert.doesNotMatch(JSON.stringify(ITEMS), /@/, "通知数据里出现了 email 样的值");
  // 评论预览是纯文本:不解析 markdown / 不注入 HTML。
  assert.doesNotMatch(panel, /dangerouslySetInnerHTML|ReactMarkdown|remark|marked\(/i, "评论预览被当成 markdown 渲染了");
});

test("⑦ 分页:「加载更多」带 cursor,追加而不是替换", async () => {
  const stub = stubFetch((url) => ({
    items: url.includes("cursor=") ? [ITEMS[2]] : [ITEMS[0], ITEMS[1]],
    next_cursor: url.includes("cursor=") ? null : "cursor-1",
    unread: 2,
  }));
  let first;
  let second;
  try {
    assert.ok(cloud.cloudNotifications, "lib/cloud.ts 里还没有 notifications 取数");
    first = await cloud.cloudNotifications.list({ limit: 20 });
    second = await cloud.cloudNotifications.list({ limit: 20, cursor: first.next_cursor });
  } finally {
    stub.restore();
  }
  assert.equal(stub.calls[0].url, "/api/cloud/v1/notifications?limit=20");
  assert.equal(stub.calls[1].url, "/api/cloud/v1/notifications?limit=20&cursor=cursor-1");
  assert.equal(second.next_cursor, null, "最后一页还给了 cursor");
  assert.deepEqual(
    [...first.items, ...second.items].map((item) => item.id),
    ["n-like", "n-fav", "n-comment"],
  );

  const panel = read(PANEL);
  assert.match(panel, /setItems\(\(current\) => \[\.\.\.current, \.\.\.page\.items\]\)/, "「加载更多」不是追加");
  assert.match(panel, /nextCursor/, "没有记住下一页的 cursor");
  assert.match(panel, /loadMore/, "没有「加载更多」");
});
