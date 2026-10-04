import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { startWorkflowFromPage, type WorkflowTemplateId } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { AGENT_DRAFT_EVENT, startNewAgentSession } from "@/features/agent/currentAgentSession";
import { emitOpenEvent, gotoRecord } from "@/lib/deepLink";

import type { PageInfo } from "./pageActions";
import type { ToolNotice } from "./useToolNotice";

/** 「用当前页开工」能接的三张分析模板(和后端 workflows/from_page.PAGE_TEMPLATES 是同一组)。 */
export const PAGE_TEMPLATES = ["viral_video_breakdown", "account_analysis", "comment_insights"] as const satisfies readonly WorkflowTemplateId[];

/**
 * 用当前页开工:
 * - 模板:后端建好(或打开已建的)那张图、填上当前页链接、读页面用当前档案;收起浏览器跳过去,由他检查后运行。
 * - 交给智能体:新开一条对话,把链接和标题放进输入框(不替他发送 —— 他多半还要说想做什么)。
 */
export function useStartTools(workspaceId: string, page: PageInfo, profileId: () => Promise<string | null>, notice: ToolNotice) {
  const t = useI18n();
  const qc = useQueryClient();
  const { say, failed } = notice;

  const template = useMutation({
    mutationFn: async (templateId: WorkflowTemplateId) =>
      startWorkflowFromPage({ workspace_id: workspaceId, template_id: templateId, url: page.url, profile_id: await profileId() }),
    onMutate: () => say({ tone: "busy", text: t("browserToolsWorking") }),
    onSuccess: (workflow) => {
      say(null);
      void qc.invalidateQueries({ queryKey: ["workflows"] });
      void window.mosaelPublish?.hideView();
      gotoRecord("/workflows", "mosael:open-workflow", workflow.id);
      // 浏览器已经收起,应用自己的提示看得见了。
      toast.success(t("browserToolsWorkflowReady").replace("{name}", workflow.name));
    },
    onError: failed,
  });

  const agent = useMutation({
    mutationFn: () => startNewAgentSession(qc, workspaceId),
    onSuccess: () => {
      emitOpenEvent(AGENT_DRAFT_EVENT, `${t("browserToolsAgentDraft")}\n${page.title || page.url}\n${page.url}\n`);
      void window.mosaelPublish?.hideView();
      gotoRecord("/ai");
    },
    onError: failed,
  });

  return { template, agent, busy: template.isPending || agent.isPending };
}
