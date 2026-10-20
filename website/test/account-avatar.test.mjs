import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 顶栏已登录入口的契约:不再是「账号」两个字,而是一颗 36px 的圆形头像 ——
//: 账号名的第一个字(中文取第一个字、英文大写)、按名字固定的底色、说清含义的 aria-label,
//: 点进去仍然去账号页。未登录那颗「登录」按钮保持 816c0c714 定稿的描边次级按钮。
//:
//: 取名 / 取首字 / 取色相是纯函数,值得真的跑一遍,而不是用正则猜行为:仓库里没有 JSX
//: 运行器,所以把组件之前的纯函数抽成一个临时 .ts 模块直接 import。渲染那部分仍然看源码
//: 结构(DOM 顺序、类名、链接目标)—— 样式被改回一行文字时它们必须红。
const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const accountNav = read("src/components/account/account-nav.tsx");

/**
 * 组件之前的纯函数抽成临时模块。文件结构约定:import 之后、`export function AccountNav`
 * 之前只放这些纯函数,于是这里切出来的就是可以独立跑的 JS(去掉 import 与 "use client")。
 */
async function loadLogic() {
  const cut = accountNav.indexOf("export function AccountNav");
  if (cut === -1) throw new Error("account-nav 里找不到 `export function AccountNav`");
  const head = accountNav
    .slice(0, cut)
    .split("\n")
    .filter((line) => !/^import\b/.test(line) && line.trim() !== '"use client";')
    .join("\n");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-account-avatar-"));
  const file = path.join(dir, "logic.ts");
  fs.writeFileSync(file, `${head}\nexport { accountName, initialOf, hueOf, avatarStyle, avatarLabel };\n`, "utf8");
  return import(pathToFileURL(file).href);
}

let logic = null;
try {
  logic = await loadLogic();
} catch {
  // 现在是一行文字「账号」,没有这套纯函数 —— 下面的断言会给出明确的红。
  logic = null;
}

/** 拿到纯函数模块;还没有就红在「没有可测的纯函数」上,而不是一个莫名其妙的 TypeError。 */
function logicModule() {
  assert.ok(logic, "account-nav 里还没有抽出来的账号名 / 首字 / 色相纯函数");
  return logic;
}

/** 头像那颗链接的 className。整个文件里只有头像用 size-9。 */
function avatarClass() {
  const found = accountNav.replace(/\s+/g, " ").match(/className="([^"]*\bsize-9\b[^"]*)"/);
  assert.ok(found, "顶栏找不到 36px(size-9)的账号头像");
  return found[1];
}

test("① 已登录渲染成圆形头像:链接 + 圆形 + 36px,不再是「账号」两个字", () => {
  const cls = avatarClass();
  assert.match(cls, /rounded-full/, "头像不是圆形");
  assert.match(accountNav, /<Link\b/, "头像不是链接(键盘到不了)");
  assert.match(accountNav, /\{initialOf\(/, "头像里没有放账号名的首字");
  assert.doesNotMatch(accountNav, /\{accountLabel\}\s*<\/Link>/, "已登录入口还在渲染「账号」文字");
});

test("① 头像直径与旁边那排图标按钮同一档(量过:GitHub / 主题 / 语言 / 搜索都是 36px)", () => {
  assert.match(avatarClass(), /\bsize-9\b/, "头像不是 36px,和 h-9 那排图标按钮对不齐");
});

test("① 头像有 hover / 键盘 focus 的可见反应", () => {
  const cls = avatarClass();
  assert.match(cls, /hover:/, "头像 hover 没有可见反应");
  assert.match(cls, /focus-visible:ring/, "头像键盘 focus 没有焦点环");
});

test("② 英文名取首字母,大写", () => {
  const { accountName, initialOf } = logicModule();
  assert.equal(initialOf(accountName({ display_name: "ada lovelace", handle: "ada", email: "ada@example.com" })), "A");
});

test("② 中文名取第一个字(中文没有大小写,不能被 toUpperCase 吃掉)", () => {
  const { accountName, initialOf } = logicModule();
  assert.equal(initialOf(accountName({ display_name: "张三", handle: "zhangsan", email: "z@example.com" })), "张");
});

test("② display_name 缺失时退回 handle,再缺退回邮箱前缀,且不会把完整邮箱放进 DOM", () => {
  const { accountName } = logicModule();
  assert.equal(accountName({ display_name: null, handle: "grace", email: "grace@example.com" }), "grace");
  assert.equal(accountName({ display_name: "  ", handle: "grace", email: "grace@example.com" }), "grace");
  assert.equal(accountName({ display_name: null, handle: null, email: "lin@example.com" }), "lin");
  assert.ok(!accountName({ display_name: null, handle: null, email: "lin@example.com" }).includes("@"), "邮箱域名进了名字");
});

test("③ 同一个名字永远是同一个底色", () => {
  const { avatarStyle, accountName, hueOf } = logicModule();
  assert.deepEqual(avatarStyle("张三"), avatarStyle("张三"), "同一个名字调两次颜色不一样");
  const fromDisplay = accountName({ display_name: "ada", handle: null, email: "ada@example.com" });
  const fromHandle = accountName({ display_name: null, handle: "ada", email: "ada@example.com" });
  assert.equal(fromDisplay, fromHandle);
  assert.deepEqual(avatarStyle(fromDisplay), avatarStyle(fromHandle), "同一个名字换了来源就换了颜色");
  assert.match(hueOf("张三"), /^var\(--tile-[1-6]\)$/, "底色不是现有的 --tile-* token");
  assert.doesNotMatch(accountNav, /Math\.random/, "底色是随机挑的,同一个人每次刷新都不一样");
});

test("④ aria-label 含「账号」和名字", () => {
  const { avatarLabel } = logicModule();
  const label = avatarLabel("账号", "张三");
  assert.match(label, /账号/, "aria-label 没说清这是账号");
  assert.match(label, /张三/, "aria-label 里没有名字");
  assert.match(accountNav, /avatarLabel\(accountLabel, name\)/, "标签不是「账号 + 名字」拼出来的");
  // 有未读角标时,数字也要进 aria-label(角标本身 aria-hidden,读屏不能只念名字)。
  assert.match(accountNav, /badge \? .*avatarLabel\(accountLabel, name\).* : avatarLabel\(accountLabel, name\)/, "未读数字没有进 aria-label");
  assert.match(accountNav, /aria-label=\{label\}/, "头像没有 aria-label,读屏只会念一个字母");
});

test("⑤ 未登录仍是「登录」描边按钮(回归)", () => {
  assert.match(accountNav, /variant="outline"/);
  assert.match(accountNav, /size="lg"/);
  assert.match(accountNav, /\{loginLabel\}/);
  assert.match(accountNav, /\/\$\{locale\}\/login/);
});

test("⑥ 头像去「我的」控制台(不再去 /account)", () => {
  assert.match(accountNav, /href=\{`\/\$\{locale\}\/dashboard`\}/, "头像的链接目标不是控制台");
  assert.doesNotMatch(accountNav, /href=\{`\/\$\{locale\}\/account`\}/, "头像还在去 /account");
});

test("移动端同一套:头像没有 hidden 只留桌面", () => {
  assert.doesNotMatch(avatarClass(), /\bhidden\b/, "头像在窄屏被藏起来了,手机上就没有账号入口");
});
