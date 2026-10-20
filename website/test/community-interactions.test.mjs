import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { registerSourceAliases } from "./source-aliases.mjs";

//: 分享详情页的互动(点赞 / 收藏 / 评论 / 下载)必须让**列表缓存**失效。
//:
//: 原始 bug:详情页的 `toggleLike` / `toggleFavorite` / `download` 只改本地 state,
//: 查询缓存完全没动 —— 点完赞回列表,卡片上的数字还是旧的。评论数更糟:两个 client
//: island 之间靠 `window.dispatchEvent(new CustomEvent("mosael:share-comment-count"))`
//: 广播,那是一条绕过缓存的旁路(仓库明令禁止),而且列表也不知道评论数变了。
//:
//: 这里钉住:
//:   ① 点赞 / 收藏 / 下载 → 失效 `shareList` 前缀 + `sharesByMe`;
//:   ② 评论新增 / 删除 → 同上 + 通知(`notifications` 前缀);
//:   ③ 源码里 `dispatchEvent` 出现 0 次,`COMMENT_COUNT_EVENT` 一条不留;
//:   ④ 页头「创意画板」tab 里的数字由一个小 client 组件渲染,取数键与 /boards 相同;
//:   ⑤ 加载中 / 一条都没有时不显示数字,更不先闪一个 0。
const ROOT = path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "src");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const exists = (relative) => fs.existsSync(path.join(ROOT, relative));
const walk = (dir) =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });

registerSourceAliases();

const DETAIL_UI = "src/components/community/share-detail.tsx";
const DETAIL_PAGE = "src/app/[locale]/(site)/community/[id]/page.tsx";
const HEADER = "src/components/community/community-header.tsx";
const TABS = "src/components/community/community-tabs.ts";
const BOARD_COUNT = "src/components/community/board-tab-count.tsx";
const QUERY_CLIENT = "src/lib/query-client.ts";
const UPLOAD_UI = "src/components/community/upload-form.tsx";

/** 去掉注释再看:注释里写「不再 dispatchEvent」不算实现。 */
const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

/** 导入源码里的纯 .ts 模块;文件还没写时红在「缺少」上,而不是一个 ERR_MODULE_NOT_FOUND。 */
async function importSource(relative) {
  assert.ok(exists(relative), `缺少 ${relative}`);
  return import(pathToFileURL(path.join(ROOT, relative)).href);
}

/** 打桩的 QueryClient:只记下每次 invalidateQueries 收到的键。 */
function stubClient() {
  const calls = [];
  return {
    calls,
    invalidateQueries(filters) {
      calls.push(filters.queryKey);
      return Promise.resolve();
    },
  };
}

const received = (client) => client.calls.map((key) => JSON.stringify(key));
const has = (client, key) => received(client).includes(JSON.stringify(key));

