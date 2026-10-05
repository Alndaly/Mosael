import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 官网的 SEO 契约。此前根布局写了 canonical = 首页,插件页、工作流页、更新日志没写自己那份,于是全都
//: 声明「我的规范地址是首页」;sitemap 漏了插件和工作流详情;没有一条测试看得见。这里把它们钉住:
//: 每一页都有自己的标题、描述、canonical 和 hreflang,sitemap 列全有正文的页,结构化数据是合法的 JSON
//: 且只写查得到的事实。
const SRC = path.resolve(import.meta.dirname, "..", "src");
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) {
      return nextResolve(pathToFileURL(path.join(SRC, `${specifier.slice(2)}.ts`)).href, context);
    }
    // 源码里的相对导入不带扩展名(`./docs-navigation`),打包器认得,node 不认。
    if (/^\.\.?\//.test(specifier) && !path.extname(specifier) && context.parentURL?.includes("/src/")) {
      return nextResolve(`${specifier}.ts`, context);
    }
    return nextResolve(specifier, context);
  },
});

const { LOCALES, HTML_LANG, DEFAULT_LOCALE } = await import("../src/i18n/config.ts");
const { getMessages } = await import("../src/i18n/messages.ts");
const { listDocs } = await import("../src/lib/docs.ts");
const { listPlugins, listWorkflows } = await import("../src/lib/registry.ts");
const { SITE } = await import("../src/lib/site.ts");
const seo = await import("../src/lib/seo.ts");
const ld = await import("../src/lib/structured-data.ts");
const { default: sitemap } = await import("../src/app/sitemap.ts");
const { default: robots } = await import("../src/app/robots.ts");

/** 按「看得见的字」数长度:一个汉字算一个。 */
const length = (text) => Array.from(text).length;
/**
 * 搜索结果标题按显示宽度截断:一个汉字(和全角标点)约等于两个拉丁字母宽。百度按字节、Google 按像素,
 * 换算下来都在 60~70 个半角宽度上下。
 */
const width = (text) => Array.from(text).reduce((sum, char) => sum + (/[\u2E80-\uFFEF]/.test(char) ? 2 : 1), 0);
const TITLE_WIDTH = 72;

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}

test("pageMetadata:canonical 指向自己,hreflang 两种语言加 x-default,分享卡片同一个地址", () => {
  for (const locale of LOCALES) {
    const meta = seo.pageMetadata({ locale, path: "/docs/start/intro", title: "Intro", description: "About it.", keywords: ["a", "b"] });
    assert.equal(meta.alternates.canonical, `/${locale}/docs/start/intro`);
    assert.deepEqual(Object.keys(meta.alternates.languages).sort(), [...LOCALES.map((item) => HTML_LANG[item]), "x-default"].sort());
    assert.equal(meta.alternates.languages["x-default"], `/${DEFAULT_LOCALE}/docs/start/intro`);
    assert.equal(meta.openGraph.url, meta.alternates.canonical);
    assert.equal(meta.openGraph.locale, seo.OG_LOCALE[locale]);
    assert.match(meta.openGraph.locale, /^[a-z]{2}_[A-Z]{2}$/, "Open Graph 的 locale 用下划线");
    assert.equal(meta.twitter.card, "summary_large_image");
    assert.equal(meta.title.absolute, "Intro | Mosael");
    assert.deepEqual(meta.keywords, ["a", "b"]);
  }
  // 标题里已经有品牌名就不再补一遍。
  assert.equal(seo.withSiteName("Mosael – AI"), "Mosael – AI");
});

test("分享卡片的图在 public 里,尺寸就是声明的 1200×630", () => {
  for (const locale of LOCALES) {
    const image = seo.ogImage(locale);
    const file = path.resolve("public", image.url.slice(1));
    assert.ok(fs.existsSync(file), `缺少 ${image.url}`);
    const header = fs.readFileSync(file);
    assert.equal(header.readUInt32BE(16), image.width, image.url);
    assert.equal(header.readUInt32BE(20), image.height, image.url);
    assert.ok(image.alt.length > 10);
  }
});

