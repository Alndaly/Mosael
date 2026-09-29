import { Workflow as WorkflowIcon } from "lucide-react";

import type { Workflow, WorkflowGraph } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { CanvasPreview } from "@/components/layout/CanvasPreview";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { relativeTime } from "@/lib/time";

/**
 * 工作流卡片。**卡面上要能认出"是不是这一条"** —— 名字、一句说明、多大(几个节点)、
 * 上次改动是什么时候。此前列表只给名字和节点数,同名的「新工作流」并排五个时分不出来。
 */
export function WorkflowCard({ workflow }: { workflow: Workflow }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const nodes = (workflow.graph as unknown as WorkflowGraph).nodes ?? [];
  return (
    // 同 PublishCard:名字贴顶、"几个节点 · 版本 · 多久前"贴底,中间留给长短不一的说明。
    <article className="flex h-full flex-col gap-3">
      <CanvasPreview items={nodes.map((node, i) => ({ id: node.id, x: node.position?.x ?? i * 240, y: node.position?.y ?? 0, label: node.name || node.type, width: 180, height: 80 }))} edges={(workflow.graph as unknown as WorkflowGraph).edges ?? []} />
      <div className="flex items-center gap-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary">
          <WorkflowIcon size={13} />
        </span>
        <strong className="min-w-0 truncate text-ui-md font-[650] text-foreground">{workflow.name}</strong>
      </div>
      {workflow.description ? (
        <p className="m-0 line-clamp-2 text-ui-sm leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
          {toPlainText(workflow.description)}
        </p>
      ) : (
        <p className="m-0 text-ui-xs text-muted-foreground/60">{t("wfNoDescription")}</p>
      )}
      <div className="mt-auto flex items-center gap-1.5 pt-0.5 text-ui-xs text-muted-foreground">
        <span className="tabular-nums">{t("wfNodeCount").replace("{n}", String(nodes.length))}</span>
        <span aria-hidden>·</span>
        <span className="font-mono tabular-nums">v{workflow.revision}</span>
        <span aria-hidden>·</span>
        <span className="truncate">{relativeTime(workflow.updated_at, locale)}</span>
      </div>
    </article>
  );
}
