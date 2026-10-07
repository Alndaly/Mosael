import React from "react";

import type { Job } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { MarkdownRefsContext, type MarkdownRefs } from "@/components/markdown/markdownRefs";
import { Hint } from "@/components/ui/tooltip";
import { CanvasAgentChat } from "@/features/agent/CanvasAgentChat";
import { linkNodeRefs } from "@/features/plugins/workbench/nodeRefs";
import { useJobWatch } from "@/features/plugins/workbench/workbenchParts";
import {
  workbenchCall,
  workbenchSnapshot,
  type WorkbenchRun,
  type WorkbenchTarget,
} from "@/features/plugins/workbench/workbenchSession";

type Translate = ReturnType<typeof useI18n>;

/** 报错写进上下文时最多多少字(上下文整段上限 4000,见 composerAttachments.MAX_CONTEXT_CHARS)。 */
const ERROR_CHARS = 600;

/** 这一张上一次在工作台里跑的那一次(这次会话里的):任务号、状态、失败的原因。 */
export interface AssistantLastRun {
  jobId: string;
  status: string;
  error: string;
}

/**
 * 「助手」每条消息附的页面上下文(ADR 0042 §5):哪台 ComfyUI(连接 id、版本)、画布上开着哪一张(名字、路径、改没改)、选中了谁、
 * 上次运行有没有报错。**不放整张图** —— 要看时它调 comfy_canvas_read。
 *
 * 上次运行:先看这一张在工作台里跑的那一次(有任务号,诊断时交给 comfy_check);没有失败的,再看画布上的事件 —— 在 ComfyUI
 * 自己点「运行」报的错也在里面(最近一次报错之后又跑成了就不提)。
 */
export function assistantContext(
  t: Translate,
  { target, state, events, lastRun }: {
    target: WorkbenchTarget;
    state: ComfyWorkbenchState | null;
    events: readonly ComfyWorkbenchEvent[];
    lastRun: AssistantLastRun | null;
  },
): string {
  const server = state?.server;
  const version = server?.comfyui
    ? t("workbenchAssistantVersion").replace("{version}", server.comfyui)
      + (server.frontend ? t("workbenchAssistantFrontend").replace("{version}", server.frontend) : "")
    : t("workbenchAssistantVersionUnknown");
  const open = state?.workflow;
  const workflow = !state ? t("workbenchAssistantNoCanvas")
    : !open ? t("workbenchAssistantNoWorkflow")
    : (open.path ? t("workbenchAssistantSaved").replace("{name}", open.name || open.path).replace("{path}", open.path)
      : t("workbenchAssistantUnsaved").replace("{name}", open.name || open.key))
      + (open.modified ? t("workbenchAssistantModified") : t("workbenchAssistantUnmodified"));
  const node = state?.selection.node;
  const selection = !state || state.selection.count === 0 ? t("workbenchAssistantSelectionNone")
    : node ? (node.title && node.title !== node.type ? t("workbenchAssistantSelectionTitled").replace("{title}", node.title)
      : t("workbenchAssistantSelectionOne")).replace("{id}", node.id).replace("{type}", node.type)
    : t("workbenchAssistantSelectionMany").replace("{n}", String(state.selection.count));
  return t("workbenchAssistantContext")
    .replaceAll("{id}", target.instanceId)
    .replace("{name}", target.instanceName)
    .replace("{version}", version)
    .replace("{workflow}", workflow)
    .replace("{selection}", selection)
    .replace("{run}", lastRunLine(t, events, lastRun));
}

function lastRunLine(t: Translate, events: readonly ComfyWorkbenchEvent[], lastRun: AssistantLastRun | null): string {
  if (lastRun?.status === "failed") {
    return t("workbenchAssistantRunFailed").replace("{job}", lastRun.jobId).replace("{error}", lastRun.error.slice(0, ERROR_CHARS));
  }
  const failed = events.map((one) => one.type).lastIndexOf("execution_error");
  const recovered = failed >= 0 && events.slice(failed + 1).some((one) => one.type === "execution_success");
  if (failed >= 0 && !recovered) {
    const error = events[failed];
    return t("workbenchAssistantCanvasError").replace("{node}", error.node).replace("{type}", error.nodeType ?? "")
      .replace("{message}", (error.message ?? "").slice(0, ERROR_CHARS));
  }
  if (!lastRun) return "";
  return (lastRun.status === "succeeded" ? t("workbenchAssistantRunOk") : t("workbenchAssistantRunGoing")).replace("{job}", lastRun.jobId);
}

/**
 * 回复里的 `#12`、`#12:5`:点了在画布上选中那个节点、移到中间(子图里的桥先一层层打开),和缺失项的「定位」同一个桥调用。
 * 没找到就在旁边说一句。
 */
function NodeRef({ node, children }: { node: string; children: React.ReactNode }) {
  const t = useI18n();
  const [note, setNote] = React.useState("");
  const locate = async () => {
    setNote("");
    const result = await workbenchCall({ op: "locate", node, subgraph: null });
    if (result.ok) return;
    setNote(result.error === "noNode" ? t("workbenchAssistantNoNode").replace("{node}", node)
      : result.error === "inSubgraph" ? t("workbenchAssistantInSubgraph")
      : t("workbenchCallFailed").replace("{why}", "message" in result && result.message ? result.message : result.error));
  };
  return (
    <>
      <Hint label={t("workbenchAssistantLocate").replace("{node}", node)}>
        <button
          type="button"
          data-comfy-node={node}
          className="cursor-pointer rounded-sm border-0 bg-transparent p-0 font-mono text-[0.95em] text-primary underline decoration-dotted underline-offset-2 hover:decoration-solid"
          onClick={() => void locate()}
        >
          {children}
        </button>
      </Hint>
      {note && <span role="status" className="ml-1 text-ui-xs text-destructive">{note}</span>}
    </>
  );
}

const NODE_REFS: MarkdownRefs = {
  rewrite: linkNodeRefs,
  render: (node, children) => <NodeRef node={node}>{children}</NodeRef>,
};

/**
 * 工作台的「助手」页签(ADR 0042 拍板 1):就是工作流、画板、剪辑页共用的那个智能体面板,停靠在这一列里(不浮、不关 ——
 * 换个页签就收起来了)。会话和 AI 工作台是同一个池子。页面上下文**发送那一刻**才取(画布一直在变)。
 */
export function AssistantPanel({ target, runs, workflowKey }: { target: WorkbenchTarget; runs: WorkbenchRun[]; workflowKey: string }) {
  const t = useI18n();
  const latest = runs.find((run) => run.workflowKey === workflowKey) ?? null;
  const job = useJobWatch(latest?.jobId ?? null).data as Job | undefined;
  const lastRun = React.useRef<AssistantLastRun | null>(null);
  lastRun.current = latest ? { jobId: latest.jobId, status: job?.status ?? "queued", error: job?.error ?? "" } : null;
  const contextLine = React.useCallback(() => {
    const { state, events } = workbenchSnapshot();
    return assistantContext(t, { target, state, events, lastRun: lastRun.current });
  }, [t, target]);
  return (
    <MarkdownRefsContext.Provider value={NODE_REFS}>
      <CanvasAgentChat
        contextLine={contextLine}
        emptyHint={t("workbenchAssistantEmpty")}
        placeholder={t("workbenchAssistantPlaceholder")}
        rectKey="mosael.comfy-workbench.agent.rect.v1"
        workspaceId={target.workspaceId}
        mode="docked"
        dockedLayout="inline"
      />
    </MarkdownRefsContext.Provider>
  );
}
