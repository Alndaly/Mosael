import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { registerSourceAliases } from "./source-aliases.mjs";

//: 社区页头 / 首页(落地页)的验收契约。
//:
//: 原始 bug:页头的 tab 是用条件拼接出来的 —— `...(active === "shares" ? [分享] : [])`。
//: 于是切到 `/plugins` 或 `/workflows` 之后,「分享」这一项整个从页头消失,用户看到的就是
//: 「分享列表没了」。数据一直在云端,消失的只是入口。
//:
//: 现在把结构钉死:**社区就是「插件」和「工作流」两件事**(维护者:「插件和工作流本身就是分享的呀,
//: 官方插件和工作流就是官方账号发布分享的」),"分享"不占 tab;`/community` 是社区首页 ——
//: 两组各列「官方静态卡片 + 当前语言的用户分享」,官方在前;搜索 / 排序 / 分页留在
//: `/plugins`、`/workflows` 里,落地页不背那一套;「去上传」只在页头出现一次。
const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");

registerSourceAliases();

const HEADER = "src/components/community/community-header.tsx";
const LIST_PAGE = "src/app/[locale]/(site)/community/page.tsx";
const PLUGINS_PAGE = "src/app/[locale]/(site)/plugins/page.tsx";
const WORKFLOWS_PAGE = "src/app/[locale]/(site)/workflows/page.tsx";
const LANDING_UI = "src/components/community/landing.tsx";
const BROWSE = "src/components/community/browse.tsx";
const LIST_UI = "src/components/community/shares.tsx";

/** tab 列表的纯逻辑。导不进来时给 null,让每条断言自己说清缺的是哪一块。 */
const tabsModule = async () => {
  try {
    return await import("../src/components/community/community-tabs.ts");
  } catch {
    return null;
  }
};
/** 两组共用同一份合并规则(和 /plugins 是同一套)。 */
const listedSharesModule = async () => {
  try {
    return await import("../src/components/community/listed-shares.ts");
  } catch {
    return null;
  }
};

const { getMessages } = await import("../src/i18n/messages.ts");

test("① 社区三个分区在页头都在:插件 / 工作流 / 创意画板 —— 不为「分享」单开 tab", async () => {
  // 先钉住根因:tab 只能来自同一个纯函数,页头不许再按 active 条件拼接。
  const header = read(HEADER);
  assert.doesNotMatch(header, /active ===/, "页头又按 active 条件拼 tab 了(这正是之前「切一下 tab 列表就没了」的 bug)");
  assert.match(header, /communityTabs\(locale, counts\)/, "页头没有用 communityTabs 生成 tab");

  const mod = await tabsModule();
  assert.ok(mod, "缺少 community-tabs.ts:tab 列表应当只由 (locale, counts) 决定的纯函数给出");

  for (const locale of ["zh", "en"]) {
    const tabs = mod.communityTabs(locale, { plugins: 9, workflows: 15 });
    assert.deepEqual(
      tabs.map((tab) => tab.id),
      ["plugins", "workflows", "boards"],
      `${locale}: 社区 tab 不是「插件 / 工作流 / 创意画板」三项`,
    );
    assert.deepEqual(
      tabs.map((tab) => tab.href),
      [`/${locale}/plugins`, `/${locale}/workflows`, `/${locale}/boards`],
      `${locale}: tab 指向的地址不对`,
    );
    assert.ok(
      tabs.every((tab) => tab.href !== `/${locale}/community`),
      `${locale}: 「分享」又占了一个 tab —— 社区就是插件和工作流两件事`,
    );
  }

  // 计数:两项各自带数字。
  assert.deepEqual(mod.communityTabs("zh", { plugins: 9, workflows: 15 }).map((tab) => tab.count), [9, 15, undefined], "计数不对(画布的数拿不到就不显示)");
  assert.equal(mod.communityTabs("en", { plugins: 1, workflows: 2 })[0].label, getMessages("en").plugins.title, "「插件」tab 文案不对");
  assert.equal(mod.communityTabs("en", { plugins: 1, workflows: 2 })[1].label, getMessages("en").workflows.title, "「工作流」tab 文案不对");

  // 两个列表页各自把「当前分区」告诉页头;tab 本身来自同一个函数,与页面无关。
  for (const [page, active] of [[PLUGINS_PAGE, "plugins"], [WORKFLOWS_PAGE, "workflows"]]) {
    const source = read(page);
    assert.match(source, /<CommunityHeader/, `${page} 没有渲染社区页头`);
    assert.match(source, new RegExp(`active="${active}"`), `${page} 没有把当前分区传给页头`);
  }
  // 社区首页仍渲染同一个页头,只是不占 tab(页头不传 active)。
  const listPage = read(LIST_PAGE);
  assert.match(listPage, /<CommunityHeader/, "社区首页没有渲染社区页头");
  assert.doesNotMatch(listPage, /active="shares"/, "社区首页又把自己当成一个 tab 了");
});

