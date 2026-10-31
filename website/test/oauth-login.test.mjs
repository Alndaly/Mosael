import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 第三方登录的界面契约:登录页 / 注册页各两颗(仅在已配置时出现)、沿用现有控件与图标、
//: 分隔线在按钮之上、键盘可达、loading 与失败态都有;中英同键。
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
const { enabledOAuthProviders, oauthStartUrl, oauthErrorCopyKey } = await import(
  "../src/lib/oauth.ts"
);

const read = (relative) => fs.readFileSync(path.resolve(import.meta.dirname, "..", relative), "utf8");
const maybeRead = (relative) => {
  const file = path.resolve(import.meta.dirname, "..", relative);
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
};

const buttons = maybeRead("src/components/account/oauth-buttons.tsx");
const login = read("src/components/account/login-form.tsx");
const signup = read("src/components/account/signup-form.tsx");
const accountPage = read("src/app/[locale]/(auth)/account/page.tsx");
const dashboardPage = read("src/app/[locale]/(dashboard)/dashboard/page.tsx");
const outcomeToast = maybeRead("src/components/account/oauth-outcome.tsx");
const icons = read("src/components/icons.tsx");
const client = read("src/lib/cloud.ts");

test("未配置的 provider 不渲染:两个 false → 空数组,malformed 也算没配置", () => {
  assert.deepEqual(enabledOAuthProviders({ providers: { github: false, google: false } }), []);
  assert.deepEqual(enabledOAuthProviders({ providers: { github: true, google: true } }), [
    "github",
    "google",
  ]);
  assert.deepEqual(enabledOAuthProviders({ providers: { github: true, google: false } }), ["github"]);
  assert.deepEqual(enabledOAuthProviders({ providers: { github: "yes", google: null } }), []);
  assert.deepEqual(enabledOAuthProviders(null), []);
  assert.deepEqual(enabledOAuthProviders({}), []);
  // 组件本身:没拿到 / 拿到空列表时整块不画,连分隔线都不占位。
  assert.match(buttons, /providers\.length === 0/, "空列表没有整块隐藏");
  assert.match(buttons, /return null/, "未配置时没有 return null");
});

test("启动地址是同源 GET,带着语言和来源页", () => {
  assert.equal(
    oauthStartUrl("github", "zh", "signup"),
    "/api/cloud/v1/oauth/github/start?locale=zh&from=signup",
  );
  assert.equal(
    oauthStartUrl("google", "en", "login"),
    "/api/cloud/v1/oauth/google/start?locale=en&from=login",
  );
  assert.match(client, /"\/oauth\/providers"/, "浏览器客户端没有读取 provider 配置");
});

test("登录页和注册页各有一组第三方按钮,并复用现有图标与按钮", () => {
  for (const [name, form, from] of [
    ["登录", login, "login"],
    ["注册", signup, "signup"],
  ]) {
    assert.match(form, /<OAuthButtons/, `${name}页没有第三方登录按钮`);
    assert.match(form, new RegExp(`from="${from}"`), `${name}页没有把来源页传给 Cloud`);
    assert.match(form, /oauthError/, `${name}页没有接收第三方失败原因`);
    assert.match(form, /FormAlert/, `${name}页没有显示失败态的位置`);
  }

  assert.match(buttons, /GithubMark/, "GitHub 按钮没有沿用站里的品牌图标");
  assert.match(buttons, /GoogleMark/, "Google 按钮没有沿用站里的品牌图标");
  assert.match(buttons, /from "@\/components\/ui\/button"/, "按钮没有复用站里的 Button");
  assert.match(icons, /export function GoogleMark/, "icons.tsx 里没有 Google 图标");
  assert.doesNotMatch(buttons, /from "react-icons|from "@?icons\/|lucide-react.*Github/, "引了新图标依赖");
});

