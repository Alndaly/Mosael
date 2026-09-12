import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";
import { workflowTemplateText } from "@/features/workflows/WorkflowCommunityDialog";

/**
 * 官方工作流的名字和介绍**只写一处**。
 *
 * 它此前写了两处:社区对话框里一份声明,新建那条路上一句三元判断
 * (`templateId === "transcript_video_cleanup" ? A : B`)。两个模板时那句话碰巧是对的,
 * 而加第三个模板时它**不会报错** —— 只会把新模板建成第一个模板的名字和介绍,
 * 然后这份工作流在列表里顶着别人的名字,直到有人点开它。
 */
describe("模板的名字从声明里来", () => {
  it("每个模板拿到的是自己的那一份", () => {
    const ids = ["full_video_generation", "transcript_video_cleanup", "translated_dub"] as const;
    const titles = ids.map((id) => workflowTemplateText(id).title);
    expect(new Set(titles).size).toBe(ids.length);
    expect(workflowTemplateText("translated_dub").title).toBe("wfTranslatedDubTemplateName");
  });

  it("指向的都是真的存在的文案键", () => {
    for (const id of ["full_video_generation", "transcript_video_cleanup", "translated_dub"] as const) {
      const { title, description } = workflowTemplateText(id);
      for (const locale of ["zh-CN", "en-US"] as const) {
        expect(messages[locale][title], `${locale}/${title}`).toBeTruthy();
        expect(messages[locale][description], `${locale}/${description}`).toBeTruthy();
      }
    }
  });
});
