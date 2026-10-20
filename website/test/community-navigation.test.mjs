import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { registerSourceAliases } from "./source-aliases.mjs";

//: 社区页头 / 列表的验收契约。
//:
//: 原始 bug:页头的 tab 是用条件拼接出来的 —— `...(active === "shares" ? [分享] : [])`。
//: 于是切到 `/plugins` 或 `/workflows` 之后,「分享」这一项整个从页头消失,用户看到的就是
//: 「分享列表没了」。数据一直在云端,消失的只是入口。
//:
//: 这里把重构后的结构钉死:**社区就是「插件」和「工作流」两件事**(维护者:「插件和工作流本身就是分享的呀,
//: 官方插件和工作流就是官方账号发布分享的」),"分享"不占 tab;tab 只由 (locale, counts) 决定,两页都在;
//: 筛选(kind)和排序(sort)是两个控件;「去上传」只出现一次;空态不再占一整屏。
const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");

registerSourceAliases();

const HEADER = "src/components/community/community-header.tsx";
const LIST_PAGE = "src/app/[locale]/(site)/community/page.tsx";
const PLUGINS_PAGE = "src/app/[locale]/(site)/plugins/page.tsx";
const WORKFLOWS_PAGE = "src/app/[locale]/(site)/workflows/page.tsx";
const LIST_UI = "src/components/community/shares.tsx";

/** tab 列表的纯逻辑。导不进来时给 null,让每条断言自己说清缺的是哪一块。 */
const tabsModule = async () => {
  try {
    return await import("../src/components/community/community-tabs.ts");
  } catch {
    return null;
  }
};
const shareUtils = () => import("../src/components/community/share-utils.ts");

const { getMessages } = await import("../src/i18n/messages.ts");

/** 取一个函数的源码块:`function X` 到下一个顶层 `function` / `export function` 之前。 */
function functionBlock(source, name) {
  const start = source.indexOf(`function ${name}`);
  assert.notEqual(start, -1, `找不到 ${name}`);
  const rest = source.slice(start + 1);
  const next = rest.search(/\n(?:export )?function /);
  return next === -1 ? rest : rest.slice(0, next);
}

/** 从一个 `<legend>` 所在位置往前找 `<fieldset`,往后找它的 `</fieldset>`,截出整组控件。 */
function controlGroup(source, legendText) {
  const legend = source.indexOf(`{${legendText}}`);
  assert.notEqual(legend, -1, `找不到组标题 {${legendText}} —— 两组控件需要可见的标题`);
  const open = source.lastIndexOf("<fieldset", legend);
  assert.notEqual(open, -1, `{${legendText}} 不在 <fieldset> 里`);
  const close = source.indexOf("</fieldset>", legend);
  assert.notEqual(close, -1, `{${legendText}} 所在的 <fieldset> 没有闭合`);
  return { open, close, block: source.slice(open, close) };
}

test("① 社区两个分区在页头都在:插件 / 工作流 —— 不为「分享」单开 tab", async () => {
  // 先钉住根因:tab 只能来自同一个纯函数,页头不许再按 active 条件拼接。
  const header = read(HEADER);
  assert.doesNotMatch(header, /active ===/, "页头又按 active 条件拼 tab 了(这正是之前「切一下 tab 列表就没了」的 bug)");
  assert.match(header, /communityTabs\(locale, counts\)/, "页头没有用 communityTabs 生成 tab");

  const mod = await tabsModule();
  assert.ok(mod, "缺少 community-tabs.ts:tab 列表应当只由 (locale, counts) 决定的纯函数给出");

  for (const locale of ["zh", "en"]) {
    const tabs = mod.communityTabs(locale, { plugins: 9, workflows: 15 });
    assert.deepEqual(tabs.map((tab) => tab.id), ["plugins", "workflows"], `${locale}: 社区 tab 不是「插件 / 工作流」两项`);
    assert.deepEqual(
      tabs.map((tab) => tab.href),
      [`/${locale}/plugins`, `/${locale}/workflows`],
      `${locale}: tab 指向的地址不对`,
    );
    assert.ok(
      tabs.every((tab) => tab.href !== `/${locale}/community`),
      `${locale}: 「分享」又占了一个 tab —— 社区就是插件和工作流两件事`,
    );
  }

  // 计数:两项各自带数字。
  assert.deepEqual(mod.communityTabs("zh", { plugins: 9, workflows: 15 }).map((tab) => tab.count), [9, 15], "计数不对");
  assert.equal(mod.communityTabs("en", { plugins: 1, workflows: 2 })[0].label, getMessages("en").plugins.title, "「插件」tab 文案不对");
  assert.equal(mod.communityTabs("en", { plugins: 1, workflows: 2 })[1].label, getMessages("en").workflows.title, "「工作流」tab 文案不对");

  // 两个列表页各自把「当前分区」告诉页头;tab 本身来自同一个函数,与页面无关。
  for (const [page, active] of [[PLUGINS_PAGE, "plugins"], [WORKFLOWS_PAGE, "workflows"]]) {
    const source = read(page);
    assert.match(source, /<CommunityHeader/, `${page} 没有渲染社区页头`);
    assert.match(source, new RegExp(`active="${active}"`), `${page} 没有把当前分区传给页头`);
  }
  // 分享流那一页仍然存在、仍然渲染列表,只是不再占一个 tab(页头不传 active)。
  const listPage = read(LIST_PAGE);
  assert.match(listPage, /<CommunityHeader/, "分享页没有渲染社区页头");
  assert.doesNotMatch(listPage, /active="shares"/, "分享页又把自己当成一个 tab 了");
});

