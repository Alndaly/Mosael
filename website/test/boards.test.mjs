import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { registerSourceAliases } from "./source-aliases.mjs";

//: 「创意画板」的验收契约。
//:
//: 此前 `kind=board` 在官网**任何地方都没有露出**:云端已经收下用户上传的画布分享,
//: `GET /shares?kind=board&locale=…` 也早就返回它们,但站上既没有入口也没有列表页。
//: 这里把两件事钉住:
//:
//: ① 社区首页 `/community` 多第三组「创意画板」—— **只**由用户画布分享组成(官方内容里
//:    没有 board),一条都没有时整组不渲染;卡片复用现有的 `ShareCard`,不另画一种;
//: ② 新路由 `/boards` 是完整列表页,和 `/plugins`、`/workflows` 同构:页头 / 搜索 /
//:    当前语言 /「去上传」,只列 `kind=board`,空态说「还没有人分享画布」并给出上传入口。
//:
//: 另外,站头「社区」的匹配范围要把 `/boards` 包进去(在画板页「社区」仍高亮),页脚
//: 「社区」那一列也要有「创意画板」。
const ROOT = path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "src");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const maybeRead = (relative) => {
  const file = path.join(ROOT, relative);
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
};
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}

registerSourceAliases();

const BOARDS_PAGE = "src/app/[locale]/(site)/boards/page.tsx";
const LANDING_UI = "src/components/community/landing.tsx";
const BROWSE = "src/components/community/browse.tsx";
const HEADER = "src/components/site-header.tsx";
const FOOTER = "src/components/site-footer.tsx";

const { getMessages } = await import("../src/i18n/messages.ts");
const { cloudLocale, cloudShares } = await import("../src/lib/cloud.ts");
const listed = await import("../src/components/community/listed-shares.ts");

/** 一段源码:从 `start` 到下一个顶层 `export`(找不到就一直到文件尾)。 */
function section(source, startMarker) {
  const start = source.indexOf(startMarker);
  if (start === -1) return "";
  const rest = source.slice(start);
  const next = rest.indexOf("\nexport ", 1);
  return next === -1 ? rest : rest.slice(0, next);
}

test("① 社区首页第三组「创意画板」:只列用户画布分享,一条都没有就整组不渲染", () => {
  const landing = maybeRead(LANDING_UI);
  assert.ok(landing, "缺少社区首页的落地页组件");

  assert.match(landing, /function BoardGroup/, "缺少第三组(创意画板)");
  assert.match(landing, /<BoardGroup locale=\{locale\} \/>/, "落地页没有渲染第三组");
  assert.match(landing, /t\.boards\.title/, "第三组的标题没有用 boards.title");
  assert.match(landing, /useListedShares\("board", locale\)/, "第三组没有按 kind=board 取当前语言的画布分享");
  assert.match(landing, /localePath\(locale, "\/boards"\)/, "第三组的「查看全部」没有指向 /boards");
  // 分享排序沿用同一套新→旧规则(画布没有官方 slug,去重集合是空的)。
  assert.match(landing, /listedShares\(\w+, \[\]\)/, "画布组没有走同一套新→旧排序");

  // 一段一条都没有时整组不出现 —— 和另外两组一样,不画空块。
  assert.match(landing, /if \(shares\.length === 0\) return null/, "没有画布分享时第三组仍会画一个空块");

  // 画布没有官方静态内容:这一组里不许出现插件 / 工作流卡片,也不许有官方列表。
  const group = section(landing, "function BoardGroup");
  assert.ok(group, "取不到 BoardGroup 的源码");
  assert.doesNotMatch(
    group,
    /PluginCard|WorkflowCard|mergeListing|listPlugins|listWorkflows/,
    "画布组混进了官方静态卡片 / 官方列表 —— 官方内容里没有 board",
  );
  assert.match(group, /<ShareCard locale=\{locale\} share=\{share\}/, "画布分享没有复用现有 ShareCard");

  // 三组各一个「查看全部」,不多不少。
  const labels = landing.match(/\{t\.community\.viewAll\}/g) ?? [];
  assert.equal(labels.length, 3, `三组应各有一个「查看全部」,现在有 ${labels.length} 个`);
});