test("① 点赞:失效 shareList 前缀与 sharesByMe,详情页真的调了", async () => {
  const invalidation = await importSource("src/lib/query-invalidation.ts");
  const keys = await importSource("src/lib/queryKeys.ts");
  assert.equal(
    typeof invalidation.invalidateAfterShareInteract,
    "function",
    "缺少 invalidateAfterShareInteract(详情页互动后该刷哪些缓存)",
  );

  const client = stubClient();
  await invalidation.invalidateAfterShareInteract(client, "like");
  assert.ok(
    has(client, keys.queryKeys.shareList()),
    `点赞后没有失效 shareList 前缀(列表卡片上的统计还在旧值),实际收到 ${received(client).join(" / ")}`,
  );
  assert.ok(has(client, keys.queryKeys.sharesByMe()), "点赞后没有失效 sharesByMe(我的分享 / 概览还是旧的)");

  const ui = stripComments(read(DETAIL_UI));
  assert.match(ui, /useQueryClient\(\)/, "详情页没有拿到 useQueryClient —— 改不了查询缓存");
  assert.match(
    ui,
    /cloudShares\.like\([\s\S]{0,700}?invalidateAfterShareInteract\(queryClient, "like"\)/,
    "点赞成功后没有失效列表缓存",
  );
});

test("② 收藏 / 下载:同一套失效(shareList 前缀 + sharesByMe)", async () => {
  const invalidation = await importSource("src/lib/query-invalidation.ts");
  const keys = await importSource("src/lib/queryKeys.ts");
  assert.equal(typeof invalidation.invalidateAfterShareInteract, "function", "缺少 invalidateAfterShareInteract");

  for (const kind of ["favorite", "download"]) {
    const client = stubClient();
    await invalidation.invalidateAfterShareInteract(client, kind);
    assert.ok(has(client, keys.queryKeys.shareList()), `${kind} 后没有失效 shareList 前缀`);
    assert.ok(has(client, keys.queryKeys.sharesByMe()), `${kind} 后没有失效 sharesByMe`);
  }

  const ui = stripComments(read(DETAIL_UI));
  for (const [api, kind] of [
    ["cloudShares\\.favorite\\(", "favorite"],
    ["cloudShares\\.download\\(", "download"],
  ]) {
    assert.match(
      ui,
      new RegExp(`${api}[\\s\\S]{0,800}?invalidateAfterShareInteract\\(queryClient, "${kind}"\\)`),
      `${kind} 成功后没有失效列表缓存`,
    );
  }
});

test("③ 评论增删:失效列表 + sharesByMe + 通知;window 广播一条不留", async () => {
  const invalidation = await importSource("src/lib/query-invalidation.ts");
  const keys = await importSource("src/lib/queryKeys.ts");
  assert.equal(typeof invalidation.invalidateAfterShareInteract, "function", "缺少 invalidateAfterShareInteract");

  const client = stubClient();
  await invalidation.invalidateAfterShareInteract(client, "comment");
  assert.ok(has(client, keys.queryKeys.shareList()), "评论后没有失效 shareList 前缀");
  assert.ok(has(client, keys.queryKeys.sharesByMe()), "评论后没有失效 sharesByMe");
  assert.ok(
    has(client, keys.queryKeys.notificationsAll()),
    `评论后没有失效通知(作者那边会收到一条),实际收到 ${received(client).join(" / ")}`,
  );

  const ui = stripComments(read(DETAIL_UI));
  assert.match(
    ui,
    /cloudShares\.createComment\([\s\S]{0,900}?invalidateAfterShareInteract\(queryClient, "comment"\)/,
    "评论成功后没有失效缓存",
  );
  assert.match(
    ui,
    /cloudShares\.deleteComment\([\s\S]{0,900}?invalidateAfterShareInteract\(queryClient, "comment"\)/,
    "删除评论后没有失效缓存",
  );

  // 仓库明令禁止的旁路:window 事件广播(自定义事件名也不许再出现)。
  const offenders = walk(SRC)
    .filter((file) => /\.(ts|tsx)$/.test(file))
    .filter((file) => /dispatchEvent/.test(read(path.relative(ROOT, file))))
    .map((file) => path.relative(ROOT, file));
  assert.deepEqual(offenders, [], `源码里还有 window 事件广播:\n${offenders.join("\n")}`);
  assert.doesNotMatch(read(DETAIL_UI), /COMMENT_COUNT_EVENT|mosael:share-comment-count/, "COMMENT_COUNT_EVENT 没有删干净");

  // 两个 client island 的评论数改由同一页的 React state 共享(不是 window 广播)。
  assert.match(read(DETAIL_PAGE), /ShareCommentCountProvider/, "详情页没有把两个 island 放进同一个评论数 provider");
  assert.match(ui, /React\.createContext|createContext/, "评论数没有走 React context");
});

test("④ 创意画板 tab:有画布时显示数字,取数键与 /boards 共用", async () => {
  const tabs = await importSource(TABS);
  assert.equal(typeof tabs.boardTabCount, "function", "缺少 boardTabCount(页头画布数字的纯逻辑)");
  assert.equal(tabs.boardTabCount([{ id: "a" }, { id: "b" }]), 2, "有画布时没有渲染条数");
  assert.equal(tabs.boardTabCount([]), undefined, "一条画布都没有时不要显示 0");
  assert.equal(tabs.boardTabCount(undefined), undefined, "还没取到时不要显示 0");
  assert.ok(tabs.TAB_COUNT_CLASS, "缺少 tab 数字的胶囊样式常量(两处要长得一样)");
  assert.match(tabs.TAB_COUNT_CLASS, /bg-secondary/, "数字胶囊没有和其它 tab 一样的底色");
  assert.match(tabs.TAB_COUNT_CLASS, /tabular-nums/, "数字没有用等宽数字");

  assert.ok(exists(BOARD_COUNT), `缺少 ${BOARD_COUNT}(页头里唯一的那格 client)`);
  const count = stripComments(read(BOARD_COUNT));
  assert.match(count, /^"use client";/m, "画布数字组件不是 client component");
  assert.match(count, /useListedShares\("board", locale\)/, "画布数字没有复用列表的取数(会多一份数据源)");
  assert.match(count, /boardTabCount\(/, "画布数字没有走 boardTabCount 的「拿不到就不显示」规则");
  assert.match(count, /TAB_COUNT_CLASS/, "画布数字没有复用同一个胶囊样式");

  const header = read(HEADER);
  assert.doesNotMatch(header, /^"use client";/m, "页头被改成了 client component(只该让那格数字是 client)");
  assert.match(header, /<BoardTabCount locale=\{locale\}/, "页头没有渲染画布数字组件");
  assert.match(header, /TAB_COUNT_CLASS/, "页头其它两个数字没有和画布数字共用样式常量");
});

test("⑤ 加载中不闪 0:没数据就不渲染数字", async () => {
  const count = stripComments(read(BOARD_COUNT));
  assert.match(count, /count === undefined\) return null/, "没有数据时没有直接不渲染");
  assert.doesNotMatch(count, /\?\?\s*0|\|\|\s*0/, "用 0 兜底了(加载中会先闪一个 0)");

  // 默认的 refetchOnMount 已经够用(失效把缓存标脏 → 回到列表挂载时重取),
  // 不要把「每次挂载都重取」开成全局行为。
  assert.doesNotMatch(stripComments(read(QUERY_CLIENT)), /refetchOnMount/, "全局开了 refetchOnMount(应按需失效)");
});

test("⑥ 上传成功后列表能被标脏,回到 /community / /boards 会重取", async () => {
  const invalidation = await importSource("src/lib/query-invalidation.ts");
  const keys = await importSource("src/lib/queryKeys.ts");
  const client = stubClient();
  await invalidation.invalidateAfterShareChange(client, "board");
  assert.ok(
    has(client, keys.queryKeys.shareList()),
    "上传画布后没有失效 shareList 分组(/boards 与首页第三组还是旧列表)",
  );
  assert.ok(has(client, keys.queryKeys.sharesByMe()), "上传后没有失效我的分享");

  const upload = stripComments(read(UPLOAD_UI));
  assert.match(
    upload,
    /cloudShares\.create\([\s\S]{0,1600}?invalidateAfterShareChange\(queryClient, share\.kind\)/,
    "上传成功后没有失效列表缓存",
  );
});
