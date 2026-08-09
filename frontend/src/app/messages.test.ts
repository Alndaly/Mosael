import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * 界面文案里不要写 markdown。
 *
 * 这些串全都被塞进 `<p>{description}</p>`、`<AlertDialogDescription>{body}</AlertDialogDescription>`
 * 这类**纯文本**位置 —— 没有任何 markdown 渲染器。写 `**重点**` 的结果是用户看到一串星号。
 *
 * 用户是在一条转写报错里发现这件事的(截图里赫然是 `缺的是**运行环境**`),而全项目当时有六处
 * 同样的写法。要强调就用中文的方式(「」引号、破折号、换个词序),它们在纯文本里就是能用的。
 */
const SOURCE = readFileSync(resolve(__dirname, "./messages.ts"), "utf8");

describe("界面文案", () => {
  it("不含未渲染的 markdown 强调", () => {
    const offenders = SOURCE.split("\n")
      .map((line, index) => [index + 1, line] as const)
      .filter(([, line]) => /".*\*\*.*"/.test(line))
      .map(([index, line]) => `${index}: ${line.trim().slice(0, 90)}`);

    expect(offenders).toEqual([]);
  });
});
