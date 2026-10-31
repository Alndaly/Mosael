import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

//: 社区页(列表 / 详情 / 上传)的验收契约。
//:
//: 后端契约已经定死(`cloud/src/cloud/api/{shares,profile}.py`):公开响应只带
//: `{display_name, handle, avatar_seed}`,email 绝不出现;列表 / 详情不取 payload,
//: 只有下载和深链才碰内容本体。这里把三页的行为、文案和下一步都钉住 —— 光有接口调用
//: 不算做完,错误要能读、空态要有出口、未登录要点得动。
const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const maybeRead = (relative) => {
  const file = path.join(ROOT, relative);
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
};
const util = async () => {
  try {
    return await import("../src/components/community/share-utils.ts");
  } catch {
    return null;
  }
};

const LIST_PAGE = "src/app/[locale]/(site)/community/page.tsx";
const DETAIL_PAGE = "src/app/[locale]/(site)/community/[id]/page.tsx";
const UPLOAD_PAGE = "src/app/[locale]/(site)/community/upload/page.tsx";
const LIST_UI = "src/components/community/shares.tsx";
const LANDING_UI = "src/components/community/landing.tsx";
const DETAIL_UI = "src/components/community/share-detail.tsx";
const UPLOAD_UI = "src/components/community/upload-form.tsx";
const IDENTITY_UI = "src/components/community/identity-form.tsx";
const SERVER_DATA = "src/components/community/share-server.ts";

const { getMessages } = await import("../src/i18n/messages.ts");
const { LOCALES } = await import("../src/i18n/config.ts");

