import { describe, expect, it } from "vitest";

import { readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { messages } from "./messages";

/**
 * 界面文案里不要写 markdown。
 *
 * 这些串全都被塞进 `<p>{description}</p>`、`<AlertDialogDescription>{body}</AlertDialogDescription>`
 * 这类**纯文本**位置 —— 没有任何 markdown 渲染器。写 `**重点**` 的结果是用户看到一串星号。
 *
 * 用户是在一条转写报错里发现这件事的(截图里赫然是 `缺的是**运行环境**`),而全项目当时有六处
 * 同样的写法。要强调就用中文的方式(「」引号、破折号、换个词序),它们在纯文本里就是能用的。
 */
const APP = resolve(__dirname);
const TABLE_DIR = join(APP, "messages");
const LOCALES = ["zh-CN", "en-US"] as const;

/** 文案表的全部源文件:入口 messages.ts 加 messages/<语言>/*.ts。 */
function tableFiles(): string[] {
  const areas = LOCALES.flatMap((locale) =>
    readdirSync(join(TABLE_DIR, locale))
      .filter((name) => name.endsWith(".ts"))
      .map((name) => join(TABLE_DIR, locale, name)),
  );
  return [join(APP, "messages.ts"), ...areas];
}

/** 某个语言下的分区文件名(不含 index.ts)。 */
function areaNames(locale: (typeof LOCALES)[number]): string[] {
  return readdirSync(join(TABLE_DIR, locale))
    .filter((name) => name.endsWith(".ts") && name !== "index.ts")
    .map((name) => name.replace(/\.ts$/, ""))
    .sort();
}

describe("界面文案", () => {
  it("不含未渲染的 markdown 强调", () => {
    const offenders = tableFiles().flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .map((line, index) => [index + 1, line] as const)
        .filter(([, line]) => /".*\*\*.*"/.test(line))
        .map(([index, line]) => `${relative(APP, file)}:${index}: ${line.trim().slice(0, 90)}`),
    );

    expect(offenders).toEqual([]);
  });

  //: 沙盒实测:AI 工作台「调参」里那一格写着「Seed」—— 中文界面里留了一个没翻的英文词(工作流节点里的大模型参数
  //: 「Seed」「Temperature」、对话里的「Steer」同样)。中文表里和英文一模一样、又是一个英文词的,只能是专名和术语。
  it("中文表里没有留着没翻的英文词(专名、术语除外)", () => {
    const zh = messages["zh-CN"] as Record<string, string>;
    const en = messages["en-US"] as Record<string, string>;
    const untranslated = Object.keys(zh)
      .filter((key) => zh[key] === en[key] && /^[A-Za-z][a-z]+( [a-z]+)*$/.test(zh[key]))
      .sort();
    expect(untranslated).toEqual([
      "homeChartPlatformWebhook", // Webhook:术语
      "languageEn", // 语言名「English」就写它自己
      "modelDownloadSourceCivitai", // 站名
      "revision", // 没找到读它的地方,不是界面上看得到的字
      "trigger_webhook", // Webhook:术语
    ]);
  });

  it("扫得到文案表 —— 别变成空转", () => {
    expect(areaNames("zh-CN").length).toBeGreaterThan(5);
  });
});

describe("文案表分区", () => {
  it("中英两边的分区文件一一对应", () => {
    expect(areaNames("en-US")).toEqual(areaNames("zh-CN"));
  });

  it("每对分区的键集完全相同,且拼起来就是整张表", async () => {
    const sizes: Record<string, number> = { "zh-CN": 0, "en-US": 0 };
    for (const area of areaNames("zh-CN")) {
      const [zh, en] = await Promise.all(
        LOCALES.map(async (locale) => {
          const mod = (await import(`./messages/${locale}/${area}.ts`)) as Record<string, Record<string, string>>;
          const tables = Object.values(mod);
          expect(tables, `${locale}/${area}.ts 应只导出一张表`).toHaveLength(1);
          const keys = Object.keys(tables[0]);
          sizes[locale] += keys.length;
          const missing = keys.filter((key) => !Object.hasOwn(messages[locale], key));
          expect(missing, `${locale}/${area}.ts 里这些键没拼进入口`).toEqual([]);
          return keys;
        }),
      );
      expect([...en].sort(), `en-US/${area}.ts 与 zh-CN/${area}.ts 的键不一致`).toEqual([...zh].sort());
    }
    // 分区之间不重复、也没有漏拼的分区
    for (const locale of LOCALES) expect(sizes[locale]).toBe(Object.keys(messages[locale]).length);
  });
});

/**
 * 中英两边同一条文案的占位符(`{n}`、`{name}`……)要对得上。
 *
 * 文案一律是 `t(key).replace("{n}", …)` 这样填的:英文那条把 `{count}` 写成了 `{n}`,替换落空,界面上就露出一个
 * 原样的 `{count}`;少写一个,那个数就悄悄没了。没有任何编译期检查会说话。
 */
const PLACEHOLDER_DIFFERS: Record<string, string> = {
  //: 中文说「常配 X 等 N 种」(总数),英文说「and N more」(其余几种);ModelEncoder 把 {n} 和 {more} 都替换。
  modelEncoderPairsMore: "中英说法不同:中文给总数 {n},英文给其余几种 {more}",
};

describe("中英文案的占位符", () => {
  const placeholders = (text: string) => [...new Set([...text.matchAll(/\{(\w+)\}/g)].map((one) => one[1]))].sort();

  it("同一条文案两边的占位符一致", () => {
    const zh = messages["zh-CN"];
    const en = messages["en-US"];
    const differ = (Object.keys(zh) as (keyof typeof zh)[])
      .filter((key) => !(key in PLACEHOLDER_DIFFERS))
      .filter((key) => placeholders(zh[key]).join() !== placeholders(en[key]).join())
      .map((key) => `${key}: 中 {${placeholders(zh[key]).join(",")}} / 英 {${placeholders(en[key]).join(",")}}`);
    expect(differ, "两边的占位符要一致,不然替换落空、界面上露出 {x}").toEqual([]);
  });

  it("例外清单里的条目确实两边不同 —— 改一致了就删掉", () => {
    for (const key of Object.keys(PLACEHOLDER_DIFFERS) as (keyof (typeof messages)["zh-CN"])[]) {
      expect(placeholders(messages["zh-CN"][key]).join(), key).not.toBe(placeholders(messages["en-US"][key]).join());
    }
  });
});
