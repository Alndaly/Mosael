import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 「操作成功了」的通知走 shadcn/ui 的 toast(Radix Toast),发完就弹、不再占版面;
//: 错误仍然留在字段旁边(FormAlert),不跟着改成 toast。
//:
//: 这里盯的是结构:toast 三件套在不在、用的是不是现成的 radix-ui、Toaster 只挂一处、
//: 四处成功提示是不是真的换成了 toast、内联的 FormNotice 是不是删干净了。
const ROOT = path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "src");

const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const maybeRead = (relative) => {
  const file = path.join(ROOT, relative);
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
};
const exists = (relative) => fs.existsSync(path.join(ROOT, relative));

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

const { getMessages } = await import("../src/i18n/messages.ts");

const walk = (dir) =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });

const sourceFiles = walk(SRC).filter((file) => /\.(ts|tsx)$/.test(file));
const layoutFiles = sourceFiles.filter((file) => file.endsWith("layout.tsx"));

const toastComponent = maybeRead("src/components/ui/toast.tsx");
const toaster = maybeRead("src/components/ui/toaster.tsx");
const hook = maybeRead("src/components/ui/use-toast.ts");
const controls = maybeRead("src/components/account/form-controls.tsx");
const signup = maybeRead("src/components/account/signup-form.tsx");
const login = maybeRead("src/components/account/login-form.tsx");
// 账号页并进控制台后只剩跳转;它原来的删号错误提示跟危险区一起搬到了控制台。
const dangerZone = maybeRead("src/components/account/account-danger-zone.tsx");
const profile = maybeRead("src/components/account/dashboard-profile.tsx");
const pkg = JSON.parse(read("package.json"));

test("① toast 三件套存在,且用的是现成的 radix-ui(Radix Toast),不是 sonner", () => {
  assert.ok(exists("src/components/ui/toast.tsx"), "没有 src/components/ui/toast.tsx");
  assert.ok(exists("src/components/ui/toaster.tsx"), "没有 src/components/ui/toaster.tsx");
  assert.ok(exists("src/components/ui/use-toast.ts"), "没有 src/components/ui/use-toast.ts");
  assert.match(toastComponent, /from "radix-ui"/, "toast 没有基于现成的 radix-ui");
  assert.match(toastComponent, /Toast as ToastPrimitive/, "toast 没有从 radix-ui 取 Toast 原子");
  assert.match(
    toastComponent,
    /ToastPrimitive\.(Root|Title|Description|Close|Provider|Viewport)/,
    "toast 没有用 Radix 的 Toast 原子拼出来",
  );
  assert.equal(pkg.dependencies.sonner, undefined, "不许为了 toast 新增 sonner");
  assert.ok(pkg.dependencies["radix-ui"], "radix-ui 不该从依赖里消失");
  assert.match(controls, /export function FormAlert/, "错误提示控件 FormAlert 不该被删");
});

test("② 全站只挂一处 Toaster,挂在盖住两组页面的根布局里", () => {
  const mounted = layoutFiles.filter((file) => /<Toaster/.test(fs.readFileSync(file, "utf8")));
  assert.equal(
    mounted.length,
    1,
    `Toaster 必须只挂一处,现在挂在:${mounted.map((file) => path.relative(ROOT, file)).join(", ") || "无"}`,
  );
  const rootLayout = path.join(SRC, "app", "[locale]", "layout.tsx");
  assert.equal(mounted[0], rootLayout, "Toaster 应挂在 [locale] 根布局,才能同时盖住 (site) 与 (auth)");
  assert.match(fs.readFileSync(rootLayout, "utf8"), /import \{ Toaster \}/, "根布局没有引入 Toaster");
  assert.match(toaster, /<ToastViewport/, "toaster 没有渲染 Radix 的 viewport");
});

test("③ 注册页发码成功后直接弹 toast,页面上不再有那条内联提示", () => {
  assert.doesNotMatch(signup, /FormNotice/, "注册页还在用内联的 FormNotice");
  assert.match(signup, /toast\(\{ title: copy\.codeSent \}\)/, "发码成功没有弹 toast");
  assert.match(signup, /import \{ toast \} from "@\/components\/ui\/use-toast"/, "注册页没有引入 toast");
});

test("④ 失败仍然是字段旁的 FormAlert(回归,没有跟着改成 toast)", () => {
  for (const [name, source] of [
    ["注册", signup],
    ["登录", login],
    ["删除账号", dangerZone],
    ["个人信息", profile],
  ]) {
    assert.match(source, /<FormAlert id=/, `${name}页丢了内联的错误提示`);
    assert.doesNotMatch(source, /toast\(\{ title: (error|copy\.actionFailed|copy\.saveFailed)/, `${name}页把错误也改成了 toast`);
  }
});

test("⑤ FormNotice 已删除,全仓没有任何引用", () => {
  const offenders = sourceFiles
    .filter((file) => fs.readFileSync(file, "utf8").includes("FormNotice"))
    .map((file) => path.relative(ROOT, file));
  assert.deepEqual(offenders, [], `仍在引用 FormNotice:${offenders.join(", ")}`);
  assert.doesNotMatch(controls, /export function FormNotice/, "form-controls 里还留着 FormNotice");
});

test("⑥ toast 文案仍然来自 messages.ts(中英各一条)", () => {
  const zh = getMessages("zh");
  const en = getMessages("en");
  assert.equal(typeof zh.toast?.close, "string", "中文缺少关闭 toast 的文案");
  assert.equal(typeof en.toast?.close, "string", "英文缺少关闭 toast 的文案");
  assert.notEqual(zh.toast.close, en.toast.close, "中英关闭文案是同一句,等于没翻译");
  assert.notEqual(zh.account.codeSent, en.account.codeSent, "发码成功的文案没有英文版");
  assert.notEqual(zh.dashboard.saved, en.dashboard.saved, "已保存的文案没有英文版");
  const rootLayout = read("src/app/[locale]/layout.tsx");
  assert.match(rootLayout, /closeLabel=\{t\.toast\.close\}/, "Toaster 的关闭文案没有从 i18n 取");
  for (const [name, source] of [
    ["注册", signup],
    ["登录", login],
    ["删除账号", dangerZone],
    ["个人信息", profile],
  ]) {
    assert.doesNotMatch(source, /toast\(\{ title: "/, `${name}页把 toast 文案写死了`);
  }
});

test("⑦ 可访问性交给 Radix:不重复包 aria-live,不抢焦点,能手动关", () => {
  for (const [name, source] of [
    ["toast.tsx", toastComponent],
    ["toaster.tsx", toaster],
  ]) {
    assert.doesNotMatch(source, /aria-live=/, `${name} 自己又加了一层 aria-live,会和 Radix 重复播报`);
    assert.doesNotMatch(source, /autoFocus/, `${name} 让 toast 抢了焦点`);
  }
  assert.match(toaster, /<ToastClose aria-label=\{closeLabel\}/, "toast 没有可用的手动关闭按钮");
  assert.match(toastComponent, /ToastPrimitive\.Close/, "toast 没有用 Radix 的 Close");
  assert.match(toastComponent, /motion-reduce:animate-none/, "toast 的进出场没有 reduced-motion 回退");
});

test("⑧ 不自定义消失时长,用 Radix 的默认值", () => {
  for (const source of [toastComponent, toaster, hook]) {
    assert.doesNotMatch(source, /duration/, "toast 自己改了消失时长");
  }
});
