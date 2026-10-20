import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 账号页的视觉契约:分屏、明确的字号阶梯、真实 label、密码可见性、错误区域与四态。
//: 这些断言盯的是**结构**,不是"能不能渲染"——样式被换回一张窄卡片时它们必须红。
const SRC = path.resolve(import.meta.dirname, "..", "src");
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
const read = (relative) => fs.readFileSync(path.resolve(import.meta.dirname, "..", relative), "utf8");
const source = (component) => {
  const relative = `src/components/account/${component}.tsx`;
  return fs.existsSync(path.resolve(import.meta.dirname, "..", relative)) ? read(relative) : "";
};

const shell = source("account-shell");
const controls = source("form-controls");
const login = source("login-form");
const signup = source("signup-form");

test("三页共用一套分屏骨架:桌面左表单、右产品叙事,移动端单列", () => {
  assert.match(shell, /lg:grid-cols-\[minmax\(0,0\.92fr\)_minmax\(0,1\.08fr\)\]/, "账号骨架没有桌面分屏网格");
  assert.match(shell, /<aside/, "缺少右侧品牌 / 产品叙事面板");
  assert.match(shell, /studioTitle/, "右侧没有说清 Mosael 是什么的标题");
  assert.match(shell, /studioBody/, "右侧没有产品说明");
  assert.match(shell, /BrandWordmark/, "账号页缺少品牌字标");
  assert.match(shell, /editor\.png/, "没有复用已存在的产品截图");
  assert.match(shell, /max-w-\[96rem\]/, "分屏容器没有站点级版心");
  assert.match(shell, /min-w-0/, "分屏列没有 min-w-0,窄屏会被内容撑破");
  assert.match(shell, /motion-safe:/, "入场动效没有放进 motion-safe");
  assert.match(shell, /prefers-reduced-motion|motion-reduce|motion-safe/, "没有声明减少动效时的行为");
});

test("表单控件有真实 label、聚焦环、密码可见性和错误关联", () => {
  assert.match(controls, /htmlFor=\{id\}/, "label 没有通过 htmlFor 绑定输入框");
  assert.match(controls, /<input[\s\S]*id=\{id\}/, "输入框没有稳定 id");
  assert.match(controls, /aria-describedby=\{describedBy\}/, "输入框没有把 hint / 错误关联给读屏");
  assert.match(controls, /aria-invalid=\{Boolean\(error\)\}/, "错误态没有 aria-invalid");
  assert.match(controls, /showPassword/, "没有显示密码的文案");
  assert.match(controls, /hidePassword/, "没有隐藏密码的文案");
  assert.match(controls, /aria-pressed=\{visible\}/, "密码可见性按钮没有 aria-pressed");
  assert.match(controls, /role="alert"/, "错误区域没有 role=alert");
  // 成功通知改走 toast(Radix 自带 role="status"/aria-live,见 toast.test.mjs ⑦):
  // 表单零件里不再有第二块 live region,留下的只有错误的 role=alert。
  assert.doesNotMatch(controls, /<output/, "表单零件里还留着一条内联的成功提示");
  assert.match(controls, /LoaderCircle/, "提交按钮没有 loading 图标");
  assert.match(controls, /aria-busy=\{busy\}/, "提交按钮没有 aria-busy");
  assert.match(controls, /motion-reduce:animate-none/, "loading 动画没有尊重减少动效");
});