test("② /boards 是完整列表页:只取 kind=board + 当前 locale,不混官方内容", async () => {
  const page = maybeRead(BOARDS_PAGE);
  assert.ok(page, "缺少 /boards 路由页");
  assert.match(page, /export async function generateMetadata/, "/boards 没有自己的 <head>");
  assert.match(page, /pageMetadata\(/, "/boards 没有走 pageMetadata");
  assert.match(page, /path: "\/boards"/, "/boards 的 canonical 路径不对");
  assert.match(page, /notFound\(\)/, "/boards 没有处理非法语言");
  assert.match(page, /<CommunityHeader/, "/boards 没有和 /plugins、/workflows 一样的页头");
  assert.match(page, /<BoardBrowser locale=\{locale\}/, "/boards 没有渲染画板列表");
  // 页头**不带** CTA:这一页的列表在浏览器里取,只有它知道此刻空不空;一屏只留一处「去上传」。
  assert.match(page, /contribute=\{null\}/, "/boards 的页头又把「去上传」加回来了(会和空态那条重复)");

  const browse = maybeRead(BROWSE);
  assert.match(browse, /export function BoardBrowser/, "缺少 BoardBrowser");
  const browser = section(browse, "export function BoardBrowser");
  assert.ok(browser, "取不到 BoardBrowser 的源码");
  assert.match(browser, /useListedShares\("board", locale\)/, "BoardBrowser 没有按 kind=board 取当前语言的分享");
  assert.match(browser, /<ShareCard locale=\{locale\} share=\{/, "BoardBrowser 没有用现有 ShareCard");
  assert.match(browser, /SearchBox/, "BoardBrowser 没有搜索(和 /plugins、/workflows 同构)");
  assert.doesNotMatch(browser, /PluginCard|WorkflowCard|mergeListing\(/, "画板列表混进了官方静态内容");
  // 空态另走一条:没有画布时给「去上传」,搜索筛空时给清筛选。
  assert.match(browser, /t\.boards\.empty/, "没有画布的整页空态没有文案");
  assert.match(browser, /localePath\(locale, "\/community\/upload"\)/, "空态没有「去上传」的入口");

  // 真正发出去的请求:kind=board + 当前语言,只取两页各一次。
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
    await listed.fetchListedShares((query) => cloudShares.list(query), "board", "zh");
    await listed.fetchListedShares((query) => cloudShares.list(query), "board", "en");
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.equal(requested.length, 2, "两种语言应各取一次");
  assert.match(requested[0], /kind=board/, "画板列表没有带 kind=board");
  assert.match(requested[0], /locale=zh-CN/, "中文画板列表没有带中文 locale");
  assert.doesNotMatch(requested[0], /kind=(?:plugin|workflow)/, "画板列表请求了别的 kind");
  assert.match(requested[1], /kind=board/, "英文画板列表没有带 kind=board");
  assert.match(requested[1], /locale=en-US/, "英文画板列表没有带英文 locale");

  // 响应里混进别的语言时再兜一次底(同 /plugins、/workflows 的规则)。
  const onlyZh = await listed.fetchListedShares(
    async () => ({
      items: [{ locale: cloudLocale("zh") }, { locale: cloudLocale("en") }],
      next_cursor: null,
    }),
    "board",
    "zh",
  );
  assert.deepEqual(onlyZh, [{ locale: "zh-CN" }], "画板列表把别的语言的分享也画出来了");
});

test("③ 站头「社区」的匹配范围包含 /boards,页脚「社区」列有「创意画板」", () => {
  const header = maybeRead(HEADER);
  assert.ok(header, "缺少站头");
  const community = header.slice(
    header.indexOf('localePath(locale, "/community")'),
    header.indexOf("label: t.nav.community"),
  );
  assert.match(community, /localePath\(locale, "\/boards"\)/, "站头「社区」的 match 没有包含 /boards");
  // 原有的两个分区没有被顶掉。
  assert.match(community, /localePath\(locale, "\/plugins"\)/, "站头「社区」的匹配范围丢了 /plugins");
  assert.match(community, /localePath\(locale, "\/workflows"\)/, "站头「社区」的匹配范围丢了 /workflows");

  const footer = maybeRead(FOOTER);
  assert.ok(footer, "缺少页脚");
  assert.match(
    footer,
    /\{ label: t\.boards\.title, href: localePath\(locale, "\/boards"\) \}/,
    "页脚「社区」列没有「创意画板 → /boards」",
  );
  // 页脚原有两条仍在。
  assert.match(footer, /localePath\(locale, "\/plugins"\)/, "页脚丢了插件市场");
  assert.match(footer, /localePath\(locale, "\/workflows"\)/, "页脚丢了工作流");
});

test("④ 一条画布都没有:一句人话 + 去上传,沿用现有空态样式", async () => {
  const zh = getMessages("zh").boards;
  const en = getMessages("en").boards;
  assert.match(zh.empty, /还没有人分享画布/, "中文空态没有说清「还没有人分享画布」");
  assert.match(zh.emptyHint, /上传/, "中文空态没有指向「去上传」");
  assert.ok(en.empty && en.emptyHint, "英文空态缺文案");

  const browser = section(maybeRead(BROWSE), "export function BoardBrowser");
  assert.match(browser, /t\.boards\.empty/, "BoardBrowser 没有渲染「还没有人分享画布」");
  assert.match(browser, /uploadCta/, "空态没有「去上传」这个动作");
  assert.match(browser, /border-dashed/, "空态没有沿用现有空态的虚线框样式");
});

test("⑤ 画板文案中英键一致,标题就是「创意画板」", () => {
  const zh = getMessages("zh").boards;
  const en = getMessages("en").boards;
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort(), "中英 boards 文案键不一致");
  for (const key of ["title", "heading", "lede", "search", "seoTitle", "seoDescription", "empty", "emptyHint"]) {
    assert.ok(zh[key], `中文 boards 缺 ${key}`);
    assert.ok(en[key], `英文 boards 缺 ${key}`);
  }
  assert.equal(zh.title, "创意画板", "中文组的标题不是「创意画板」");
  assert.ok(Array.isArray(zh.keywords) && zh.keywords.length >= 3, "中文画板页缺关键词");
  assert.equal(zh.keywords.length, en.keywords.length, "关键词条数中英不一致");
});

test("⑥ 硬编码的旧构建页数已清", () => {
  // 不写死这串数字,免得 grep 证据本身变成新的硬编码。
  const OLD = ["1", "3", "5"].join("");
  const pattern = new RegExp(`\\b${OLD}\\b`);
  const offenders = walk(SRC)
    .filter((file) => pattern.test(fs.readFileSync(file, "utf8")))
    .map((file) => path.relative(ROOT, file));
  assert.deepEqual(offenders, [], `源码里还写着旧的构建页数 ${OLD}`);

  const official = read("test/official-content.test.mjs");
  assert.ok(!official.includes(OLD), `test/official-content.test.mjs 还写着旧的构建页数 ${OLD}`);
});