test("每一个页面路由都经 pageMetadata 出 <head>,根布局不再写会被继承的 canonical 和 Open Graph", () => {
  const pages = walk(path.join(SRC, "app", "[locale]")).filter((file) => file.endsWith("page.tsx"));
  assert.ok(pages.length >= 7, `只找到 ${pages.length} 个页面,目录结构变了吗`);
  const missing = pages
    .filter((file) => {
      const text = fs.readFileSync(file, "utf8");
      // `/docs` 只做跳转,没有自己的内容可描述。
      if (/redirect\(/.test(text) && !/generateMetadata/.test(text)) return false;
      return !/export async function generateMetadata/.test(text) || !/pageMetadata\(/.test(text);
    })
    .map((file) => path.relative(SRC, file));
  assert.deepEqual(missing, []);

  const layout = fs.readFileSync(path.join(SRC, "app", "[locale]", "layout.tsx"), "utf8");
  assert.doesNotMatch(layout, /\balternates\s*:/, "根布局写了 alternates,子页面会继承它的 canonical");
  assert.doesNotMatch(layout, /\bopenGraph\s*:/, "根布局写了 openGraph,子页面会继承首页的分享卡片");
  assert.match(layout, /applicable-device/, "百度的 applicable-device 声明不见了");
  assert.match(layout, /no-transform/, "百度转码声明不见了");
});

test("站长验证码只从环境读,没配的那家不出 meta", () => {
  assert.equal(seo.siteVerification({}), undefined);
  assert.equal(seo.siteVerification({ SITE_VERIFICATION_BAIDU: "  " }), undefined);
  assert.deepEqual(seo.siteVerification({ SITE_VERIFICATION_GOOGLE: "g-code", SITE_VERIFICATION_BAIDU: "codeva-x" }), {
    google: "g-code",
    other: { "baidu-site-verification": "codeva-x" },
  });
  // 仓库里不能出现一个具体的验证码(那是维护者在平台上领的,写死就是替他做了决定)。
  const offenders = walk(SRC).filter((file) => /baidu-site-verification"\s*content=|codeva-[A-Za-z0-9]/.test(fs.readFileSync(file, "utf8")));
  assert.deepEqual(offenders, []);
});

test("sitemap 列全两种语言的文档、插件和工作流详情,每条都带 hreflang 与 x-default,不列跳转", () => {
  const entries = sitemap();
  const urls = entries.map((entry) => entry.url);
  assert.equal(new Set(urls).size, urls.length, "sitemap 里有重复的地址");
  const expect = (url) => assert.ok(urls.includes(url), `sitemap 缺 ${url}`);
  for (const locale of LOCALES) {
    expect(`${SITE.url}/${locale}`);
    expect(`${SITE.url}/${locale}/workflows`);
    expect(`${SITE.url}/${locale}/plugins`);
    expect(`${SITE.url}/${locale}/changelog`);
    for (const doc of listDocs(locale)) expect(`${SITE.url}/${locale}/docs/${doc.section}/${doc.name}`);
    for (const workflow of listWorkflows(locale)) expect(`${SITE.url}/${locale}/workflows/${workflow.slug}`);
    for (const plugin of listPlugins(locale)) expect(`${SITE.url}/${locale}/plugins/${plugin.slug}`);
  }
  for (const entry of entries) {
    assert.ok(entry.url.startsWith(`${SITE.url}/`), entry.url);
    assert.ok(!entry.url.endsWith("/docs"), `${entry.url} 是一条跳转`);
    const languages = entry.alternates?.languages ?? {};
    assert.deepEqual(Object.keys(languages).sort(), [...LOCALES.map((item) => HTML_LANG[item]), "x-default"].sort(), entry.url);
    assert.ok(Object.values(languages).includes(entry.url), `${entry.url} 的 hreflang 里没有它自己`);
  }
  assert.ok(!urls.includes(SITE.url) && !urls.includes(`${SITE.url}/`), "根路径是一条跳转");
});

test("robots 放行全站、指向 sitemap,只挡站内搜索的 JSON", () => {
  const rules = robots();
  assert.equal(rules.sitemap, `${SITE.url}/sitemap.xml`);
  assert.equal(rules.rules.allow, "/");
  assert.deepEqual(rules.rules.disallow, LOCALES.map((locale) => `/${locale}/search.json`));
});

test("首页与各页的标题、描述长度落在搜索结果显示得下的范围里", () => {
  const limits = { en: { description: [110, 170] }, zh: { description: [50, 130] } };
  for (const locale of LOCALES) {
    const t = getMessages(locale);
    const limit = limits[locale];
    assert.ok(width(t.meta.title) <= TITLE_WIDTH, `${locale} 首页标题宽 ${width(t.meta.title)}`);
    const [min, max] = limit.description;
    assert.ok(length(t.meta.description) >= min && length(t.meta.description) <= max, `${locale} 首页描述 ${length(t.meta.description)} 字`);
    assert.ok(t.meta.keywords.length >= 5 && t.meta.keywords.length <= 15, "关键词别堆");
    for (const page of [t.plugins, t.workflows]) {
      assert.ok(width(seo.withSiteName(page.seoTitle)) <= TITLE_WIDTH, `${locale} ${page.seoTitle}`);
    }
    assert.ok(length(t.workflows.seoDescription) <= max + 40, `${locale} 工作流页描述太长`);
  }
});

test("每篇文档都有描述,<title> 在一种语言里不重复,seo_title 不超长", () => {
  for (const locale of LOCALES) {
    const titles = new Map();
    for (const doc of listDocs(locale)) {
      const key = `${locale}/${doc.section}/${doc.name}`;
      assert.ok(doc.description.trim().length > 10, `${key} 没有描述`);
      assert.ok(!/^["']|["']$/.test(doc.title), `${key} 的标题带着引号上了页面`);
      const title = seo.withSiteName(doc.seoTitle || doc.title);
      assert.ok(width(title) <= TITLE_WIDTH, `${key} 的 <title> 宽 ${width(title)}:${title}`);
      assert.ok(!titles.has(title), `${key} 与 ${titles.get(title)} 的 <title> 相同`);
      titles.set(title, key);
      assert.ok(doc.keywords.length <= 10, `${key} 关键词别堆`);
    }
  }
});

test("首页的模板卡片都指向目录里真有的工作流", () => {
  for (const locale of LOCALES) {
    const slugs = new Set(listWorkflows(locale).map((workflow) => workflow.slug));
    for (const template of getMessages(locale).home.templates) {
      assert.ok(slugs.has(template.slug), `${locale} 首页模板 ${template.slug} 不在工作流目录里`);
    }
  }
});

test("结构化数据是合法的 JSON,只写查得到的事实", () => {
  for (const locale of LOCALES) {
    const t = getMessages(locale);
    const software = ld.softwareApplicationLd({
      locale,
      description: t.meta.description,
      features: t.home.chapters.map((chapter) => chapter.title),
      screenshots: ["/media/screens/boards.png"],
      keywords: t.meta.keywords,
    });
    const graph = [ld.organizationLd(), ld.websiteLd(t.meta.description), software, ld.faqLd(t.home.faq)];
    const parsed = JSON.parse(ld.serializeJsonLd(graph));
    for (const node of parsed) {
      assert.equal(node["@context"], "https://schema.org");
      assert.ok(node["@type"]);
    }
    const app = parsed[2];
    assert.equal(app["@type"], "SoftwareApplication");
    assert.equal(app.name, "Mosael");
    assert.match(app.operatingSystem, /macOS/);
    assert.match(app.operatingSystem, /Windows/);
    assert.equal(app.offers.price, "0");
    assert.equal(app.downloadUrl, SITE.releases);
    assert.ok(app.license.endsWith("/LICENSE"), "许可指向仓库里的 LICENSE 原文");
    assert.ok(app.screenshot.every((url) => url.startsWith("https://")), "截图要绝对地址");
    // 编出来的评分、评价、下载量比没有更糟。
    for (const field of ["aggregateRating", "review", "interactionStatistic", "downloads"]) assert.ok(!(field in app), field);

    const faq = parsed[3];
    assert.equal(faq.mainEntity.length, t.home.faq.length);
    assert.ok(faq.mainEntity.length >= 5);
    for (const entry of faq.mainEntity) {
      assert.ok(entry.name.trim() && entry.acceptedAnswer.text.trim().length > 20, entry.name);
    }
  }
  // 数据里出现 </script> 也关不掉脚本块。
  assert.ok(!ld.serializeJsonLd({ text: "</script><script>alert(1)</script>" }).includes("</script>"));
  const crumbs = ld.breadcrumbLd([{ name: "Mosael", path: "/en" }, { name: "Docs", path: "/en/docs/start/intro" }]);
  assert.deepEqual(crumbs.itemListElement.map((item) => item.position), [1, 2]);
  assert.ok(crumbs.itemListElement.every((item) => item.item.startsWith(`${SITE.url}/`)));
});

test("对外文案不说 Mosael 是开源软件 —— 许可是专有的", () => {
  //: 常见问题里可以**回答**「是不是开源」(答案是否定的),但任何地方都不能把它说成开源。
  const claims = /(?<!not |isn't |不是)(?:open[- ]source (?:AI|video|desktop|app|studio|alternative|software)|开源(?:软件|项目|的 ?AI|替代|剪辑)(?!吗))/i;
  const sources = [
    ...LOCALES.map((locale) => JSON.stringify(getMessages(locale))),
    fs.readFileSync(path.resolve("..", "README.md"), "utf8"),
    fs.readFileSync(path.resolve("..", "README.zh-CN.md"), "utf8"),
  ];
  for (const text of sources) assert.doesNotMatch(text, claims);
  for (const locale of LOCALES) {
    const answers = getMessages(locale).home.faq.map((entry) => entry.answer).join("\n");
    assert.match(answers, locale === "zh" ? /不是开源许可/ : /not an open-source one/);
  }
});