test("登录 / 注册都有四态,且登录和注册的提交按钮可区分", () => {
  for (const [name, form] of [
    ["登录", login],
    ["注册", signup],
  ]) {
    assert.match(form, /AccountField/, `${name}表单没复用统一字段`);
    assert.match(form, /PasswordField/, `${name}表单没有密码可见性字段`);
    assert.match(form, /SubmitButton/, `${name}表单没有统一主按钮`);
    assert.match(form, /FormAlert/, `${name}表单没有错误 / 成功区域`);
    assert.match(form, /autoComplete=/, `${name}表单没有声明自动填充语义`);
  }
  assert.match(login, /registered/, "登录页没有账号创建后的成功态");
  // 注册成功**不再有中间态**:云端注册直接建会话(见 cloud/api/auth.py 的 signup),所以没有
  // 「去登录」这一步 —— 注册完就直接进自己的控制台(维护者:「注册完成就应该直接跳转」)。
  assert.match(signup, /router\.replace\(`\/\$\{locale\}\/dashboard`\)/, "注册成功后没有直接跳转控制台");
  assert.doesNotMatch(signup, /phase === "success"|setPhase\("success"\)/, "注册表单又有中间成功态了");
  assert.doesNotMatch(signup, /signupSuccessCta|\/login\?registered=1/, "注册成功后还在让用户再去登录一次");
});

// 账号页的四态(加载 / 未登录 / 失败 / 已登录)随 `/account` 一起收进了控制台:
// 现在那一页只是 `permanentRedirect(...)`(见 account-consolidation.test.mjs),
// 身份与删号都在 dashboard 那一侧,由 dashboard.test.mjs 与 account-consolidation.test.mjs 钉。

test("暗色 / 亮色文字都达到 WCAG AA(4.5:1),含右侧暗房面板", () => {
  const toRgb = (hex) => hex.match(/[0-9a-f]{2}/gi).map((pair) => parseInt(pair, 16) / 255);
  const linear = (value) => (value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  const luminance = (hex) => {
    const [r, g, b] = toRgb(hex).map(linear);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a, b) => {
    const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (high + 0.05) / (low + 0.05);
  };

  const css = read("src/app/globals.css");
  const block = (start) => css.slice(css.indexOf(start), css.indexOf("\n}", css.indexOf(start)));
  const vars = (text) =>
    Object.fromEntries([...text.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((match) => [match[1], match[2]]));
  const light = vars(block(":root {"));
  const dark = vars(block(".dark {"));

  const pairs = [
    ["亮色正文", light.ink, light.paper],
    ["亮色次要文字", light["muted-foreground"], light.paper],
    ["亮色错误文字", light.destructive, light.card],
    ["亮色主按钮", light["primary-foreground"], light.flame],
    ["亮色强调文字 / 淡紫底", light.indigo, light["brand-soft"]],
    ["暗色正文", dark.ink, dark.paper],
    ["暗色次要文字", dark["muted-foreground"], dark.paper],
    ["暗色错误文字", dark.destructive, dark.paper],
    ["暗色主按钮", dark["primary-foreground"], dark.flame],
    ["暗色强调文字 / 淡紫底", dark.indigo, dark["brand-soft"]],
    ["暗房正文", "#c7c1d2", "#0b0812"],
    ["暗房次要文字", "#aaa2b2", "#0b0812"],
    ["暗房强调文字", "#b9a9ff", "#0b0812"],
  ];
  for (const [label, foreground, background] of pairs) {
    const value = ratio(foreground, background);
    assert.ok(value >= 4.5, `${label} 对比度只有 ${value.toFixed(2)}:1 (${foreground} on ${background})`);
  }
});

test("新增文案中英同键,且没有把按钮词当标签用", () => {
  const zh = getMessages("zh").account;
  const en = getMessages("en").account;
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort(), "中英 account 文案键不一致");
  for (const key of [
    "studioEyebrow",
    "studioTitle",
    "studioBody",
    "studioCaption",
    "studioPointLocal",
    "studioPointModels",
    "studioPointTimeline",
    "cloudNote",
    "showPassword",
    "hidePassword",
    "passwordHint",
    "formErrorTitle",
  ]) {
    assert.ok(zh[key], `中文缺 account.${key}`);
    assert.ok(en[key], `英文缺 account.${key}`);
  }
  for (const locale of LOCALES) {
    const account = getMessages(locale).account;
    assert.notEqual(account.showPassword, account.hidePassword, `${locale} 的显示 / 隐藏密码文案相同`);
  }
});
