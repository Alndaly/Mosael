import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 官网的路由分组契约。
//:
//: 账号页(登录 / 注册 / 账号)不属于「站内」:顶部不该出现整站导航。这个意图由目录结构表达 ——
//: `(auth)` 组有自己的 layout,`(site)` 组才有站头 / 站尾 —— 而不是在页面里条件隐藏 header。
//: 分组名带括号,不进入 URL;下面这几条同时钉住「地址没变」和「metadata / 静态参数没丢」。
const SRC = path.resolve(import.meta.dirname, "..", "src");
const APP = path.join(SRC, "app");
const LOCALE = path.join(APP, "[locale]");
const read = (...parts) => fs.readFileSync(path.join(...parts), "utf8");
const exists = (...parts) => fs.existsSync(path.join(...parts));

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

const { LOCALES } = await import("../src/i18n/config.ts");
const { getMessages } = await import("../src/i18n/messages.ts");

/** 站内页面的 route(相对 `[locale]`),`page.tsx` 之前那段就是 URL。 */
const SITE_ROUTES = [
  "page.tsx",
  "changelog/page.tsx",
  "community/page.tsx",
  "community/[id]/page.tsx",
  "community/upload/page.tsx",
  "dashboard/page.tsx",
  "docs/page.tsx",
  "docs/[section]/[name]/page.tsx",
  "plugins/page.tsx",
  "plugins/[slug]/page.tsx",
  "workflows/page.tsx",
  "workflows/[slug]/page.tsx",
];
const AUTH_ROUTES = ["login/page.tsx", "signup/page.tsx", "account/page.tsx"];

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}

test("页面按 (site) / (auth) 分组,分组只有目录意义,页面一个都不少", () => {
  assert.ok(fs.statSync(path.join(LOCALE, "(site)")).isDirectory(), "缺少 (site) 路由组");
  assert.ok(fs.statSync(path.join(LOCALE, "(auth)")).isDirectory(), "缺少 (auth) 路由组");

  for (const route of SITE_ROUTES) {
    assert.ok(exists(LOCALE, "(site)", route), `站内页面不在 (site) 组里: ${route}`);
  }
  for (const route of AUTH_ROUTES) {
    assert.ok(exists(LOCALE, "(auth)", route), `账号页面不在 (auth) 组里: ${route}`);
    assert.ok(!exists(LOCALE, "(site)", route), `账号页面混进了 (site) 组: ${route}`);
  }

  // 分组之外不允许再有页面 —— 页面一旦落在两个组外面,它就既没有站头也没有账号壳。
  const stray = walk(LOCALE)
    .filter((file) => file.endsWith("page.tsx"))
    .filter((file) => !file.includes(`${path.sep}(site)${path.sep}`) && !file.includes(`${path.sep}(auth)${path.sep}`))
    .map((file) => path.relative(LOCALE, file));
  assert.deepEqual(stray, [], "有页面落在 (site) / (auth) 分组之外");
});

test("分组名不进 URL:每个页面还是原来的地址", () => {
  const urls = [...SITE_ROUTES, ...AUTH_ROUTES]
    .map((route) => `/${route.replace(/\/?page\.tsx$/, "")}`.replace(/\/$/, ""))
    .map((url) => (url === "/" ? "" : url))
    .sort();
  assert.deepEqual(
    urls,
    [
      "",
      "/account",
      "/changelog",
      "/community",
      "/community/[id]",
      "/community/upload",
      "/dashboard",
      "/docs",
      "/docs/[section]/[name]",
      "/login",
      "/plugins",
      "/plugins/[slug]",
      "/signup",
      "/workflows",
      "/workflows/[slug]",
    ].sort(),
  );
});

