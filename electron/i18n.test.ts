/**
 * 桌面壳文案表(electron/i18n.cjs)的两条硬约束:
 *
 * 1. 每个 key 两种语言都有,而且占位符一致 —— 缺一半,英文界面里就冒出中文(或者 key 本身);
 *    占位符对不上,一种语言里就漏了那个值。
 * 2. 代码里用到的 key 都在表里,表里的 key 都有人用 —— t() 查不到时原样返回 key,不报错,
 *    所以写错一个字母只会在界面上变成一串 `publishErr_xxx`,而没人会注意到。
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

import { afterEach, describe, expect, it } from "vitest";

const i18n = createRequire(import.meta.url)("./i18n.cjs") as typeof import("./i18n.cjs");

const ROOT = path.resolve(__dirname);
const PREFIXES = Object.keys(i18n.MESSAGES).map((key) => key.split("_")[0]);
const KEY_LITERAL = new RegExp(`["'\`]((?:${[...new Set(PREFIXES)].join("|")})_[A-Za-z]+)["'\`]`, "g");

function* sources(dir: string): Generator<string> {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) {
      if (name !== "node_modules") yield* sources(full);
    } else if (/\.(ts|cjs)$/.test(name) && !/\.test\.|\.d\.c?ts$|\.bundle\.cjs$|^i18n\.cjs$/.test(name)) {
      yield full;
    }
  }
}

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

afterEach(() => {
  i18n.setLocale(i18n.DEFAULT_LOCALE);
});

describe("桌面壳文案表", () => {
  it("每个 key 中英都有,占位符一致", () => {
    for (const [key, entry] of Object.entries(i18n.MESSAGES)) {
      for (const locale of i18n.LOCALES) {
        expect(entry[locale]?.trim(), `${key}.${locale}`).toBeTruthy();
      }
      expect(placeholders(entry.en), key).toEqual(placeholders(entry.zh));
    }
  });

  it("代码里用到的 key 都在表里,表里的 key 都有人用", () => {
    const used = new Set<string>();
    for (const file of sources(ROOT)) {
      for (const match of fs.readFileSync(file, "utf8").matchAll(KEY_LITERAL)) used.add(match[1]);
    }
    const known = new Set(Object.keys(i18n.MESSAGES));
    expect([...used].filter((key) => !known.has(key)), "代码里用了表里没有的 key").toEqual([]);
    expect([...known].filter((key) => !used.has(key)), "表里有、代码里没人用的 key").toEqual([]);
  });

  it("语言标签归一成 zh / en,认不出的回落到缺省", () => {
    expect(i18n.normalizeLocale("en-US")).toBe("en");
    expect(i18n.normalizeLocale("en_GB")).toBe("en");
    expect(i18n.normalizeLocale("zh-CN")).toBe("zh");
    expect(i18n.normalizeLocale("zh-Hant-TW")).toBe("zh");
    expect(i18n.normalizeLocale("ja")).toBe(i18n.DEFAULT_LOCALE);
    expect(i18n.normalizeLocale("")).toBe(i18n.DEFAULT_LOCALE);
    expect(i18n.normalizeLocale(undefined)).toBe(i18n.DEFAULT_LOCALE);
  });

  it("按当前语言出字,并填上参数", () => {
    i18n.setLocale("en-US");
    expect(i18n.t("tray_running", { count: 3 })).toBe("3 running");
    expect(i18n.t("publishErr_rejected", { platform: "Bilibili", reason: "标题重复" })).toBe(
      "Bilibili rejected the post: 标题重复",
    );
    i18n.setLocale("zh-CN");
    expect(i18n.t("tray_running", { count: 3 })).toBe("3 个任务运行中");
    expect(i18n.getLocale()).toBe("zh");
  });

  it("填不上的占位符原样留着(那是参数名写错了,留着才查得出来),不认识的 key 原样返回", () => {
    i18n.setLocale("en");
    expect(i18n.t("menu_aboutVersion", { wrong: 1 })).toBe("Version {version}");
    expect(i18n.t("no_suchKey")).toBe("no_suchKey");
  });
});
