/**
 * 官方工作流的名字和介绍**只写一处**。
 *
 * 它此前写了三处:应用里的模板卡片(前端一张表)、官网模板页(同步脚本里另一份)、后端的图。
 * 三处各写各的,改一处不会让另外两处报错 —— 同一个模板在三个地方讲三种话。现在只有后端的
 * `TEMPLATE_CATALOG`,应用和官网都读它;前端只留图标。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

export const RATCHET = true;

const DIALOG = readFileSync(join(import.meta.dirname, "WorkflowCommunityDialog.tsx"), "utf8");
const CATALOG = readFileSync(
  join(import.meta.dirname, "../../../../backend/app/domain/workflows/templates.py"),
  "utf8",
);

describe("模板的名字只有一个产地", () => {
  it("前端只留图标,文案从接口来", () => {
    expect(DIALOG).toContain("fetchWorkflowTemplates");
    //: 名字/介绍/步骤/前置条件一律不在前端写死。
    expect(DIALOG).not.toMatch(/TemplateName|TemplateDescription|wfCommunityStage|wfCommunityRequirement[CV]/);
  });

  it("每个模板都有图标", () => {
    const icons = DIALOG.slice(DIALOG.indexOf("TEMPLATE_ICONS"), DIALOG.indexOf("};", DIALOG.indexOf("TEMPLATE_ICONS")));
    for (const id of ["full_video_generation", "transcript_video_cleanup", "translated_dub"]) {
      expect(CATALOG, `${id} 不在后端目录里`).toContain(`"${id}"`);
      expect(icons, `${id} 没有图标`).toContain(id);
    }
  });
});