test("① 社区首页:插件 / 工作流两组,官方静态卡片在前、当前语言的用户分享在后", async () => {
  assert.ok(maybeRead(LIST_PAGE), "缺少社区列表页 /[locale]/community");
  assert.ok(maybeRead(SERVER_DATA), "缺少服务端取数封装(仍要经 lib/cloud.ts)");

  const page = maybeRead(LIST_PAGE);
  assert.match(page, /generateMetadata/, "社区首页没有自己的 <head>");
  assert.match(page, /pageMetadata\(/, "社区首页没有走 pageMetadata");
  // 两组官方内容都来自构建期读好的 registry —— 卡片就是 /plugins、/workflows 的静态卡片。
  assert.match(page, /listPlugins\(locale\)/, "社区首页没有读官方插件");
  assert.match(page, /listWorkflows\(locale\)/, "社区首页没有读官方工作流");
  assert.match(
    page,
    /<CommunityLanding locale=\{locale\} plugins=\{plugins\} workflows=\{workflows\}/,
    "社区首页没有把两组官方内容交给落地页组件",
  );

  const landing = maybeRead(LANDING_UI);
  assert.ok(landing, "缺少社区首页的两组列表组件");
  // 两组各用和 /plugins、/workflows 同一份官方卡片(权限 / 工具 / 安装、节点数 / 阶段)。
  assert.match(landing, /<PluginCard locale=\{locale\} plugin=\{entry\.official\}/, "插件组没有用官方静态卡片");
  assert.match(landing, /<WorkflowCard locale=\{locale\} workflow=\{entry\.official\}/, "工作流组没有用官方静态卡片");
  // 分享按 kind 各取一次,各带当前语言(取数规则复用 listed-shares)。
  assert.match(landing, /useListedShares\("plugin", locale\)/, "插件组没有取当前语言的插件分享");
  assert.match(landing, /useListedShares\("workflow", locale\)/, "工作流组没有取当前语言的工作流分享");
  // 合并规则复用 /plugins 那一套:命中静态 slug 的官方分享跳过,官方卡片全部在前。
  assert.match(landing, /listedShares\(/, "没有复用 listedShares 的 slug 去重 / 新→旧排序");
  assert.match(landing, /mergeListing\(/, "没有复用 mergeListing 的「官方在前、分享在后」");
  assert.match(landing, /mergeListing\([^)]*officialSlugs|listedShares\(shares, officialSlugs\)/, "组件没有先按官方 slug 去重");
  assert.ok(landing.includes("<ShareCard"), "两组都该把用户分享画成分享卡片");

  const ui = maybeRead(LIST_UI);
  assert.ok(ui, "缺少分享卡片组件");
  // 卡片字段:标题 / 摘要 / 作者昵称 / 类型 / 四项统计(详情页和落地页共用这张卡)。
  for (const field of ["share.title", "share.summary", "display_name", "stats.downloads", "stats.likes", "stats.favorites", "stats.comments"]) {
    assert.ok(ui.includes(field), `卡片没有渲染 ${field}`);
  }
  // 列表不取 payload —— 内容只在下载 / 深链时取。
  assert.doesNotMatch(ui, /payload/i, "列表组件碰了 payload");
  // 作者名是独立链接,不能被整卡链接吞掉。
  assert.match(ui, /localePath\(locale, `\/users\/\$\{share\.author\.handle\}`\)/, "卡片作者没有指向公开主页");
  assert.match(ui, /relative z-10/, "作者链接没有抬到整卡链接之上");
});

test("①b 作者可点:卡片与详情页都跳到 /users/{handle}", () => {
  const ui = maybeRead(LIST_UI);
  const page = maybeRead(DETAIL_PAGE);
  assert.match(ui, /\/users\//, "分享卡片没有作者公开页地址");
  assert.match(page, /\/users\//, "详情页没有作者公开页地址");
  assert.match(page, /localePath\(locale, `\/users\/\$\{share\.author\.handle\}`\)/, "详情页作者没有指向公开主页");
});

test("② 详情:深链、下载成 .json、统计、404 可读文案与下一步", async () => {
  const page = maybeRead(DETAIL_PAGE);
  assert.ok(page, "缺少分享详情页 /[locale]/community/[id]");
  assert.match(page, /Suspense/, "详情页没有 Suspense,首屏会等云端返回");
  assert.match(page, /loadShare|shares\.get/, "详情页没有取单条分享");
  assert.match(page, /generateMetadata/, "详情页没有自己的 <head>");
  assert.match(page, /pageMetadata\(/, "详情页没有走 pageMetadata");
  assert.match(page, /status === 404/, "详情页没有单独处理 404");
  assert.match(page, /\.text\(locale\)/, "404 / 失败没有显示后端的人话");
  assert.match(page, /backToCommunity/, "404 没有「回到社区」的下一步");
  // 预览会在服务端取 payload,但**不能**走 `POST /download` —— 那是「下载 +1」的接口,
  // 只是看一眼详情不该把统计刷上去(预览见 test/share-preview.test.mjs)。
  assert.match(page, /loadSharePayload/, "详情页没有为预览取 payload");
  assert.doesNotMatch(page, /\.download\(/, "详情页走了下载接口(下载数会被预览带涨)");
  // 官方分享带 slug 时收敛到静态详情页,不能和 /workflows/<slug> 渲染两套详情。
  assert.match(page, /officialDetailHref/, "官方分享没有规范详情页判断");
  assert.match(page, /permanentRedirect\(canonical\)/, "官方分享没有重定向到静态详情页");
  assert.match(page, /findWorkflow/, "工作流官方分享没有对回静态模板");
  assert.match(page, /findPlugin/, "插件官方分享没有对回静态模板");

  const ui = maybeRead(DETAIL_UI);
  assert.ok(ui, "缺少分享详情的交互组件");
  assert.match(ui, /mosael:\/\/import\?share=/, "没有生成 mosael://import?share=<id> 深链");
  assert.match(ui, /cloudShares\.download/, "没有走 POST /shares/{id}/download");
  assert.match(ui, /shareFilename/, "下载没有用标题 slug 当文件名");
  assert.match(ui, /liked_by_me/, "没有渲染 / 处理 liked_by_me");
  assert.match(ui, /favorited_by_me/, "没有渲染 / 处理 favorited_by_me");
  assert.match(ui, /stats\.downloads|stats\.likes|stats\.favorites|stats\.comments/, "没有显示统计");
});

test("③ 点赞 / 收藏:登录后调接口,未登录给出登录引导,不静默失败", async () => {
  const ui = maybeRead(DETAIL_UI);
  assert.ok(ui, "缺少分享详情交互组件");
  assert.match(ui, /cloudShares\.like/, "点赞没有调接口");
  assert.match(ui, /cloudShares\.favorite/, "收藏没有调接口");
  assert.match(ui, /signedIn/, "未登录状态没有参与按钮判断");
  assert.match(ui, /communityLoginHref|login\?next=/, "未登录点击没有带回跳的登录链接");
  assert.match(ui, /loginToInteract/, "未登录点击没有可读提示");
  assert.match(ui, /goLogin/, "未登录点击没有「去登录」的下一步");
});

test("④ 评论:列表 / 未登录提示 / 没有昵称时就地起名", async () => {
  const ui = maybeRead(DETAIL_UI);
  assert.ok(ui, "缺少分享详情交互组件");
  assert.match(ui, /cloudShares\.comments|initialComments/, "评论没有列表数据");
  assert.match(ui, /cloudShares\.createComment|addComment/, "评论没有写接口");
  assert.match(ui, /identity_required/, "没有处理「没有昵称」的 409");
  assert.match(ui, /IdentityForm/, "没有昵称时就地起名没有复用昵称表单");
  assert.match(ui, /commentLogin|loginToComment/, "未登录时评论没有提示登录");
  assert.match(ui, /maxLength=\{2000\}/, "评论输入框没有 2000 字上限");

  const identity = maybeRead(IDENTITY_UI);
  assert.ok(identity, "缺少昵称小表单");
  assert.match(identity, /cloudProfile\.update|profile\.update/, "昵称表单没有写 PUT /me");
  assert.match(identity, /display_name/, "昵称表单没有 display_name");
  assert.match(identity, /handle/, "昵称表单没有可选 handle");
  assert.match(identity, /\.text\(locale\)/, "昵称表单没有把后端文案显示出来");
});

test("⑤ 上传:未登录跳登录并带回跳、首次起名、>2MB 前置拦下、成功跳详情", async () => {
  const page = maybeRead(UPLOAD_PAGE);
  assert.ok(page, "缺少上传页 /[locale]/community/upload");
  assert.match(page, /redirect\(/, "未登录没有跳转");
  assert.match(page, /communityLoginHref|login\?next=/, "登录跳转没有带回跳");
  assert.match(page, /generateMetadata/, "上传页没有自己的 <head>");
  assert.match(page, /pageMetadata\(/, "上传页没有走 pageMetadata");

  const ui = maybeRead(UPLOAD_UI);
  assert.ok(ui, "缺少上传表单");
  assert.match(ui, /cloudShares\.create/, "上传没有调 POST /shares");
  assert.match(ui, /accept="\.json"|accept=\{?["']\.json/, "文件选择器没有限定 .json");
  assert.match(ui, /JSON\.parse/, "没有先确认选中的是 JSON");
  assert.match(ui, /MAX_SHARE_BYTES|measurePayload/, "前端没有先量大小");
  assert.match(ui, /fileTooLarge|> MAX_SHARE_BYTES|> 2/, "超过 2MB 没有拦下并说清");
  assert.match(ui, /IdentityForm/, "没有昵称时没有就地起名");
  assert.match(ui, /router\.push/, "发布成功没有跳走");
  assert.match(ui, /community\/\$\{|community\/'|community\/`/, "发布成功没有跳到详情页");

  const utils = await util();
  assert.ok(utils, "缺少 share-utils.ts(大小 / 文件名 / 回跳校验的纯逻辑)");
  assert.equal(utils.MAX_SHARE_BYTES, 2 * 1024 * 1024, "2MB 上限写错了");
  // 紧凑 JSON 的 UTF-8 字节数,和后端量的是同一把尺子。
  assert.equal(utils.measurePayload({ a: "中" }), Buffer.byteLength(JSON.stringify({ a: "中" }), "utf8"));
  const tooBig = { text: "x".repeat(2 * 1024 * 1024 + 16) };
  assert.ok(utils.measurePayload(tooBig) > utils.MAX_SHARE_BYTES, ">2MB 没被量出来");
});

test("⑥ email 绝不出现:社区组件与页面只碰公开身份三列", async () => {
  const files = [
    LIST_PAGE,
    DETAIL_PAGE,
    UPLOAD_PAGE,
    LIST_UI,
    LANDING_UI,
    DETAIL_UI,
    UPLOAD_UI,
    IDENTITY_UI,
    SERVER_DATA,
    "src/components/community/community-header.tsx",
    "src/components/community/tile.tsx",
  ];
  const present = files.filter((file) => maybeRead(file));
  assert.ok(present.length >= 8, "社区文件没写齐,没法做全页面扫描");
  for (const file of present) {
    const text = maybeRead(file);
    assert.doesNotMatch(text, /\bemail\b/i, `${file} 里出现了 email —— 公开页面不许碰它`);
    assert.doesNotMatch(text, /@[a-z0-9.-]+\.[a-z]{2,}/i, `${file} 里出现了邮箱形状的字面量`);
  }

  const utils = await util();
  assert.ok(utils, "缺少 share-utils.ts");
  const stripped = utils.publicIdentity({
    id: "u1",
    email: "alice@example.com",
    email_verified_at: null,
    created_at: "2026-01-01T00:00:00Z",
    display_name: "Alice",
    handle: "alice",
    avatar_seed: "abcd",
  });
  // 「官方」是公开身份的第 4 列(官方号的徽标首帧就要有,不能等客户端 /me);
  // **email 仍然一律不出现** —— 这条测试守的就是这个。
  assert.deepEqual(stripped, { display_name: "Alice", handle: "alice", avatar_seed: "abcd", official: false });
  assert.ok(!JSON.stringify(stripped).includes("alice@example.com"), "公开身份里漏出了 email");
});

test("⑦ 导航与 COMMUNITY_PATH:站头「社区」指向 /community,插件 / 工作流仍有入口", async () => {
  const header = read("src/components/site-header.tsx");
  assert.match(header, /\/community/, "站头「社区」没有指向新的 /community");
  assert.match(header, /\/plugins/, "站头的匹配范围丢了插件分区(在插件页时「社区」不再高亮)");
  assert.match(header, /\/workflows/, "站头的匹配范围丢了工作流分区");

  // 注册成功后不再绕去社区页:云端注册直接建会话,注册完直接进控制台(见 signup-form)。

  // 插件市场没有被藏起来:页脚仍然列着两个分区,新社区页的页头也能切过去。
  const footer = read("src/components/site-footer.tsx");
  assert.match(footer, /\/plugins/, "页脚不再链接插件市场");
  assert.match(footer, /\/workflows/, "页脚不再链接工作流");
  const communityHeader = read("src/components/community/community-header.tsx");
  assert.match(communityHeader, /\/community/, "社区页头没有指向分享页");
  assert.match(communityHeader, /\/plugins/, "社区页头没有指向插件分区");
  assert.match(communityHeader, /\/workflows/, "社区页头没有指向工作流分区");

  const utils = await util();
  assert.ok(utils, "缺少 share-utils.ts");
  assert.equal(utils.communityLoginHref("zh", "/zh/community/upload"), "/zh/login?next=%2Fzh%2Fcommunity%2Fupload");
  assert.ok(utils.isCommunityReturnPath("/zh/community/upload", "zh"));
  assert.ok(!utils.isCommunityReturnPath("/zh/account", "zh"));
  assert.ok(!utils.isCommunityReturnPath("//evil.example/zh/community", "zh"));
  assert.ok(!utils.isCommunityReturnPath("https://evil.example/zh/community", "zh"));
});

test("文案:中英 community 同键,空态与错误有可读句子", () => {
  const zh = getMessages("zh").community;
  const en = getMessages("en").community;
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort(), "中英 community 文案键不一致");
  for (const key of [
    "homeTitle",
    "homeLede",
    "viewAll",
    "uploadCta",
    "loadMore",
    "loadFailed",
    "retry",
    "downloads",
    "likes",
    "favorites",
    "comments",
    "loginToInteract",
    "goLogin",
    "commentLogin",
    "postComment",
    "identityTitle",
    "displayName",
    "handle",
    "saveIdentity",
    "fileTooLarge",
    "submitUpload",
    "notFoundTitle",
    "backToCommunity",
  ]) {
    assert.ok(zh[key], `中文 community 缺 ${key}`);
    assert.ok(en[key], `英文 community 缺 ${key}`);
  }
  assert.match(zh.emptyNoShares, /还没有人分享/, "空列表没有说清「还没有人分享」");
  assert.match(zh.emptyNoSharesHint, /上传/, "空态没有指向「去上传」");
  for (const locale of LOCALES) {
    assert.ok(getMessages(locale).community.shares, `${locale} 缺分享分区名`);
  }
});
