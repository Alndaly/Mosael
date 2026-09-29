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