test("根 [locale] 布局只留与分组无关的东西,不再渲染站头 / 站尾", () => {
  const layout = read(LOCALE, "layout.tsx");
  assert.doesNotMatch(layout, /<SiteHeader/, "根布局仍在渲染站头");
  assert.doesNotMatch(layout, /<SiteFooter/, "根布局仍在渲染站尾");
  assert.doesNotMatch(layout, /import \{ SiteHeader \}/, "根布局仍导入站头");
  assert.doesNotMatch(layout, /import \{ SiteFooter \}/, "根布局仍导入站尾");

  // i18n / metadata / 静态参数必须留在这一层 —— 它们和分组无关,搬走就会丢页面。
  assert.match(layout, /export function generateStaticParams/, "根布局丢了 generateStaticParams");
  assert.match(layout, /LOCALES\.map\(\(locale\) => \(\{ locale \}\)\)/, "根布局的静态语言参数变了");
  assert.match(layout, /export async function generateMetadata/, "根布局丢了 generateMetadata");
  assert.match(layout, /applicable-device/, "百度的 applicable-device 声明不见了");
  assert.match(layout, /no-transform/, "百度转码声明不见了");
});

test("(site) 布局拥有站头 / 站尾,内容和首页的 5rem 悬浮位一起搬过去", () => {
  const layout = read(LOCALE, "(site)", "layout.tsx");
  assert.match(layout, /import \{ SiteHeader \}/);
  assert.match(layout, /import \{ SiteFooter \}/);
  assert.match(layout, /<SiteHeader locale=\{locale\}/, "(site) 布局没有渲染站头");
  assert.match(layout, /<SiteFooter locale=\{locale\}/, "(site) 布局没有渲染站尾");
  assert.match(layout, /<main id="main" className="pt-20">/, "(site) 布局没有保留悬浮站头的内容留白");
  assert.doesNotMatch(layout, /generateStaticParams/, "分组布局不该重复声明静态语言参数");
});

test("(auth) 布局没有整站导航,只留一个可跳转的 main", () => {
  const layout = read(LOCALE, "(auth)", "layout.tsx");
  assert.doesNotMatch(layout, /SiteHeader|site-header/, "(auth) 布局引用了站头");
  assert.doesNotMatch(layout, /SiteFooter|site-footer/, "(auth) 布局引用了站尾");
  assert.doesNotMatch(layout, /<header[\s>]/, "(auth) 布局自己又画了一个 header");
  assert.match(layout, /<main id="main"/, "(auth) 布局缺少 main,跳到正文的链接会落空");

  for (const route of AUTH_ROUTES) {
    const page = read(LOCALE, "(auth)", route);
    assert.doesNotMatch(page, /SiteHeader|<header[\s>]/, `${route} 里出现了整站导航`);
    assert.match(page, /AccountShell/, `${route} 没有走账号壳`);
  }
});

test("账号壳里有一条回到 mosael.com 的小链接,站内布局的站头也还在", () => {
  const shell = read(SRC, "components", "account", "account-shell.tsx");
  assert.match(shell, /copy\.backToSite/, "账号壳没有返回站内的文案");
  assert.match(shell, /href=\{`\/\$\{locale\}`\}/, "返回链接没有指向当前语言的站点首页");
  const backLinkClass = shell.match(/className="([^"]*)"[\s\S]{0,400}?\{copy\.backToSite\}/)?.[1] ?? "";
  assert.match(backLinkClass, /text-xs/, "返回入口不是小字,会抢表格单的注意力");
  assert.doesNotMatch(backLinkClass, /bg-primary|border-2|px-5/, "返回入口被做成了主按钮");

  for (const locale of LOCALES) {
    const copy = getMessages(locale).account;
    assert.match(copy.backToSite, /mosael\.com/i, `${locale} 的返回入口没有写清 mosael.com`);
  }

  // 站头仍然被站内组使用,不能因为账号页不要它就被删掉。
  assert.ok(exists(SRC, "components", "site-header.tsx"), "site-header.tsx 被删了,站内页面会没有导航");
  assert.match(read(SRC, "components", "site-header.tsx"), /export function SiteHeader/);
});
