/**
 * 任务详情里的「这个任务做什么」:它绑的是哪张工作流图。
 *
 * 单独成文件是为了能测 —— 它有四档状态,而其中两档长得像、后果完全不同(见下面那段)。
 * 取数留在 SchedulerView,这里只管怎么画。
 */

import React from "react";
import { AlertTriangle, GitBranch } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { SettingsRow } from "@/components/settings/settings-layout";
import { gotoRecord } from "@/lib/deepLink";

interface WorkflowLike {
  id: string;
  name: string;
  description?: string | null;
}

/**
 * 绑了一个 id、却在列表里找不到它 —— 说明那个工作流**已经被删了**,而任务还指着它。
 *
 * 「还没读到」和「读过了,不在」必须分开:前者是暂时的,后者才是结论。混成一个的话,
 * 列表还在路上时每个任务都会先诬告自己一遍「工作流已删除」。
 *
 * 这一行画成什么样、任务的开关和「立即运行」能不能点,都按这一个判断走(后端的规则见
 * scheduler.ensure_runnable:绑的工作流不在了,任务不能启用、不能运行)。
 */
export function isBoundWorkflowGone(workflowId: string, workflows: WorkflowLike[], isPending: boolean): boolean {
  return Boolean(workflowId) && !isPending && !workflows.some((item) => item.id === workflowId);
}

export function BoundWorkflowRow({
  workflowId,
  workflows,
  isPending,
}: {
  workflowId: string;
  workflows: WorkflowLike[];
  isPending: boolean;
}) {
  const t = useI18n();
  const workflow = workflows.find((item) => item.id === workflowId) ?? null;
  /**
   * 此前这种情况下按钮里显示的是**那串裸 UUID**,既看不出是哪个工作流(它已经没有名字了),
   * 也看不出这是个故障 —— 一个 32 位十六进制串是给人看的东西里最无用的那种。
   */
  const missing = isBoundWorkflowGone(workflowId, workflows, isPending);
  const label = !workflowId
    ? t("taskNoWorkflow")
    : workflow
      ? workflow.name
      : isPending
        ? t("taskWorkflowLoading")
        : t("taskWorkflowGone");

  return (
    <SettingsRow
      label={t("wfBoundWorkflow")}
      description={missing ? t("taskWorkflowGoneDesc") : workflow?.description || t("taskWorkflowDesc")}
    >
      {/* **已删除的那一档不是按钮。**
          此前它照样能点、照样跳去工作流页 —— 而那一页当然找不到它(它已经被删了)。界面上
          写着「绑定的工作流已删除」,却又请你去那儿看一眼,等于在说"它可能还在";用户点过去、
          翻一遍、什么都没有,只会更糊涂。没有可去的地方时就不该做成可以去的样子:改成一块
          状态标记,下一步由旁边那句说明给(改绑一个,或删掉这个任务)。 */}
      {missing ? (
        <span
          role="status"
          className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-destructive/50 px-2.5 py-1.5 text-ui-sm text-destructive"
        >
          <AlertTriangle size={13} className="shrink-0" />
          <span className="truncate">{label}</span>
        </span>
      ) : (
        /* 按钮内容是工作流的**名字**,而用户的工作流常叫「新工作流」—— 光秃秃一个名字
           看起来像「新建工作流」动作按钮。图标 + 悬停说明把它钉回「这是当前绑定,点击去看」。 */
        <Button
          variant="outline"
          className="max-w-full"
          title={t("taskOpenWorkflow")}
          // 打开**它绑的那一张**。此前只换到工作流页,页面停在上次看的那张 —— 点「每日剪辑」
          // 却看到另一张图。没绑的时候没有要打开的那一条,只去列表挑一个。
          onClick={() => gotoRecord("/workflows", "mosael:open-workflow", workflow?.id)}
        >
          <GitBranch size={13} />
          <span className="truncate">{label}</span>
        </Button>
      )}
    </SettingsRow>
  );
}
