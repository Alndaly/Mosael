/**
 * 棘轮:**节点检查器不认识任何具体节点**。
 *
 * 一个字段的下拉从哪来、跟着谁变、怎么过滤,全由后端的声明说了算(`options_from` +
 * `depends_on` + `allow_custom`,见 backend/app/domain/workflows/field_options.py)。这里曾经
 * 按节点类型写着一串 if —— 插件的包和工具、发布账号、可调用工作流、对话连接与模型各一条,
 * 而**插件节点是运行时才有的类型**,前端那张表永远覆盖不到它:装了插件的人在那两个下拉里
 * 一个选项都看不到。
 *
 * 判据只看取选项的那个函数,不看整份文件:节点类型在别处(配置提醒、专区渲染)仍然出现。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

export const RATCHET = true;

//: 字段怎么渲染、下拉从哪来,住在节点表单那一层(features/nodeForms)—— 工作流检查器和画板
//: 上的工具格共用它。检查器自己只剩宿主的事(数据边、专区)。
const VIEW = readFileSync(join(import.meta.dirname, "../nodeForms/NodeConfigForm.tsx"), "utf8");
const INSPECTOR = readFileSync(join(import.meta.dirname, "WorkflowsView.tsx"), "utf8");
//: 画板上一格的能力(和空格子上的生成器)是这份表单的第二个宿主(ADR 0021 P2,ADR 0025 修订):面板和它分字段的那一层。
const BOARD_TOOL = ["../boards/AbilityComposer.tsx", "../boards/composerFields.ts"]
  .map((path) => readFileSync(join(import.meta.dirname, path), "utf8"))
  .join("\n");

describe("节点检查器的下拉", () => {
  it("取选项那段里不出现节点类型判断", () => {
    const start = VIEW.indexOf("const dynamicOptions = (");
    expect(start, "dynamicOptions 改名了?这条棘轮要跟着改").toBeGreaterThan(0);
    const body = VIEW.slice(start, VIEW.indexOf("\n  };", start));
    expect(body).not.toMatch(/node\.type\s*===/);
    expect(body).not.toMatch(/node\.type\.startsWith/);
    //: 留下的两条都是**按声明**:来源名,以及按数据类型给素材。
    expect(body).toContain("spec?.options_from");
    expect(body).toContain('fieldDataType(spec as ConfigSpec | undefined) === "asset"');
  });

  it("能不能手填由声明说了算,不按字段名猜", () => {
    const line = VIEW.slice(VIEW.indexOf("const allowsCustomValue"), VIEW.indexOf("const allowsCustomValue") + 300);
    expect(line).toContain("allow_custom");
    expect(line).not.toMatch(/key === "model"/);
  });
});

describe("节点检查器的字段编辑器", () => {
  //: 一个字段用哪种控件(映射、JSON、挑 3D 模型、挑笔记……)由后端的字段声明点名(`editor`),
  //: 不由这里按「节点类型 + 字段名」认出来 —— 那是一张手抄表,插件节点永远进不去,而这条棘轮此前
  //: 只看取选项那段,于是 `node.type === "note_read" && key === "note_id"` 就在隔壁活了下来。
  it("渲染字段那段里不按节点类型、不按字段名分支", () => {
    const start = VIEW.indexOf("const renderField = (");
    expect(start, "renderField 改名了?这条棘轮要跟着改").toBeGreaterThan(0);
    const body = VIEW.slice(start, VIEW.indexOf("\n  };", start));
    expect(body).not.toMatch(/node\.type\s*===/);
    expect(body).not.toMatch(/node\.type\.startsWith/);
    expect(body).not.toMatch(/\bkey\s*===\s*["']/);
    //: 专用控件按声明选。
    expect(body).toMatch(/editor[^\n]*=== "note_ref"/);
  });
});

describe("字段渲染只有一份", () => {
  //: 检查器再长出自己的一份 renderField / dynamicOptions,上面几条就查不到它了 —— 而画板用的是表单那一份,
  //: 两边就会渐渐长得不一样。
  it("工作流检查器不自己渲染字段、不自己取选项", () => {
    expect(INSPECTOR).not.toContain("const renderField = (");
    expect(INSPECTOR).not.toContain("const dynamicOptions = (");
    expect(INSPECTOR).toContain("<NodeConfigForm");
  });
});

describe("画板上一格的能力的面板", () => {
  //: 它跑的是任何一个插件工具或能上画板的节点 —— 为哪一个写特例,插件那边永远覆盖不到。
  //: 画板只补自己那一半(字段接哪几格上游、用谁的连接),而「能接哪几种格子」也由后端说(board_sources)。
  it("用的是表单那一份,不按节点类型、不按字段名分支", () => {
    expect(BOARD_TOOL).toContain("<NodeConfigForm");
    expect(BOARD_TOOL).not.toContain("const renderField = (");
    expect(BOARD_TOOL).not.toContain("const dynamicOptions = (");
    expect(BOARD_TOOL).not.toMatch(/(nodeType|producer|tool\.type|tool\.id)\s*===\s*["'`]/);
    expect(BOARD_TOOL).not.toMatch(/\bkey\s*===\s*["']/);
    expect(BOARD_TOOL).toContain("board_sources");
  });
});
