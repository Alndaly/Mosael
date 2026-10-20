import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { registerSourceAliases } from "./source-aliases.mjs";

//: 方案 B 的官网半:官方内容 bundle 导出 + /plugins、/workflows 把用户分享混进来。
//:
//: 两条不能松的规则:
//:
//: ① **导出必须逐字节稳定** —— 部署脚本在每次发布时重跑,输出漂移就会让 Git diff 变成
//:   噪声,也会让「bundle 改了没有」无法回答。同一份仓库导出两次必须一模一样。
//: ② **列表按当前语言取数** —— 云端 `GET /shares` 不传 locale 会把两种语言都返回,
//:   英文站就会看到中文分享。请求里必须带 locale,渲染前再按 locale 兜一次底。
//:
//: 另外,云端不可达不是列表页的错误:内容优先,取不到用户分享就只渲染静态官方列表,
//: 页面上不能冒出红色错误块。
const WEBSITE = path.resolve(import.meta.dirname, "..");
const ROOT = path.resolve(WEBSITE, "..");
const SRC = path.join(WEBSITE, "src");
const read = (relative) => fs.readFileSync(path.join(SRC, relative), "utf8");

registerSourceAliases();

const PYTHON = process.env.PYTHON || "python3";
const SCRIPT = path.join(ROOT, "scripts", "export_official_bundle.py");
const PLUGINS_PAGE = "app/[locale]/(site)/plugins/page.tsx";
const WORKFLOWS_PAGE = "app/[locale]/(site)/workflows/page.tsx";
const BROWSE = "components/community/browse.tsx";
const HELPER = "components/community/listed-shares.ts";
const UPLOAD_FORM = "components/community/upload-form.tsx";

const PNG_COUNT = { plugins: 9, workflows: 15 };

function tmpdir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function runExport(args, options = {}) {
  return spawnSync(PYTHON, [SCRIPT, ...args], { cwd: ROOT, encoding: "utf8", ...options });
}

function slugOfPluginDir(dir) {
  return fs
    .readdirSync(path.join(ROOT, "plugins", dir))
    .filter((name) => fs.existsSync(path.join(ROOT, "plugins", dir, name, "mosael.plugin.json")))
    .sort();
}

