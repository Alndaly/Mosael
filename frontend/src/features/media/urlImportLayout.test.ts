/**
 * 弹层的横向必须锁死。
 *
 * 一条没有空格的 CJK 长标题(视频标题几乎都是这样)会把整个弹层撑开:flex / grid 的子项默认
 * `min-width: auto`,也就是"至少和内容一样宽"。截图里就是内容整片溢出到弹层之外。
 *
 * 这个仓库修过同一个形状(见工具浏览器弹窗的注释),所以这里盯的是**每一层都锁住**:
 * 容器 `min-w-0`、可变的那一栏 `min-w-0 flex-1`、固定的那一栏 `shrink-0`、长文本 `truncate`。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(join(import.meta.dirname, "UrlImportDialog.tsx"), "utf8");

/** 去掉注释 —— 免得棘轮被"注释里提到 min-w-0"喂饱(这个仓库出过空棘轮)。 */
const code = SOURCE.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("从链接导入弹层的横向约束", () => {
  it("输入框那一行:输入框可缩、按钮不可缩", () => {
    expect(code).toMatch(/className="flex min-w-0 items-center/);
    expect(code).toMatch(/className="min-w-0 flex-1"[\s\S]{0,200}placeholder=\{t\("urlImportPlaceholder"\)\}/);
    expect(code).toMatch(/className="shrink-0"/);
  });

  it("标题那一行:标题截断、计数不缩", () => {
    expect(code).toMatch(/min-w-0 flex-1 truncate/);
    expect(code).toMatch(/shrink-0 text-ui-xs/);
  });

  it("清单容器锁住横向 —— 否则一条长标题就能顶开整个弹层", () => {
    // 按类逐个断言,不锁类名顺序:顺序是格式化工具的事,而这里在意的是"这几个类都在"。
    const list = code.split("\n").find((line) => line.includes("max-h-[38vh]")) ?? "";
    for (const cls of ["min-w-0", "overflow-y-auto", "overflow-x-hidden"]) {
      expect(list, `清单容器缺 ${cls}`).toContain(cls);
    }
  });

  it("勾选用仓库的 Checkbox,不是自画的方块 —— 自画的没有对勾,看不出是选中", () => {
    expect(code).toContain("<Checkbox");
    expect(code).not.toMatch(/rounded-\[4px\] border border-border-strong/);
  });
});
