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

test("三页都在,而且每一页都经 pageMetadata 出 head(未登录页不进搜索索引由页面自己声明)", () => {
  for (const page of ["signup", "login", "account"]) {
    const file = path.join(SRC, "app", "[locale]", page, "page.tsx");
    assert.ok(fs.existsSync(file), `缺少 ${page} 页`);
    const source = fs.readFileSync(file, "utf8");
    assert.match(source, /export async function generateMetadata/, `${page} 没有 generateMetadata`);
    assert.match(source, /pageMetadata\(/, `${page} 没有走 pageMetadata`);
    assert.match(source, /index:\s*false/, `${page} 是私有页,应当 noindex`);
  }
});

test("浏览器只打同源 /api/cloud/v1,不出现 localStorage 令牌", () => {
  const client = read("src/lib/cloud.ts");
  assert.match(client, /CLOUD_API\s*=\s*"\/api\/cloud\/v1"/);
  assert.match(client, /credentials:\s*"same-origin"/);
  for (const relative of ["src/lib/cloud.ts", "src/components/account/signup-form.tsx", "src/components/account/login-form.tsx", "src/components/account/account-view.tsx", "src/components/account/account-nav.tsx"]) {
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

test("中英文案齐全:登录、退出、删号、设备确认各有一份", () => {
  for (const locale of LOCALES) {
    const account = getMessages(locale).account;
    for (const key of [
      "login",
      "signup",
      "account",
      "email",
      "password",
      "signIn",
      "signUp",
      "signOut",
      "deleteAccount",
      "devices",
      "approve",
      "approved",
      "registered",
    ]) {
      assert.ok(account[key], `${locale} 缺 account.${key}`);
    }
    assert.ok(account.signIn !== account.signUp, `${locale} 的登录和注册是同一个词`);
  }
});
