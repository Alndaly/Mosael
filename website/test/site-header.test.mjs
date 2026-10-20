import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

//: 顶栏右簇的视觉契约:登录不再夹在右簇左端,而是紧贴「下载」左侧、整簇贴右;
//: 登录从纯文字链接改成安静的描边次级按钮,不与「下载」的主行动抢视觉重量。
//: 断言盯的是**结构**(DOM 顺序、容器对齐、按钮组件与 variant),样式被改回纯文字时必须红。
const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");

const header = read("src/components/site-header.tsx");
const accountNav = read("src/components/account/account-nav.tsx");
const mobileMenu = read("src/components/mobile-menu.tsx");
const button = read("src/components/ui/button.tsx");

/** 去掉 JSX 注释后再看顺序,免得被注释里的字样带偏。 */
const stripComments = (text) => text.replace(/\{\/\*[\s\S]*?\*\/\}/g, "");

/** 右簇 = `ml-auto` 那个容器里的内容。 */
function rightCluster(source) {
  const cleaned = stripComments(source);
  const start = cleaned.indexOf('className="ml-auto');
  assert.notEqual(start, -1, "顶栏找不到 `ml-auto` 的右簇容器");
  const open = cleaned.indexOf(">", start);
  const rest = cleaned.slice(open + 1);
  const end = rest.indexOf("</div>");
  assert.notEqual(end, -1, "右簇容器的闭合标签找不到");
  return rest.slice(0, end);
}

test("登录紧贴「下载」左侧,整簇靠右(容器 ml-auto、版心不变)", () => {
  const cluster = rightCluster(header);

  // 版心(居中 + 限宽)保持原样,只让这一簇贴右。
  assert.match(header, /mx-auto flex h-14 max-w-\[82rem\]/, "顶栏版心(居中 / 限宽)被改动了");
  assert.match(header, /<div className="ml-auto[^"]*"/, "右簇没有 ml-auto,不会贴右");

  const account = cluster.indexOf("<AccountNav");
  const download = cluster.indexOf("<DownloadLink");
  const menu = cluster.indexOf("<MobileMenu");
  assert.notEqual(account, -1, "右簇里没有账号入口");
  assert.notEqual(download, -1, "右簇里没有「下载」");
  assert.notEqual(menu, -1, "右簇里没有窄屏菜单");

  // ① 位置:登录在「下载」左侧,且紧邻(两者之间没有别的控件)。
  assert.ok(account < download, "「登录」仍在「下载」右边");
  assert.ok(download < menu, "「下载」不在窄屏菜单之前,右簇顺序被改了");
  const between = cluster.slice(account, download);
  assert.match(between, /^<AccountNav[\s\S]*\/>\s*$/, "「登录」和「下载」之间夹了别的东西");

  // 登录之前必须已经过了 GitHub 图标:说明它从簇的左端挪到了簇的末尾。
  assert.ok(cluster.indexOf("<GithubMark") < account, "「登录」仍夹在右簇左端 / GitHub 图标之前");
});

test("登录是次级按钮(复用 Button + outline),不是纯文字链接", () => {
  assert.match(accountNav, /from "@\/components\/ui\/button"/, "登录没有复用现成的 Button");
  assert.match(accountNav, /<Button[\s\S]*?asChild/, "登录不是 `Button asChild`(会渲染成 div 或丢掉按钮语义)");
  assert.match(accountNav, /variant="outline"/, "登录没有用已有的 outline variant");
  assert.match(accountNav, /size="lg"/, "登录没有用按钮的尺寸档,高度会与右簇对不齐");
  assert.match(accountNav, /rounded-full/, "登录按钮没有沿用顶栏的胶囊圆角");
  assert.match(accountNav, /<Link[\s\S]*?loginLabel/, "登录按钮里没有指向登录页的链接");

  // 它仍然是链接(键盘可达),没有被换成 div / span 伪装。
  assert.match(accountNav, /<Link[\s\S]*?href=\{`\/\$\{locale\}\/(account|login)/, "登录的链接目标语义丢了");
  assert.doesNotMatch(accountNav, /<div\b|<span\b/, "登录被改成了没有链接语义的元素");

  // 显示文字已经说清是「登录」,不再叠一个重复的 aria-label。
  assert.doesNotMatch(accountNav, /aria-label=\{?(loginLabel|accountLabel)/, "aria-label 与可见文字重复");
});

test("登录与「下载」不同视觉重量:一个描边、一个实心主色", () => {
  assert.match(header, /<DownloadLink[\s\S]*?bg-primary/, "「下载」不再是实心主色按钮");
  assert.match(header, /<DownloadLink[\s\S]*?text-primary-foreground/, "「下载」丢了主色按钮的文字色");
  assert.doesNotMatch(accountNav, /bg-primary\b/, "「登录」用了主色实心,会抢「下载」");
  assert.doesNotMatch(accountNav, /text-primary-foreground/, "「登录」用了主色按钮的文字色");
  assert.match(accountNav, /border-border|border\b/, "「登录」没有描边,看不出是次级按钮");
  assert.match(accountNav, /text-muted-foreground/, "「登录」没有压到次要文字色");
});

test("登录有 hover / 键盘 focus 的可见反应", () => {
  assert.match(accountNav, /hover:bg-/, "登录没有 hover 背景反馈");
  // 焦点环来自被复用的 Button 基类,不是这一颗按钮自己漏掉的样式。
  assert.match(accountNav, /<Button\b/, "登录没有复用 Button,键盘焦点反应就没有来源");
  assert.match(button, /focus-visible:ring/, "Button 基类没有 focus-visible 焦点环");
  assert.match(button, /focus-visible:border-ring/, "Button 基类没有 focus-visible 描边");
});

test("窄屏菜单没有另起一套登录样式", () => {
  // 现状:移动端菜单里没有登录项,唯一的登录入口是 AccountNav。
  // 以后若把登录加进菜单,也必须复用同一颗按钮,而不是在这里再画一个纯文字链接。
  assert.doesNotMatch(mobileMenu, /AccountNav|loginLabel/, "移动端菜单里出现了第二套登录入口,需与顶栏同一颗按钮");
  assert.doesNotMatch(mobileMenu, /<Link[\s\S]{0,200}登录/, "移动端菜单里写了第二个纯文字登录链接");
});
