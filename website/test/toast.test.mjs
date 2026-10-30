import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

//: shadcn/ui 现在推荐 Sonner(旧 Radix Toast 已标 deprecated)。
//: 这里盯的是:Sonner 真的装了、根布局只挂一处、成功提示都走 `toast.success`、
//: 错误仍在字段旁(管理台动作错误走 `toast.error`)、旧的三件套与 FormNotice 清干净。
const ROOT = path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "src");

const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const exists = (relative) => fs.existsSync(path.join(ROOT, relative));

const walk = (dir) =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });

const sourceFiles = walk(SRC).filter((file) => /\.(ts|tsx)$/.test(file));
const layoutFiles = sourceFiles.filter((file) => file.endsWith("layout.tsx"));
const pkg = JSON.parse(read("package.json"));
const sonner = read("src/components/ui/sonner.tsx");
const rootLayout = read("src/app/[locale]/layout.tsx");
const controls = read("src/components/account/form-controls.tsx");
const signup = read("src/components/account/signup-form.tsx");
const login = read("src/components/account/login-form.tsx");
const dangerZone = read("src/components/account/account-danger-zone.tsx");
const profile = read("src/components/account/dashboard-profile.tsx");
const oauth = read("src/components/account/oauth-outcome.tsx");
const admin = read("src/components/admin/admin-console.tsx");

test("① shadcn 推荐的 Sonner 已安装,旧 Radix Toast 三件套已删除", () => {
  assert.ok(pkg.dependencies.sonner, "package.json 里没有 sonner");
  assert.ok(exists("src/components/ui/sonner.tsx"), "缺少 src/components/ui/sonner.tsx");
  for (const old of ["src/components/ui/toast.tsx", "src/components/ui/toaster.tsx", "src/components/ui/use-toast.ts"]) {
    assert.equal(exists(old), false, `${old} 还在,旧的 Radix toast 没清干净`);
  }
  assert.match(sonner, /from "sonner"/, "sonner 包装没有取 Sonner 的 Toaster");
  assert.match(sonner, /useTheme/, "sonner 没有接站点主题");
  assert.match(sonner, /Toaster as Sonner/, "没有用 shadcn 的 Toaster 包装写法");
  assert.match(sonner, /closeButtonAriaLabel/, "关闭按钮没有从调用方拿文案");
  assert.match(sonner, /containerAriaLabel/, "读屏区域名没有从调用方拿文案");
  assert.doesNotMatch(sonner, /duration:/, "不要在包装里自己改 toast 时长");
});

test("② 全站只挂一处 Sonner,挂在盖住两组页面的根布局里", () => {
  const mounted = layoutFiles.filter((file) => /<Toaster/.test(fs.readFileSync(file, "utf8")));
  assert.equal(
    mounted.length,
    1,
    `Toaster 必须只挂一处,现在挂在:${mounted.map((file) => path.relative(ROOT, file)).join(", ") || "无"}`,
  );
  assert.equal(mounted[0], path.join(SRC, "app", "[locale]", "layout.tsx"), "Toaster 应挂在 [locale] 根布局");
  assert.match(rootLayout, /import \{ Toaster \} from "@\/components\/ui\/sonner"/, "根布局没有引入 Sonner 包装");
  assert.match(rootLayout, /<Toaster label=\{t\.toast\.label\} closeLabel=\{t\.toast\.close\} \/>/, "根布局没有传入读屏与关闭文案");
});

test("③ 成功提示都走 Sonner 的 toast.success", () => {
  for (const [name, source, call] of [
    ["注册", signup, /toast\.success\(copy\.codeSent\)/],
    ["登录", login, /toast\.success\(copy\.(registered|loginCodeSent|smsCodeSent)\)/],
    ["个人信息", profile, /toast\.success\(copy\.saved\)/],
    ["OAuth", oauth, /toast\.success\(/],
  ]) {
    assert.match(source, /import \{ toast \} from "sonner"/, `${name}没有从 sonner 引入 toast`);
    assert.match(source, call, `${name}没有用 toast.success`);
  }
  for (const file of sourceFiles) {
    const source = fs.readFileSync(file, "utf8");
    assert.doesNotMatch(source, /toast\(\{ title:/, `${path.relative(ROOT, file)} 还在用旧 toast({ title }) API`);
  }
});

test("④ 字段错误仍留在 FormAlert;管理动作错误走 toast.error", () => {
  for (const [name, source] of [
    ["注册", signup],
    ["登录", login],
    ["删除账号", dangerZone],
    ["个人信息", profile],
  ]) {
    assert.match(source, /<FormAlert id=/, `${name}页丢了内联的错误提示`);
  }
  assert.match(controls, /export function FormAlert/, "FormAlert 不该被删");
  assert.match(admin, /toast\.error\(failureText/, "管理动作失败没有走 toast.error");
  assert.match(admin, /toast\.error\(copy\.testFailed/, "连接测试失败没有走 toast.error");
  assert.match(admin, /toast\.success\(copy\.testOk/, "连接测试成功没有走 toast.success");
});

test("⑤ FormNotice 已删除,全仓没有任何引用", () => {
  const offenders = sourceFiles
    .filter((file) => fs.readFileSync(file, "utf8").includes("FormNotice"))
    .map((file) => path.relative(ROOT, file));
  assert.deepEqual(offenders, [], `仍在引用 FormNotice:${offenders.join(", ")}`);
  assert.doesNotMatch(controls, /export function FormNotice/, "form-controls 里还留着 FormNotice");
});

test("⑥ toast 文案仍来自 messages.ts,而不是写死在页面里", () => {
  assert.match(rootLayout, /label=\{t\.toast\.label\}/, "Sonner 的读屏区域名没有从 i18n 取");
  assert.match(rootLayout, /closeLabel=\{t\.toast\.close\}/, "Sonner 的关闭文案没有从 i18n 取");
  for (const [name, source] of [
    ["注册", signup],
    ["登录", login],
    ["个人信息", profile],
    ["OAuth", oauth],
    ["管理台", admin],
  ]) {
    assert.doesNotMatch(source, /toast\.(success|error)\("|toast\.(success|error)\(\x27/, `${name}把 toast 文案写死了`);
  }
});

test("⑦ Sonner 自己处理可访问性;包装不抢焦点、不重复 aria-live", () => {
  assert.doesNotMatch(sonner, /autoFocus/, "Sonner 包装让 toast 抢了焦点");
  assert.doesNotMatch(sonner, /aria-live=/, "Sonner 包装自己又加了一层 aria-live");
  assert.match(sonner, /closeButton/, "没有打开关闭按钮");
  assert.match(sonner, /richColors/, "错误 toast 应该用 Sonner 的颜色区分");
});