test("② 当前页高亮:aria-current 只给当前分区", () => {
  const header = read(HEADER);
  assert.match(
    header,
    /aria-current=\{tab\.id === active \? "page" : undefined\}/,
    "高亮没有落在当前分区上(aria-current 不是由 tab.id === active 决定)",
  );
  assert.match(header, /tab\.id === active/, "tab 没有按当前分区高亮");
  // 可选:分享流那一页不属于任何一个 tab,不传 active 就没有高亮。
  assert.match(header, /active\?: CommunitySection/, "active 必须可省 —— /community 不在 tab 里");

  // 两个 tab 页各自传自己的分区。
  assert.match(read(PLUGINS_PAGE), /active="plugins"/);
  assert.match(read(WORKFLOWS_PAGE), /active="workflows"/);
  // 分享流不把自己当 tab。
  assert.doesNotMatch(read(LIST_PAGE), /active="shares"/, "分享页又把自己当成一个 tab 了");
});

test("③ 筛选(kind)与排序(sort)是两组独立控件,中间有分隔", () => {
  const ui = read(LIST_UI);
  const kind = controlGroup(ui, "t.filterKind");
  const sort = controlGroup(ui, "t.filterSort");

  // 两组各自是一个带可见标题的 fieldset,不是 5 个 chip 挤在同一个控件里。
  assert.match(kind.block, /<legend/, "筛选组没有可见的组标题");
  assert.match(sort.block, /<legend/, "排序组没有可见的组标题");
  assert.ok(kind.close < sort.open, "排序组必须排在筛选组之后");

  // 每个 fieldset 只装自己那一维度的 chip。
  assert.match(kind.block, /query\.kind === ""/);
  assert.match(kind.block, /query\.kind === "workflow"/);
  assert.match(kind.block, /query\.kind === "board"/);
  assert.doesNotMatch(kind.block, /query\.sort/, "排序 chip 混进了筛选组");
  assert.match(sort.block, /query\.sort === "new"/);
  assert.match(sort.block, /query\.sort === "hot"/);
  assert.doesNotMatch(sort.block, /query\.kind/, "筛选 chip 混进了排序组");

  // 两组之间有一个分隔(视觉上分开,不是靠同一行里挨着)。
  const between = ui.slice(kind.close + "</fieldset>".length, sort.open);
  assert.match(between, /<hr\b/, "筛选与排序之间没有分隔");
  assert.match(between, /aria-orientation="vertical"/, "分隔没有标明是竖向的");
});

