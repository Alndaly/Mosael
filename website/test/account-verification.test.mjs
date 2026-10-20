import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 邮箱验证码的界面契约:注册必须带码且有重发倒计时;登录页同一套分段控件里有两个入口;
//: 错误通过 aria-describedby 关联;中英文案同键。
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

const { getMessages } = await import("../src/i18n/messages.ts");
const read = (relative) => fs.readFileSync(path.resolve(import.meta.dirname, "..", relative), "utf8");
const maybeRead = (relative) => {
  const file = path.resolve(import.meta.dirname, "..", relative);
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
};

const controls = read("src/components/account/form-controls.tsx");
const signup = read("src/components/account/signup-form.tsx");
const login = read("src/components/account/login-form.tsx");
const countdown = maybeRead("src/components/account/use-email-code.ts");
const client = read("src/lib/cloud.ts");

test("注册表单:邮箱 → 发送验证码(含倒计时)→ 6 位码 → 密码,复用现有控件", () => {
  assert.match(signup, /sendSignupCode/, "注册表单没有发送注册验证码");
  assert.match(signup, /useResendCountdown/, "注册表单没有重发倒计时");
  assert.match(signup, /countdown\.start\(\)/, "发送成功后没有启动倒计时");
  assert.match(signup, /countdown\.remaining/, "倒计时剩余秒数没有显示");
  assert.match(signup, /CodeField/, "注册表单没有复用统一的验证码字段");
  assert.match(signup, /SendCodeButton/, "注册表单没有复用发送验证码按钮");
  assert.match(signup, /PasswordField/, "注册表单丢了密码字段");
  assert.match(signup, /SubmitButton/, "注册表单丢了统一主按钮");
  // 码要真的交给注册接口,而不是只做前端装饰。
  assert.match(signup, /cloudAccount\.signup\(email[^,]*,\s*code/, "注册请求没有带验证码");
});

test("验证码控件:6 位数字、按码自动填充、发送中 / 冷却时禁用", () => {
  assert.match(controls, /export function CodeField/, "没有验证码字段控件");
  assert.match(controls, /inputMode="numeric"/, "验证码输入框不是数字键盘");
  assert.match(controls, /autoComplete="one-time-code"/, "验证码输入框没有声明一次性验证码语义");
  assert.match(controls, /maxLength=\{6\}/, "验证码输入框没有限制 6 位");
  assert.match(controls, /pattern="\[0-9\]\{6\}"/, "验证码输入框没有 6 位数字约束");
  assert.match(controls, /export function SendCodeButton/, "没有发送验证码按钮控件");
  assert.match(controls, /disabled=\{blocked\}/, "发送按钮在发送中 / 冷却时没有禁用");
  assert.match(controls, /resendLabel/, "发送按钮没有重发文案");
  assert.match(controls, /export function SegmentedControl/, "没有登录方式的分段控件");
  assert.match(controls, /aria-pressed=\{selected\}/, "分段控件没有 aria-pressed");
});

test("登录页:同一页两个入口(密码 / 验证码),不是两个页面", () => {
  assert.match(login, /SegmentedControl/, "登录页没有分段切换控件");
  assert.match(login, /loginModePassword/, "登录页缺少密码入口");
  assert.match(login, /loginModeCode/, "登录页缺少验证码入口");
  assert.match(login, /sendLoginCode/, "验证码入口没有发送登录码");
  assert.match(login, /loginWithCode/, "验证码入口没有用码登录");
  assert.match(login, /CodeField/, "验证码入口没有复用统一的验证码字段");
  assert.match(login, /SendCodeButton/, "验证码入口没有复用发送按钮");
  assert.match(login, /PasswordField/, "密码入口丢了密码字段");
  assert.match(login, /CloudApiError/, "登录页没有把云端错误翻成当前语言");
});

test("倒计时是共享逻辑,且和弹层 / 动画一样尊重减少动效偏好", () => {
  assert.match(countdown, /RESEND_COOLDOWN_SECONDS/, "倒计时没有写死与服务端一致的冷却秒数");
  assert.match(countdown, /setTimeout/, "倒计时没有按秒推进");
  assert.match(countdown, /remaining/, "倒计时没有返回剩余秒数");
  assert.match(controls, /motion-reduce:transition-none/, "分段控件 / 按钮没有 reduced-motion 回退");
  assert.match(controls, /motion-reduce:animate-none/, "发送中的 spinner 没有 reduced-motion 回退");
});

test("错误和提示通过 aria-describedby 关联", () => {
  assert.match(signup, /const codeDescription =/, "注册表单没有把验证码提示 / 错误 id 组装起来");
  assert.match(signup, /describedBy=\{codeDescription\}/, "注册表单的验证码字段没有关联提示 / 错误");
  assert.match(login, /const codeDescription =/, "登录表单没有把验证码提示 / 错误 id 组装起来");
  assert.match(login, /describedBy=\{codeDescription\}/, "登录表单的验证码字段没有关联提示 / 错误");
  assert.match(signup, /<FormNotice id=/, "注册成功提示没有 id,无法关联到字段");
});

test("浏览器客户端只新增同源的验证码端点,签名带上 code", () => {
  assert.match(client, /sendSignupCode/, "客户端没有 sendSignupCode");
  assert.match(client, /sendLoginCode/, "客户端没有 sendLoginCode");
  assert.match(client, /loginWithCode/, "客户端没有 loginWithCode");
  assert.match(client, /"\/signup\/code"/, "客户端没有请求 /signup/code");
  assert.match(client, /"\/login\/code"/, "客户端没有请求 /login/code");
  assert.match(client, /"\/login\/code\/verify"/, "客户端没有请求 /login/code/verify");
  assert.match(client, /JSON\.stringify\(\{\s*email,\s*code,\s*password\s*\}\)/, "注册请求没有把 code 发给后端");
});

test("登录码的提示不泄露邮箱是否注册,中英同键", () => {
  const zh = getMessages("zh").account;
  const en = getMessages("en").account;
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort(), "中英 account 文案键不一致");

  for (const key of [
    "codeLabel",
    "codeHint",
    "codeRequired",
    "sendCode",
    "sendingCode",
    "resendCode",
    "codeSent",
    "loginCodeSent",
    "emailRequired",
    "loginModeLabel",
    "loginModePassword",
    "loginModeCode",
    "loginWithCode",
    "verifying",
    "emailVerified",
  ]) {
    assert.ok(zh[key], `中文缺 account.${key}`);
    assert.ok(en[key], `英文缺 account.${key}`);
  }

  // 枚举防护的界面文案:两封邮件走同一句"如果注册过"。
  assert.match(zh.loginCodeSent, /注册过/, "中文登录码提示没有写成「如果注册过」");
  assert.match(en.loginCodeSent, /registered/i, "英文登录码提示没有写成「if registered」");
  assert.doesNotMatch(zh.loginCodeSent, /未注册|没有注册|不存在/, "中文登录码提示泄露了邮箱是否存在");
  assert.notEqual(zh.loginModePassword, zh.loginModeCode, "两个登录入口用了同一个词");
});