test("分隔线在按钮之上,按钮键盘可达且有 loading / busy 态", () => {
  assert.match(buttons, /h-px flex-1 bg-border/, "没有分隔线");
  assert.match(buttons, /copy\.oauthOr/, "分隔线上没有「或」");
  assert.ok(
    buttons.indexOf("copy.oauthOr") < buttons.indexOf("providers.map"),
    "分隔线没有排在按钮之前",
  );
  assert.match(buttons, /<a href=\{oauthStartUrl\(/, "按钮不是原生链接,键盘 / 新窗口不可用");
  assert.match(buttons, /aria-busy=\{busy\}/, "按钮没有 busy 态");
  assert.match(buttons, /LoaderCircle/, "按钮没有 loading 图标");
  assert.match(buttons, /motion-reduce:animate-none/, "loading 动画没有尊重减少动效");
  assert.match(buttons, /focus-visible:/, "按钮没有键盘聚焦样式");
});

test("失败原因按稳定错误码翻成当前语言,未知码落到通用文案", () => {
  assert.equal(oauthErrorCopyKey("oauth_email_unverified"), "oauthErrorEmailUnverified");
  assert.equal(oauthErrorCopyKey("oauth_state_invalid"), "oauthErrorStateInvalid");
  assert.equal(oauthErrorCopyKey("oauth_not_configured"), "oauthErrorNotEnabled");
  assert.equal(oauthErrorCopyKey("oauth_identity_conflict"), "oauthErrorConflict");
  assert.equal(oauthErrorCopyKey("something_new"), "oauthErrorGeneric");
  assert.equal(
    oauthErrorCopyKey("oauth_code_rejected"),
    "oauthErrorCodeRejected",
    "PKCE / 授权码失败没有自己的文案",
  );

  for (const locale of ["en", "zh"]) {
    const accountCopy = getMessages(locale).account;
    for (const key of [
      "oauthOr",
      "oauthGithub",
      "oauthGoogle",
      "oauthRedirecting",
      "oauthErrorNotEnabled",
      "oauthErrorStateInvalid",
      "oauthErrorCallbackInvalid",
      "oauthErrorDenied",
      "oauthErrorCodeRejected",
      "oauthErrorEmailUnverified",
      "oauthErrorConflict",
      "oauthErrorProvider",
      "oauthErrorGeneric",
      "oauthExisting",
      "oauthCreated",
    ]) {
      assert.ok(accountCopy[key], `${locale} 缺 account.${key}`);
    }
  }
  const zh = getMessages("zh").account;
  const en = getMessages("en").account;
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort(), "中英 account 文案键不一致");
  assert.match(zh.oauthErrorEmailUnverified, /已验证/, "中文没有说清「邮箱未验证」");
  assert.match(en.oauthErrorEmailUnverified, /verified/i, "英文没有说清「邮箱未验证」");
  assert.match(zh.oauthErrorCodeRejected, /PKCE/, "中文没有说清 PKCE 校验失败");
});

test("登录后的结果在控制台说清:新建 / 绑定到已有账号", () => {
  // 云端的回调仍回到 /account?oauth=…(cloud 不在这笔改动里),而 /account 只剩永久跳转:
  // 结果码必须被透传,否则「已创建 / 已绑定」那句提示会在 308 里丢掉。
  assert.match(accountPage, /permanentRedirect\(/, "/account 不是永久跳转");
  assert.match(accountPage, /oauth/, "/account 跳转没有透传第三方登录结果");
  assert.match(dashboardPage, /OAuthOutcomeToast/, "控制台没有接上第三方登录结果");
  assert.match(dashboardPage, /parseOAuthOutcome\(/, "控制台没有归一化结果码");
  assert.match(outcomeToast, /copy\.oauthCreated/, "没有「已创建账号」的提示");
  assert.match(outcomeToast, /copy\.oauthExisting/, "没有「已绑定到已有账号」的提示");
  const loginPage = read("src/app/[locale]/(auth)/login/page.tsx");
  const signupPage = read("src/app/[locale]/(auth)/signup/page.tsx");
  assert.match(loginPage, /oauth_error/, "登录页没有读回失败错误码");
  assert.match(signupPage, /oauth_error/, "注册页没有读回失败错误码");
});