test("④ q / kind / sort 进地址栏、进请求,切换时整页不刷新", async () => {
  const utils = await shareUtils();

  // 解析:只认这三个值,非法值回落到默认,不留垃圾给请求和地址栏。
  assert.deepEqual(utils.parseShareQuery({ q: "  canvas ", kind: "board", sort: "hot" }), {
    q: "canvas",
    kind: "board",
    sort: "hot",
  });
  assert.deepEqual(utils.parseShareQuery({ kind: "evil", sort: "evil" }), { q: "", kind: "", sort: "new" });
  assert.deepEqual(utils.parseShareQuery({ q: ["first", "second"], kind: ["workflow"] }), {
    q: "first",
    kind: "workflow",
    sort: "new",
  });

  // 序列化:默认值不进地址栏,非默认值一个都不能丢。
  assert.equal(utils.shareSearch({ q: "", kind: "", sort: "new" }), "");
  assert.equal(utils.shareSearch({ q: "canvas", kind: "board", sort: "hot" }), "?q=canvas&kind=board&sort=hot");
  assert.equal(utils.shareSearch({ q: "", kind: "workflow", sort: "new" }), "?kind=workflow");

  // 组件:地址栏用 replaceState 就地改(不导航),请求带着同一个 query。
  const ui = read(LIST_UI);
  assert.match(ui, /history\.replaceState/, "改了筛选没有写回地址栏");
  assert.doesNotMatch(ui, /router\.push|router\.replace/, "切换筛选不该整页导航");
  assert.match(ui, /shareSearch\(query\)/, "地址栏里的查询串没有走 shareSearch");
  assert.match(
    ui,
    /cloudShares\.list\(\{[\s\S]{0,240}q: next\.q[\s\S]{0,200}kind: next\.kind[\s\S]{0,200}sort: next\.sort/,
    "列表请求没有跟着 q / kind / sort 走",
  );

  // 首屏(可分享出去的链接 / 刷新)用同一个解析,地址栏和页面内容一致。
  assert.match(read(LIST_PAGE), /parseShareQuery\(/, "首屏没有复用同一套查询串解析");
});

test("⑤ 「去上传」只出现一次:空列表归空态,非空归页头", async () => {
  const utils = await shareUtils();
  assert.equal(utils.uploadCtaSurface(false), "empty", "没有分享时,CTA 该由空态给");
  assert.equal(utils.uploadCtaSurface(true), "header", "有分享时,CTA 该由页头给");

  // 页头:按「首屏列表空不空」决定给不给 CTA;空的时候传 null,页头不渲染链接。
  const page = read(LIST_PAGE);
  assert.match(page, /uploadCtaSurface\(hasShares\) === "header"/, "页头 CTA 没有按列表空不空决定");
  assert.match(page, /:\s*null/, "列表为空时页头 CTA 没有关掉");

  const header = read(HEADER);
  assert.match(header, /contribute\?: \{ label: string; href: string \} \| null/, "页头没有「不给 CTA」这个状态");
  assert.match(header, /\{contribute && \(/, "contribute 为 null 时页头仍会渲染链接");

  // 空态:没有数据时才有「去上传」,筛空时给的是「清除筛选」。
  const empty = functionBlock(read(LIST_UI), "EmptyState");
  assert.match(empty, /t\.uploadCta/, "空态没有「去上传」出口");
  assert.match(empty, /t\.clearFilters/, "筛空时没有清除筛选的出口");
  assert.match(empty, /localePath\(locale, "\/community\/upload"\)/, "空态的「去上传」没有指向上传页");
});

test("⑥ 空态收成两行 + 一个按钮,不再是大虚线框 + 图标", () => {
  const empty = functionBlock(read(LIST_UI), "EmptyState");
  assert.doesNotMatch(empty, /border-dashed/, "空态还是那个大虚线框");
  assert.doesNotMatch(empty, /py-(?:10|12|16|20|24|28|32)/, "空态还在用大段留白占屏");
  assert.doesNotMatch(empty, /PackageOpen/, "空态的装饰大图标还在");
  assert.doesNotMatch(empty, /min-h-(?:screen|\[)/, "空态还在撑满高度");

  const paragraphs = empty.match(/<p[\s>]/g) ?? [];
  assert.equal(paragraphs.length, 2, `空态应该是 2 行文字,现在有 ${paragraphs.length} 行`);
  // 两条分支(没有数据 / 筛空)各只有一个行动按钮。
  assert.match(
    empty,
    /filtered \? \([\s\S]*?<button[\s\S]*?\) : \([\s\S]*?<Link[\s\S]*?\)\}/,
    "空态的按钮不是「每条分支一个」",
  );
});

test("⑦ 回归:切到别的分区再回来,页头两项仍在(不随当前页裁剪)", async () => {
  const mod = await tabsModule();
  assert.ok(mod, "缺少 community-tabs.ts");

  // 旧实现按 active 拼 tab,切走时那一项整项消失(原始 bug)。现在生成函数根本不收 active,
  // 结构上不可能因为切换而少一项。
  for (const active of ["plugins", "workflows", undefined]) {
    const tabs = mod.communityTabs("zh", { plugins: 9, workflows: 15 });
    assert.deepEqual(tabs.map((tab) => tab.id), ["plugins", "workflows"], `停在 ${active ?? "/community"} 时页头少了 tab`);
  }
  assert.equal(mod.communityTabs.length, 2, "communityTabs 只该收 locale 和 counts —— 收 active 就又会按页面裁剪");

  const header = read(HEADER);
  assert.doesNotMatch(header, /active ===/, "页头又按 active 条件拼 tab 了");
  assert.doesNotMatch(header, /\.\.\.\(active/, "页头又在用展开语法按 active 拼 tab");

  // 分享列表挂在页面数据上,不挂在 active 上。
  const page = read(LIST_PAGE);
  assert.match(page, /<ShareBrowser/, "分享页没有渲染列表(或空态)");
  assert.match(page, /initial=\{page\}/, "分享页的列表没有接上首屏数据");
  assert.match(page, /loadShareList/, "分享页没有取分享列表");
});