test("① 导出脚本产出 cloud 认的 bundle,同一份仓库两次导出逐字节一致", () => {
  assert.ok(fs.existsSync(SCRIPT), "缺少 scripts/export_official_bundle.py");

  const out = tmpdir("mosael-bundle-");
  const first = path.join(out, "first.json");
  const second = path.join(out, "second.json");

  const a = runExport(["--output", first]);
  assert.equal(a.status, 0, `第一次导出失败:\n${a.stderr || a.stdout}`);
  const b = runExport(["--output", second]);
  assert.equal(b.status, 0, `第二次导出失败:\n${b.stderr || b.stdout}`);

  // 逐字节,不是「解析后 deepEqual」—— 排序 / 缩进 / 键顺序 / 换行都必须一样。
  assert.ok(fs.readFileSync(first).equals(fs.readFileSync(second)), "同一份仓库两次导出不是逐字节一致");

  const bundle = JSON.parse(fs.readFileSync(first, "utf8"));
  assert.deepEqual(Object.keys(bundle), ["plugins", "workflows"], "bundle 顶层只允许 plugins / workflows");
  assert.equal(bundle.plugins.length, PNG_COUNT.plugins, "导出的插件数量不对");
  assert.equal(bundle.workflows.length, PNG_COUNT.workflows, "导出的工作流数量不对");

  const pluginSlugs = bundle.plugins.map((entry) => entry.slug);
  const workflowSlugs = bundle.workflows.map((entry) => entry.slug);
  assert.deepEqual(pluginSlugs, [...pluginSlugs].sort(), "插件没有按 slug 固定排序");
  assert.deepEqual(workflowSlugs, [...workflowSlugs].sort(), "工作流没有按 slug 固定排序");
  assert.equal(new Set(pluginSlugs).size, pluginSlugs.length, "插件 slug 有重复");
  assert.equal(new Set(workflowSlugs).size, workflowSlugs.length, "工作流 slug 有重复");

  // 插件:slug 就是目录名,payload 是 manifest 原文(不是整个目录)。
  const expectedPluginSlugs = [...slugOfPluginDir("bundled"), ...slugOfPluginDir("examples")].sort();
  assert.deepEqual(pluginSlugs, expectedPluginSlugs, "插件 slug 不等于 plugins/{bundled,examples}/<目录名>");

  for (const entry of bundle.plugins) {
    const manifestPath = ["bundled", "examples"]
      .map((dir) => path.join(ROOT, "plugins", dir, entry.slug, "mosael.plugin.json"))
      .find((candidate) => fs.existsSync(candidate));
    assert.ok(manifestPath, `找不到插件 ${entry.slug} 的 manifest`);
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    assert.deepEqual(entry.payload, manifest, `${entry.slug} 的 payload 不是 manifest 原文`);
    assert.ok(
      Buffer.byteLength(JSON.stringify(entry.payload), "utf8") <= 2 * 1024 * 1024,
      `${entry.slug} 的 payload 超过 2MB`,
    );
    assertEntryShape(entry);
  }

  // 工作流:slug 是官网静态条目的 slug(下划线折成连字符),payload 是那份
  // .mosael-workflow.json 的内容;不是 Node 数 / 简介 / 下载路径的拼装。
  const catalog = JSON.parse(fs.readFileSync(path.join(ROOT, "website", "public", "workflows", "catalog.json"), "utf8"));
  for (const entry of bundle.workflows) {
    const record = catalog.find((one) => one.id.replaceAll("_", "-") === entry.slug);
    assert.ok(record, `bundle 里有 catalog 不认识的工作流 slug: ${entry.slug}`);
    const payloadPath = path.join(ROOT, "website", "public", record.download.en.replace(/^\//, ""));
    const payload = JSON.parse(fs.readFileSync(payloadPath, "utf8"));
    assert.deepEqual(entry.payload, payload, `${entry.slug} 的 payload 不是 .mosael-workflow.json 的内容`);
    assert.ok(
      Buffer.byteLength(JSON.stringify(entry.payload), "utf8") <= 2 * 1024 * 1024,
      `${entry.slug} 的 payload 超过 2MB`,
    );
    assertEntryShape(entry);
    assert.equal(entry.locales["zh-CN"].title, record.name.zh, `${entry.slug} 的中文标题不是 catalog 的 name.zh`);
    assert.equal(entry.locales["en-US"].title, record.name.en, `${entry.slug} 的英文标题不是 catalog 的 name.en`);
  }
});

function assertEntryShape(entry) {
  const keys = Object.keys(entry).sort();
  const allowed = ["locales", "payload", "slug"];
  if ("license" in entry) allowed.push("license");
  assert.deepEqual(keys, allowed.sort(), `${entry.slug} 的 bundle 条目多了或少了一列`);
  assert.match(entry.slug, /^[a-z0-9][a-z0-9._-]*$/, `${entry.slug} 不是合法 slug`);
  assert.ok(Object.keys(entry.locales).length > 0, `${entry.slug} 没有任何语言`);
  for (const [locale, text] of Object.entries(entry.locales)) {
    assert.ok(["zh-CN", "en-US"].includes(locale), `${entry.slug} 有云端不支持的语言: ${locale}`);
    assert.equal(typeof text.title, "string", `${entry.slug} 的 ${locale} 缺 title`);
    assert.ok(text.title.length > 0, `${entry.slug} 的 ${locale} title 是空的`);
    assert.ok(text.title.length <= 200, `${entry.slug} 的 ${locale} title 超过 200 字`);
    if (text.summary !== undefined) {
      assert.ok(text.summary.length <= 500, `${entry.slug} 的 ${locale} summary 超过云端 500 字上限`);
    }
  }
}

test("①-a 没有英文就不编造:只导出 zh-CN 一种语言", () => {
  assert.ok(fs.existsSync(SCRIPT), "缺少 scripts/export_official_bundle.py");

  const root = tmpdir("mosael-fixture-");
  fs.mkdirSync(path.join(root, "plugins", "examples", "zh-only"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "plugins", "examples", "zh-only", "mosael.plugin.json"),
    JSON.stringify({ id: "dev.mosael.zh-only", name: { zh: "只有中文" }, summary: { zh: "中文简介" } }),
  );
  fs.mkdirSync(path.join(root, "website", "public", "workflows"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "website", "public", "workflows", "zh_only.zh.mosael-workflow.json"),
    JSON.stringify({ format: "mosael-workflow", version: 1, name: "只有中文" }),
  );
  fs.writeFileSync(
    path.join(root, "website", "public", "workflows", "catalog.json"),
    JSON.stringify([
      {
        id: "zh_only",
        name: { zh: "只有中文的工作流" },
        summary: { zh: "中文工作流简介" },
        download: { zh: "/workflows/zh_only.zh.mosael-workflow.json" },
      },
    ]),
  );

  const output = path.join(root, "bundle.json");
  const result = runExport(["--root", root, "--output", output]);
  assert.equal(result.status, 0, `fixture 导出失败:\n${result.stderr || result.stdout}`);

  const bundle = JSON.parse(fs.readFileSync(output, "utf8"));
  assert.deepEqual(Object.keys(bundle.plugins[0].locales), ["zh-CN"], "插件缺英文时被编造了 en-US");
  assert.deepEqual(bundle.plugins[0].locales["zh-CN"], { title: "只有中文", summary: "中文简介" });
  assert.deepEqual(Object.keys(bundle.workflows[0].locales), ["zh-CN"], "工作流缺英文时被编造了 en-US");
  assert.deepEqual(bundle.workflows[0].locales["zh-CN"], { title: "只有中文的工作流", summary: "中文工作流简介" });
});

test("② 合并规则:官方在前;用户分享(slug=null)在后且新的在前;命中的官方分享不重复", async () => {
  const helper = await import("../src/components/community/listed-shares.ts");

  const share = (over = {}) => ({
    id: "share-1",
    slug: null,
    kind: "plugin",
    locale: "zh-CN",
    title: "用户分享",
    summary: null,
    bytes: 10,
    license: null,
    created_at: "2026-10-01T00:00:00Z",
    author: { display_name: "Alice", handle: "alice", avatar_seed: "seed", official: false },
    stats: { downloads: 0, likes: 0, favorites: 0, comments: 0 },
    liked_by_me: false,
    favorited_by_me: false,
    ...over,
  });

  const input = [
    share({ id: "matched-official", slug: "comfyui", created_at: "2026-10-05T00:00:00Z" }),
    share({ id: "user-old", created_at: "2026-10-01T00:00:00Z" }),
    share({ id: "unmatched-official", slug: "legacy", created_at: "2026-10-03T00:00:00Z" }),
    share({ id: "user-new", created_at: "2026-10-04T00:00:00Z" }),
  ];
  const before = input.map((one) => one.id);

  const kept = helper.listedShares(input, ["comfyui", "mineru"]);
  assert.deepEqual(
    kept.map((one) => one.id),
    ["user-new", "unmatched-official", "user-old"],
    "命中静态条目的官方分享没有跳过,或分享没有按新→旧排",
  );
  assert.deepEqual(input.map((one) => one.id), before, "listedShares 改了入参顺序");

  const items = helper.mergeListing([{ slug: "comfyui" }, { slug: "mineru" }], kept);
  assert.deepEqual(items.map((one) => one.kind), ["official", "official", "share", "share", "share"], "官方卡片没有排在用户分享之前");

  // 没有用户分享时就是原样的官方列表,不会多出一节空区域。
  assert.deepEqual(helper.mergeListing([{ slug: "comfyui" }], []).map((one) => one.kind), ["official"]);
});

test("②-a 取数带 locale + kind;失败返回空数组,不把错误抛给页面", async () => {
  const helper = await import("../src/components/community/listed-shares.ts");
  const cloud = await import("../src/lib/cloud.ts");

  assert.equal(cloud.cloudLocale("zh"), "zh-CN", "zh → zh-CN 映射不对");
  assert.equal(cloud.cloudLocale("en"), "en-US", "en → en-US 映射不对");

  let seen = null;
  const shares = await helper.fetchListedShares(
    async (query) => {
      seen = query;
      return {
        items: [
          shareFixture({ id: "zh", locale: "zh-CN" }),
          shareFixture({ id: "en", locale: "en-US" }),
        ],
        next_cursor: null,
      };
    },
    "plugin",
    "zh",
  );
  assert.deepEqual(seen, {
    kind: "plugin",
    locale: "zh-CN",
    sort: "new",
    limit: helper.LISTED_SHARE_LIMIT,
  }, "取数没有带 kind + 当前语言 + 新序");
  assert.deepEqual(shares.map((one) => one.id), ["zh"], "返回里混进了别的语言");

  let workflowQuery = null;
  await helper.fetchListedShares(
    async (query) => {
      workflowQuery = query;
      return { items: [], next_cursor: null };
    },
    "workflow",
    "en",
  );
  assert.equal(workflowQuery.kind, "workflow", "工作流列表没有限定 kind=workflow");
  assert.equal(workflowQuery.locale, "en-US", "工作流列表没有带英文 locale");

  const failed = await helper.fetchListedShares(async () => {
    throw new Error("cloud down");
  }, "workflow", "en");
  assert.deepEqual(failed, [], "云端失败时应当退化成空数组(只渲染静态列表)");

  // 真正发出去的 URL 也得带 locale —— 只测注入的 loader 不够,云端默认两种都返回。
  const realFetch = globalThis.fetch;
  let requested = "";
  globalThis.fetch = async (url) => {
    requested = String(url);
    return new Response(JSON.stringify({ items: [], next_cursor: null }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    await cloud.cloudShares.list({ kind: "plugin", locale: "en-US", sort: "new", limit: 24 });
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.match(requested, /\/api\/cloud\/v1\/shares\?/, "列表请求没有打到云端 /shares");
  assert.match(requested, /kind=plugin/, "列表请求没有带 kind=plugin");
  assert.match(requested, /locale=en-US/, "列表请求没有带 locale —— 英文站会看到中文分享");
});

function shareFixture(over = {}) {
  return {
    id: "share",
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
  };
}

test("③ /plugins、/workflows 接上混排:静态卡片不动,分享卡片进同一张网格", () => {
  const pluginsPage = read(PLUGINS_PAGE);
  const workflowsPage = read(WORKFLOWS_PAGE);
  assert.match(pluginsPage, /listPlugins\(locale\)/, "/plugins 不再用静态官方插件列表");
  assert.match(pluginsPage, /<PluginBrowser locale=\{locale\} plugins=\{plugins\}/, "/plugins 没有把静态插件交给列表");
  assert.match(workflowsPage, /listWorkflows\(locale\)/, "/workflows 不再用静态官方工作流列表");
  assert.match(workflowsPage, /<WorkflowBrowser locale=\{locale\} workflows=\{workflows\}/, "/workflows 没有把静态工作流交给列表");

  // 保持静态页面(137 页):取数在浏览器里发生,不在构建期把云端结果烤进 HTML。
  assert.doesNotMatch(pluginsPage, /force-dynamic|loadListedShares|loadShare/, "/plugins 被改成了动态取数,构建页数会变");
  assert.doesNotMatch(workflowsPage, /force-dynamic|loadListedShares|loadShare/, "/workflows 被改成了动态取数,构建页数会变");

  const browse = read(BROWSE);
  assert.match(browse, /cloudShares\.list/, "列表没有向云端取分享");
  assert.match(read(HELPER), /cloudLocale\(locale\)/, "列表取数没有把当前语言映射成云端 locale");
  assert.match(browse, /useListedShares\("plugin", locale\)/, "PluginBrowser 没有取 plugin 分享");
  assert.match(browse, /useListedShares\("workflow", locale\)/, "WorkflowBrowser 没有取 workflow 分享");
  assert.match(browse, /listedShares\(shares, officialSlugs\)/, "没有按官方 slug 跳过已静态展示的官方分享");
  // 分享卡片:插件 / 工作流 / 画板三个列表各一处(画板列表全是用户分享)。
  assert.equal((browse.match(/<ShareCard/g) ?? []).length, 3, "分享卡片没有同时出现在插件、工作流和画板列表里");
  assert.match(browse, /mergeListing\(/, "官方卡片和分享卡片没有走同一条合并逻辑");
  assert.match(browse, /entry\.kind === "official"[\s\S]{0,400}<PluginCard/, "PluginBrowser 的官方条目没有用静态卡片");
  assert.match(browse, /entry\.kind === "official"[\s\S]{0,400}<WorkflowCard/, "WorkflowBrowser 的官方条目没有用静态卡片");

  const helper = read(HELPER);
  assert.match(helper, /function listedShares/, "缺少 listedShares 合并规则");
  assert.match(helper, /function mergeListing/, "缺少 mergeListing 合并规则");
  assert.match(helper, /catch\s*\{\s*return \[\]/, "取数失败没有退化成空数组");
  assert.doesNotMatch(helper, /setError|throw new CloudApiError|loadFailed/, "云端失败被做成了页面错误");

  // 分享卡片的类型标签:plugin 不能显示成工作流 —— 而且**只在一处判 kind**(lib/shareKind.ts),
  // 之前四处各写 `board ? 画布 : 工作流`,插件就被写成了工作流。
  const shares = read("components/community/shares.tsx");
  assert.match(shares, /shareKindLabel\(share\.kind, t\)/, "分享卡片没有走统一的类型名");
  const kindHelper = read("lib/shareKind.ts");
  assert.match(kindHelper, /kind === "plugin"/, "统一助手没有处理 plugin");
  assert.match(kindHelper, /kind === "board"/, "统一助手没有处理 board");
  assert.match(shares, /share\.author\.official/, "分享卡片没有显示官方标记");

  const messages = read("i18n/messages.ts");
  assert.match(messages, /kindPlugin:\s*"插件"/, "中文缺 kindPlugin");
  assert.match(messages, /kindPlugin:\s*"Plugin"/, "英文缺 kindPlugin");

  // POST /shares 现在必填 locale:上传表单也要跟着带,否则发布永远 422。
  const upload = read(UPLOAD_FORM);
  assert.match(upload, /locale:\s*cloudLocale\(locale\)/, "上传没有带 locale,云端会 422");
});
