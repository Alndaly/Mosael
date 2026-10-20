import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: MosaelCloud 官网入口的契约:三页(注册 / 登录 / 账号)都存在且各自出 <head>;
//: 浏览器只请求同源的 /api/cloud/v1/*(cookie 才是第一方的);云端会话不落 localStorage。
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

test("登录 / 注册在 (auth) 分组里并各自出 head;/account 只剩永久跳转,不再有自己的 head", () => {
  for (const page of ["signup", "login"]) {
    const file = path.join(SRC, "app", "[locale]", "(auth)", page, "page.tsx");
    assert.ok(fs.existsSync(file), `缺少 ${page} 页`);
    const source = fs.readFileSync(file, "utf8");
    assert.match(source, /export async function generateMetadata/, `${page} 没有 generateMetadata`);
    assert.match(source, /pageMetadata\(/, `${page} 没有走 pageMetadata`);
    assert.match(source, /index:\s*false/, `${page} 是私有页,应当 noindex`);
  }

  // `/account` 并进控制台后没有可描述的内容:一个 308 就够了(控制台自己 noindex)。
  const account = path.join(SRC, "app", "[locale]", "(auth)", "account", "page.tsx");
  assert.ok(fs.existsSync(account), "缺少 account 页 —— 旧地址仍要能打开");
  const source = fs.readFileSync(account, "utf8");
  assert.match(source, /permanentRedirect\(/, "account 页不是永久跳转");
  assert.doesNotMatch(source, /generateMetadata/, "account 页只是跳转,不该再出 head");
});

test("浏览器只打同源 /api/cloud/v1,不出现 localStorage 令牌", () => {
  const client = read("src/lib/cloud.ts");
  assert.match(client, /CLOUD_API\s*=\s*"\/api\/cloud\/v1"/);
  assert.match(client, /credentials:\s*"same-origin"/);
  for (const relative of ["src/lib/cloud.ts", "src/components/account/signup-form.tsx", "src/components/account/login-form.tsx", "src/components/account/account-danger-zone.tsx", "src/components/account/account-nav.tsx"]) {
    const source = read(relative);
    assert.ok(!/localStorage\s*\./.test(source), `${relative} 把云端会话放进 localStorage 了`);
    assert.ok(!/document\.cookie/.test(source), `${relative} 自己读写了 cookie`);
  }
});

test("官网把 /api/cloud/v1/* 同源反代给 Cloud,不在浏览器里跨域", () => {
  const config = read("next.config.ts");
  assert.match(config, /\/api\/cloud\/v1\/:path\*/, "next.config 没有同源反代规则");
  assert.match(config, /CLOUD_API_URL/, "反代目标没有从部署环境读");
  assert.doesNotMatch(config, /Access-Control-Allow-Origin/);
});

test("中英文案齐全:登录在 account,退出 / 删号在控制台 dashboard", () => {
  for (const locale of LOCALES) {
    const messages = getMessages(locale);
    const account = messages.account;
    for (const key of ["login", "signup", "account", "email", "password", "signIn", "signUp", "registered"]) {
      assert.ok(account[key], `${locale} 缺 account.${key}`);
    }
    assert.ok(account.signIn !== account.signUp, `${locale} 的登录和注册是同一个词`);
    // 账号页并进控制台之后,退出与删号这两句话跟着搬到了 dashboard 文案里。
    for (const key of ["signOut", "signingOut", "deleteAccount", "deleteConfirm", "dangerZone"]) {
      assert.ok(messages.dashboard[key], `${locale} 缺 dashboard.${key}`);
    }
  }
});
