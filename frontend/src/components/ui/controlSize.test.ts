/**
 * 棘轮:**按钮、输入框、下拉触发器的高度只有一个出处**(control-size.ts)。
 *
 * 一行里、一张表单里并排的控件理应同高。此前三个文件各写一个 `h-10`,今天相等只是巧合 ——
 * 而 SearchableSelect 手抄过一份 `h-8`,在同一行里比旁边矮了 8px。这里拦下再手写。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { CONTROL_HEIGHT } from "@/components/ui/control-size";
import { FIELD_TRIGGER_CLASS } from "@/components/ui/field-trigger";

export const RATCHET = true;

const FILES = ["button.tsx", "input.tsx", "field-trigger.ts"];

describe("控件高度只有一个出处", () => {
  it.each(FILES)("%s 不手写高度", (file) => {
    //: 注释里提到旧写法不算 —— 只看代码行。
    const source = readFileSync(join(__dirname, file), "utf8")
      .split("\n")
      .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
      .join("\n");
    expect(source.match(/(?<![\w-])(h|size)-(7|8|9|10|11)(?![\w-])/g) ?? []).toEqual([]);
  });

  it("输入框、下拉触发器、默认按钮同高", async () => {
    const { buttonVariants } = await import("@/components/ui/button");
    expect(buttonVariants()).toContain(CONTROL_HEIGHT.md);
    expect(FIELD_TRIGGER_CLASS).toContain(CONTROL_HEIGHT.md);
    expect(readFileSync(join(__dirname, "input.tsx"), "utf8")).toContain("CONTROL_HEIGHT.md");
  });

  it("描边按钮和输入框是同一种描边 —— 并排时外轮廓一样清楚", async () => {
    const { buttonVariants } = await import("@/components/ui/button");
    expect(buttonVariants({ variant: "outline" })).toContain("border-field-border");
    expect(FIELD_TRIGGER_CLASS).toContain("border-field-border");
  });
});