test("② 当前页高亮:aria-current 只给当前分区", () => {
  const header = read(HEADER);
  assert.match(
    header,
    /aria-current=\{tab\.id === active \? "page" : undefined\}/,
    "高亮没有落在当前分区上(aria-current 不是由 tab.id === active 决定)",
  );
  assert.match(header, /tab\.id === active/, "tab 没有按当前分区高亮");
  // 可选:社区首页不属于任何一个 tab,不传 active 就没有高亮。
  assert.match(header, /active\?: CommunitySection/, "active 必须可省 —— /community 不在 tab 里");

  // 两个 tab 页各自传自己的分区。
  assert.match(read(PLUGINS_PAGE), /active="plugins"/);
  assert.match(read(WORKFLOWS_PAGE), /active="workflows"/);
  assert.match(read("src/app/[locale]/(site)/boards/page.tsx"), /active="boards"/, "/boards 没有把自己标成当前分区");
  // 社区首页不把自己当 tab。
  assert.doesNotMatch(read(LIST_PAGE), /active="shares"/, "社区首页又把自己当成一个 tab 了");
});

test("③ 两组都按当前语言取分享:真实请求 URL 带 locale= + kind=", async () => {
  const helper = await listedSharesModule();
  const cloud = await import("../src/lib/cloud.ts");
  assert.ok(helper, "缺少 listed-shares.ts(两组的取数与合并规则)");

  // 真正发出去的 URL —— 只测注入的 loader 不够,云端不传 locale 会把两种语言都返回。
  const realFetch = globalThis.fetch;
  const requested = [];
  globalThis.fetch = async (url) => {
    requested.push(String(url));
    return new Response(JSON.stringify({ items: [], next_cursor: null }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    await helper.fetchListedShares((query) => cloud.cloudShares.list(query), "plugin", "zh");
    await helper.fetchListedShares((query) => cloud.cloudShares.list(query), "workflow", "en");
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.equal(requested.length, 2, "两组应该各取一次,而不是取一次全量再本地筛");
  assert.match(requested[0], /kind=plugin/, "插件分享的请求没有带 kind=plugin");
  assert.match(requested[0], /locale=zh-CN/, "插件分享的请求没有带中文 locale —— 中文站会看到英文分享");
  assert.match(requested[1], /kind=workflow/, "工作流分享的请求没有带 kind=workflow");
  assert.match(requested[1], /locale=en-US/, "工作流分享的请求没有带英文 locale —— 英文站会看到中文分享");

  // 落地页也真的按 kind 各取一次(不是拿全量再本地切)。
  const landing = read(LANDING_UI);
  assert.match(landing, /useListedShares\("plugin", locale\)/, "插件组没有按 kind=plugin 取当前语言的分享");
  assert.match(landing, /useListedShares\("workflow", locale\)/, "工作流组没有按 kind=workflow 取当前语言的分享");
  assert.match(landing, /fetched\.length|useListedShares/, "组件没有用 listed-shares 的取数规则");
});

test("④ 官方在前、用户分享在后;命中静态 slug 的官方分享不再画第二张", async () => {
  const helper = await listedSharesModule();
  assert.ok(helper, "缺少 listed-shares.ts");
  const share = (over) => ({
    id: "s",
    slug: null,
    kind: "plugin",
    locale: "zh-CN",
    title: "分享",
    summary: null,
    bytes: 1,
    license: null,
    created_at: "2026-10-01T00:00:00Z",
    author: { display_name: "Alice", handle: "alice", avatar_seed: "seed", official: false },
    stats: { downloads: 0, likes: 0, favorites: 0, comments: 0 },
    liked_by_me: false,
    favorited_by_me: false,
    ...over,
  });
  const shares = [
    share({ id: "official-hit", slug: "comfyui", created_at: "2026-10-03T00:00:00Z" }),
    share({ id: "user-new", created_at: "2026-10-04T00:00:00Z" }),
    share({ id: "official-unmatched", slug: "legacy", created_at: "2026-09-01T00:00:00Z" }),
  ];
  const shown = helper.listedShares(shares, ["comfyui", "blender"]);
  assert.deepEqual(shown.map((one) => one.id), ["user-new", "official-unmatched"], "命中了静态条目的官方分享又出现了一次");
  assert.deepEqual(
    helper.mergeListing([{ slug: "comfyui" }, { slug: "blender" }], shown).map((entry) => entry.kind),
    ["official", "official", "share", "share"],
    "官方卡片没有排在用户分享之前",
  );

  // 落地页必须走同一条规则:静态 slug 集合来自 registry 的插件 / 工作流列表。
  const landing = read(LANDING_UI);
  assert.match(landing, /listedShares\(shares, officialSlugs\)/, "落地页没有按官方 slug 去重");
  assert.match(landing, /mergeListing\(official|mergeListing\(plugins|mergeListing\(workflows/, "落地页没有用同一个合并顺序");
});

test("⑤ 每组都有「查看全部」,分别指向 /plugins、/workflows、/boards", () => {
  const landing = read(LANDING_UI);
  assert.match(landing, /localePath\(locale, "\/plugins"\)/, "插件组没有「查看全部 → /plugins」");
  assert.match(landing, /localePath\(locale, "\/workflows"\)/, "工作流组没有「查看全部 → /workflows」");
  assert.match(landing, /localePath\(locale, "\/boards"\)/, "画板组没有「查看全部 → /boards」");
  const labels = landing.match(/\{t\.community\.viewAll\}/g) ?? [];
  assert.equal(labels.length, 3, `三组应该各有一个「查看全部」,现在有 ${labels.length} 个`);
  // 地址按当前语言段生成(中文站 /zh/plugins),不是写死的中文路径。
  assert.match(landing, /localePath\(locale,/, "「查看全部」没有走 localePath");
});

test("⑥ 落地页不背搜索 / 排序 / 分页 —— 那一套留在 /plugins、/workflows", () => {
  const page = read(LIST_PAGE);
  assert.doesNotMatch(page, /searchParams|parseShareQuery|shareSearch|loadShareList/, "落地页又把旧的列表查询塞回来了");
  assert.doesNotMatch(page, /Suspense/, "落地页没有首屏等待,不该再挂 Suspense");

  const landing = read(LANDING_UI);
  for (const banned of [
    'type="search"',
    "SearchBox",
    "filterKind",
    "filterSort",
    "sortNew",
    "sortHot",
    "loadMore",
    "next_cursor",
    "history.replaceState",
  ]) {
    assert.ok(!landing.includes(banned), `落地页带着旧的浏览控件:${banned}`);
  }

  // 搜索 / 筛选仍是 /plugins、/workflows 的事,没有跟着被删掉。
  const browse = read(BROWSE);
  assert.match(browse, /function SearchBox/, "搜索从 /plugins、/workflows 里也消失了");
  assert.match(browse, /function useListedShares/, "两组共用的分享取数规则被搬走了");
});

test("⑦ 云端不可达:只显示官方静态卡片,没有错误块,也没有空态块", async () => {
  const landing = read(LANDING_UI);
  assert.doesNotMatch(landing, /role="alert"|loadFailed|CloudApiError|setError/, "落地页出现了错误块");
  assert.doesNotMatch(landing, /emptyNoShares|emptyFiltered|EmptyState/, "落地页出现了空态块");
  // 某组没有任何条目时整组不渲染(官方是静态的,理论上不会空),而不是画一个空框。
  assert.match(landing, /if \(items\.length === 0\) return null/, "空组会画出一个空块");

  const helper = await listedSharesModule();
  assert.ok(helper, "缺少 listed-shares.ts");
  const failed = await helper.fetchListedShares(async () => {
    throw new Error("cloud down");
  }, "plugin", "zh");
  assert.deepEqual(failed, [], "云端失败没有退化成空数组");
  // 没有分享时,官方卡片照常渲染(内容优先)。
  assert.deepEqual(
    helper.mergeListing([{ slug: "comfyui" }], []).map((entry) => entry.kind),
    ["official"],
    "没有分享时官方卡片没有照常渲染",
  );
});

test("⑧ 「去上传」只出现一次:在页头,两组之间与空态都没有第二个", () => {
  const page = read(LIST_PAGE);
  assert.match(
    page,
    /contribute=\{\{ label: t\.uploadCta, href: localePath\(locale, "\/community\/upload"\) \}\}/,
    "页头没有上传入口",
  );
  assert.equal((page.match(/uploadCta/g) ?? []).length, 1, "上传 CTA 在页面上出现了不止一次");
  assert.doesNotMatch(read(LANDING_UI), /uploadCta|\/community\/upload/, "落地页里又放了一个上传入口");
  assert.doesNotMatch(read(LIST_UI), /uploadCta|EmptyState/, "分享卡片组件还背着旧的空态上传入口");

  // 页头支持「不给 CTA」这个状态(别的分区可能用到),不是这页才有的。
  const header = read(HEADER);
  assert.match(header, /contribute\?: \{ label: string; href: string \} \| null/, "页头没有「不给 CTA」这个状态");
  assert.match(header, /\{contribute && \(/, "contribute 为 null 时页头仍会渲染链接");
});

test("⑨ 回归:切到别的分区再回来,页头两项仍在(不随当前页裁剪)", async () => {
  const mod = await tabsModule();
  assert.ok(mod, "缺少 community-tabs.ts");

  // 旧实现按 active 拼 tab,切走时那一项整项消失(原始 bug)。现在生成函数根本不收 active,
  // 结构上不可能因为切换而少一项。
  for (const active of ["plugins", "workflows", "boards", undefined]) {
    const tabs = mod.communityTabs("zh", { plugins: 9, workflows: 15 });
    assert.deepEqual(tabs.map((tab) => tab.id), ["plugins", "workflows", "boards"], `停在 ${active ?? "/community"} 时页头少了 tab`);
  }
  assert.equal(mod.communityTabs.length, 2, "communityTabs 只该收 locale 和 counts —— 收 active 就又会按页面裁剪");

  const header = read(HEADER);
  assert.doesNotMatch(header, /active ===/, "页头又按 active 条件拼 tab 了");
  assert.doesNotMatch(header, /\.\.\.\(active/, "页头又在用展开语法按 active 拼 tab");

  // 社区首页挂在两组官方内容上,不挂在 active 上。
  const page = read(LIST_PAGE);
  assert.match(page, /<CommunityLanding/, "社区首页没有渲染两组列表");
  assert.doesNotMatch(page, /<ShareBrowser/, "旧的分享浏览组件又回到首页了");
  assert.doesNotMatch(page, /loadShareList/, "社区首页又在服务端取分享列表");
});
