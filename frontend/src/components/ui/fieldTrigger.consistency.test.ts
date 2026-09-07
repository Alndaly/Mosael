/**
 * 结构性约束:**三种下拉共用同一份触发器样式。**
 *
 * Select / Combobox / SearchableSelect 在界面上是同一类控件,用户并排看到时理应一模一样 ——
 * 见 field-trigger.ts 的说明。
 *
 * **这条测试是补写的,因为它真的破过。** SearchableSelect 手抄了一份类名,抄出来的是
 * `h-8 / gap-1 / px-2.5`,而 token 是 `h-10 / gap-1.5 / px-3`。插件的「新建连接」正好把
 * 下拉、输入框、按钮排在同一行 —— 两个下拉比旁边矮 8px。而 field-trigger.ts 的注释里点名
 * 提到了 SearchableSelect,它偏偏是唯一没用那个 token 的。措辞守不住不变量。
 *
 * 钉的是**没人再手抄**:这三个文件里不得出现自带高度的触发器类串。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const UI = __dirname;
const FILES = {
  "ui/select.tsx": join(UI, "select.tsx"),
  "ui/searchable-select.tsx": join(UI, "searchable-select.tsx"),
  "app/combobox.tsx": join(UI, "..", "app", "combobox.tsx"),
};

describe("下拉触发器只有一份样式", () => {
  it.each(Object.entries(FILES))("%s 用 FIELD_TRIGGER_CLASS", (_name, path) => {
    expect(readFileSync(path, "utf8")).toContain("FIELD_TRIGGER_CLASS");
  });

  it.each(Object.entries(FILES))("%s 不自带触发器高度", (_name, path) => {
    // 触发器那一串的标志是「flex + 边框 + bg-field」同时出现;它一旦自带 h-*,
    // 就是又抄了一份。调用点仍然可以用 className 覆盖(见 AiStudio 的 ComfyUI 参数列表),
    // 那是 cn() 之后的事,不在这几个文件里。
    const source = readFileSync(path, "utf8");
    const handwritten = source
      .split("\n")
      .filter((line) => /\bh-\d/.test(line) && /bg-field/.test(line));
    expect(handwritten, "触发器样式只该来自 FIELD_TRIGGER_CLASS").toEqual([]);
  });

  it.each(Object.entries(FILES))("%s 的触发器箭头用 FIELD_TRIGGER_CHEVRON", (_name, path) => {
    const source = readFileSync(path, "utf8");
    // **只看触发器里那一枚。** select.tsx 还有一个 ScrollDownButton 的箭头(列表滚到底时的
    // 指示),它和触发器不是同一个东西,尺寸也不该跟着走 —— 判据得说清是哪一枚,
    // 否则这条测试会逼人把无关的图标也塞进同一个 token。
    const start = source.indexOf("FIELD_TRIGGER_CLASS,");
    if (start < 0) return;
    const trigger = source.slice(start, source.indexOf("</", start) + 2);
    const adhoc = trigger
      .split("\n")
      .filter((line) => line.includes("<ChevronDown") && !line.includes("FIELD_TRIGGER_CHEVRON"));
    expect(adhoc, "箭头和触发器是同一个视觉单元,别单独写").toEqual([]);
  });
});
