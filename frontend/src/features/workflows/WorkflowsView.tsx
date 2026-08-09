import React from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useStore } from "zustand";
import {
  Background,
  Controls,
  Handle,
  ConnectionLineType,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  XCircle,
  SkipForward,
  CheckCircle2,
  ChevronRight,
  AlignLeft,
  AlertTriangle,
  AudioLines,
  Bell,
  BookOpen,
  Bot,
  Boxes,
  Braces,
  CaseSensitive,
  CircleCheck,
  Code2,
  Download,
  Flag,
  GitBranch,
  Globe,
  History,
  Languages,
  Repeat,
  RefreshCw,
  Filter,
  ArrowLeft,
  Link2,
  Loader2,
  Mic,
  Pencil,
  Timer,
  PenLine,
  Play,
  Plus,
  Rocket,
  Redo2,
  Search,
  Undo2,
  Sparkles,
  Trash2,
  X,
  Type,
  FileUp,
  Wand2,
  Workflow as WorkflowIcon,
  Wrench,
  Tags,
  FolderInput,
  FolderPlus,
  AppWindow,
  MousePointerClick,
  Keyboard,
  ScanText,
  MousePointer2,
  Hourglass,
  PanelTopClose,
  FileOutput,
  Spline,
  Waypoints,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";

import {
  api,
  createWorkflow,
  deleteWorkflow,
  exportWorkflowFile,
  fetchWorkflowNodeTypes,
  importWorkflow,
  listAssets,
  listJobEvents,
  listProviderModels,
  listPublishAccounts,
  listVoices,
  listWorkflows,
  runWorkflow,
  updateWorkflow,
  type Asset,
  type GenerationModel,
  type PluginTool,
  type TaskEvent,
  type Workflow,
  type WorkflowGraph,
  type WorkflowNodeType,
  type Workspace,
} from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Combobox } from "@/components/app/combobox";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfigNotice } from "@/components/layout/ConfigNotice";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { VarTextarea } from "@/features/workflows/VarTextarea";
import { CodeEditor, type CodeEditorHandle } from "@/components/app/code-editor";
import { WorkflowAgentChat, type WorkflowAgentMode } from "@/features/workflows/WorkflowAgentChat";
import { WorkflowRunHistory } from "@/features/workflows/WorkflowRunHistory";
import { createWorkflowGraphStore } from "@/stores/workflowGraphStore";
import { saveJsonToDisk } from "@/lib/download";
import {
  aspectRatioOptions,
  capabilityNumber,
  capabilityString,
  durationOptions,
  imageSizeOptions,
  maxImages,
  supportsParameter,
  videoResolutionOptions,
} from "@/lib/generationCapabilities";
import { cn } from "@/lib/utils";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { blurFloatingPanels, hasFocusedFloatingPanel } from "@/features/workflows/useFloatingPanel";
import {
  analyzeWorkflow,
  extractRefs,
  inputType,
  outputType,
  typesCompatible,
  type DataType,
  type NodeIssue,
} from "@/features/workflows/analyze";
import { AssetInlinePreview } from "@/components/app/asset-preview";
import { collapseToSubgraph } from "@/features/workflows/collapse";
import { assetOutputs, stepsByNode } from "@/features/workflows/runSteps";
import { isDataConnection, isDuplicateControlEdge } from "@/features/workflows/connections";

type ProviderDefault = components["schemas"]["ProviderDefaultOut"];
type ProviderProfile = components["schemas"]["ProviderProfileOut"];

/** 节点类型语义色(与轨道颜色同属内容色,不算点缀):
    开始=绿 / LLM=紫 / 检索=蓝 / 插件=琥珀 / 转写=青 / 导出=玫红 / 生成=品红;
    其余类型走 --wf-node-color 的 primary 兜底。 */
const WF_NODE_COLORS: Record<string, string> = {
  start: "#16a34a",
  llm: "#7c3aed",
  kb_search: "#2563eb",
  plugin_tool: "#d97706",
  transcribe_asset: "#0891b2",
  export_sequence: "#e11d48",
  ai_generate: "#c026d3",
  browser_open: "#0ea5e9",
  browser_navigate: "#0ea5e9",
  browser_click: "#0ea5e9",
  browser_input: "#0ea5e9",
  browser_upload: "#0ea5e9",
  browser_extract: "#0ea5e9",
  browser_wait: "#0ea5e9",
  browser_scroll: "#0ea5e9",
  browser_evaluate: "#0ea5e9",
  browser_close: "#0ea5e9",
  call_workflow: "#6366f1",
  output: "#059669",
  subgraph: "#8b5cf6",
  loop_foreach: "#6366f1",
  loop_while: "#6366f1",
};

/** 节点类型 → 图标(与节点面板/画布一致)。 */
const NODE_ICONS: Record<string, React.ReactNode> = {
  start: <Flag size={13} />,
  llm: <Sparkles size={13} />,
  kb_search: <BookOpen size={13} />,
  plugin_tool: <Wrench size={13} />,
  transcribe_asset: <Mic size={13} />,
  export_sequence: <Download size={13} />,
  ai_generate: <Wand2 size={13} />,
  condition: <GitBranch size={13} />,
  http_request: <Globe size={13} />,
  code: <Code2 size={13} />,
  template: <AlignLeft size={13} />,
  publish: <Rocket size={13} />,
  json_extract: <Braces size={13} />,
  text_transform: <CaseSensitive size={13} />,
  delay: <Timer size={13} />,
  synthesize_speech: <AudioLines size={13} />,
  browser_open: <AppWindow size={13} />,
  browser_navigate: <Globe size={13} />,
  browser_click: <MousePointerClick size={13} />,
  browser_input: <Keyboard size={13} />,
  browser_upload: <FileUp size={13} />,
  browser_extract: <ScanText size={13} />,
  browser_wait: <Hourglass size={13} />,
  browser_scroll: <MousePointer2 size={13} />,
  browser_evaluate: <Code2 size={13} />,
  browser_close: <PanelTopClose size={13} />,
  call_workflow: <WorkflowIcon size={13} />,
  output: <FileOutput size={13} />,
  subgraph: <Boxes size={13} />,
  notify: <Bell size={13} />,
  translate: <Languages size={13} />,
  loop_foreach: <Repeat size={13} />,
  loop_while: <RefreshCw size={13} />,
  asset_query: <Filter size={13} />,
  asset_tag: <Tags size={13} />,
  asset_update: <FolderInput size={13} />,
  project_create: <FolderPlus size={13} />,
};

interface WfNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  typeLabel: string;
  /** 就绪度角标:分析出的最高严重度 + 问题条数 + 悬浮明细。 */
  badge?: { severity: "error" | "warn"; count: number; title: string } | null;
  /** 数据接点:左侧输入(连接态字段)、右侧输出(节点声明的 outputs)。 */
  inputs?: string[];
  outputs?: string[];
  /** 本次运行到这一步的状态。运行结束后保留,方便回看这次跑成什么样。 */
  run?: { status: "running" | "done" | "skipped" | "failed"; ms?: number; error?: string } | null;
  /** 这一步产出的素材(节点注册表里声明为 asset 的输出)。节点上直接出缩略图。 */
  runAssets?: string[];
}

/** 画布节点:语义色图标 + 名称 + 类型标签,全平面卡片。
    条件节点右侧是「真/假」两个分支端点,其余节点单一出口。
    缺配置/失效引用/断连的节点在右上角挂一枚告警角标,一眼可辨。 */
/** 节点上的产出预览:这一步生成了什么,直接摆在节点里 —— 不用再点开历史面板去找。
 *  素材可能已被删除(取不到就不渲染),所以查询失败是正常路径。 */
function NodeResultPreview({ assetIds }: { assetIds: string[] }) {
  const assets = useQueries({
    queries: assetIds.slice(0, 2).map((id) => ({
      queryKey: ["asset", id],
      queryFn: () => api<Asset>(`/api/assets/${id}`),
      staleTime: 60_000,
      retry: false,
    })),
  });
  const ready = assets.map((q) => q.data).filter(Boolean) as Asset[];
  if (ready.length === 0) return null;
  return (
    // 铺满卡片宽度、统一高度、object-cover —— 让它看着是节点的一部分,而不是贴上去的一张方图。
    //
    // **只有视频/音频挂 nodrag**。整块都挂的话,缩略图占了节点大半个身体,从图上按下就拖不动
    // 节点了 —— 用户感觉像"焦点卡住",换个地方按又好了。图片不需要:拖动不会触发 click,
    // 原地点一下照样打开大图。
    <div className="grid grid-flow-col justify-stretch gap-1 overflow-hidden rounded-md border border-border">
      {ready.map((asset) => (
        <AssetInlinePreview
          key={asset.id}
          assetId={asset.id}
          name={asset.name || asset.original_filename}
          kind={asset.kind}
          lazy={false}
          plain
          className={
            asset.kind === "image"
              ? "block h-[62px] w-full object-cover"
              : asset.kind === "video"
                ? "h-[62px] w-full bg-black object-cover"
                : "w-full"
          }
        />
      ))}
    </div>
  );
}

function WfNode({ data, selected }: NodeProps) {
  const t = useI18n();
  const d = data as WfNodeData;
  const isCondition = d.nodeType === "condition";
  const badge = d.badge ?? null;
  const inputs = d.inputs ?? [];
  const outputs = d.outputs ?? [];
  // 条件节点保持紧凑(真/假分支端点),不上数据 IO 体;其余节点显示输入/输出接点。
  const showIo = !isCondition && (inputs.length > 0 || outputs.length > 0);
  return (
    <div
      className={cn(
        "group/node relative flex min-w-[172px] flex-col gap-1.5 rounded-lg border border-border bg-panel px-3 py-[9px] transition-[border-color] duration-100 hover:border-border-strong",
        showIo && "min-w-[210px]",
        badge && !selected && (badge.severity === "error"
          ? "border-[color-mix(in_srgb,var(--destructive)_60%,var(--border))]"
          : "border-[color-mix(in_srgb,#d97706_55%,var(--border))]"),
        // 运行态压过就绪角标:正在跑/跑挂了是此刻更要紧的信息。
        d.run?.status === "running" && "border-primary shadow-[0_0_0_1px_var(--primary)]",
        d.run?.status === "done" && "border-[color-mix(in_srgb,#3fb950_55%,var(--border))]",
        d.run?.status === "failed" && "border-[color-mix(in_srgb,var(--destructive)_70%,var(--border))]",
        d.run?.status === "skipped" && "opacity-55",
        selected && "border-primary shadow-[0_0_0_1px_var(--primary)] hover:border-primary",
      )}
      data-node-type={d.nodeType}
    >
      {/* 控制入(左上) */}
      {d.nodeType !== "start" && (
        <Handle type="target" position={Position.Left} className={cn("h-[9px]! w-[9px]! rounded-full! border-[1.5px]! border-border-strong! bg-panel! transition-[border-color,transform] duration-100 after:absolute after:-inset-[7px] after:rounded-full after:content-[''] hover:border-primary! group-hover/node:border-primary! [&.react-flow\_\_handle-left:hover]:[transform:translate(-50%,-50%)_scale(1.35)]! [&.react-flow\_\_handle-right:hover]:[transform:translate(50%,-50%)_scale(1.35)]!", selected && "border-primary!")} style={{ top: 22 }} />
      )}
      {d.run && (
        <span
          className="absolute -left-1.5 -top-1.5 grid h-[18px] min-w-[18px] place-items-center rounded-full border border-border bg-panel px-[3px]"
          title={d.run.error ?? undefined}
        >
          {d.run.status === "running" ? (
            <Loader2 size={11} className="animate-spin text-primary" />
          ) : d.run.status === "done" ? (
            <CheckCircle2 size={11} className="text-[#3fb950]" />
          ) : d.run.status === "failed" ? (
            <XCircle size={11} className="text-destructive" />
          ) : (
            <SkipForward size={11} className="text-muted-foreground" />
          )}
        </span>
      )}
      {/* 耗时贴在右下角:跑完一眼看出哪一步慢。 */}
      {d.run?.ms != null && (
        <span className="timecode absolute -bottom-2 right-1.5 rounded-full border border-border bg-panel px-1.5 text-[9.5px] text-muted-foreground">
          {(d.run.ms / 1000).toFixed(2)}s
        </span>
      )}
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 flex-none place-items-center rounded-md bg-[color-mix(in_srgb,var(--wf-node-color,var(--primary))_12%,transparent)] text-[color:var(--wf-node-color,var(--primary))]" style={{ "--wf-node-color": WF_NODE_COLORS[d.nodeType] } as React.CSSProperties}>{NODE_ICONS[d.nodeType] ?? <Type size={13} />}</span>
        <span className="grid min-w-0 gap-px [&_small]:text-[10.5px] [&_small]:text-muted-foreground [&_strong]:truncate [&_strong]:text-[12.5px]">
          <strong>{d.label}</strong>
          {/* 未改名时 label 就是类型名,别再重复显示一行类型。 */}
          {d.label !== d.typeLabel && <small>{d.typeLabel}</small>}
        </span>
      </div>
      <NodeResultPreview assetIds={d.runAssets ?? []} />
      {badge && (
        <span
          className={cn(
            "absolute -right-[7px] -top-[7px] inline-flex h-4 min-w-4 items-center gap-0.5 rounded-full px-1 text-[10px] font-bold leading-none text-white",
            badge.severity === "error" ? "bg-destructive" : "bg-[#d97706]",
          )}
          title={badge.title}
          aria-label={badge.title}
        >
          <AlertTriangle size={11} />
          {badge.count > 1 ? badge.count : null}
        </span>
      )}
      {isCondition ? (
        <>
          <Handle id="true" type="source" position={Position.Right} className={cn("h-[9px]! w-[9px]! rounded-full! border-[1.5px]! border-border-strong! bg-panel! transition-[border-color,transform] duration-100 after:absolute after:-inset-[7px] after:rounded-full after:content-[''] hover:border-primary! group-hover/node:border-primary! [&.react-flow\_\_handle-left:hover]:[transform:translate(-50%,-50%)_scale(1.35)]! [&.react-flow\_\_handle-right:hover]:[transform:translate(50%,-50%)_scale(1.35)]!", "border-[#16a34a]!", selected && "border-primary!")} style={{ top: "32%" }} />
          <Handle id="false" type="source" position={Position.Right} className={cn("h-[9px]! w-[9px]! rounded-full! border-[1.5px]! border-border-strong! bg-panel! transition-[border-color,transform] duration-100 after:absolute after:-inset-[7px] after:rounded-full after:content-[''] hover:border-primary! group-hover/node:border-primary! [&.react-flow\_\_handle-left:hover]:[transform:translate(-50%,-50%)_scale(1.35)]! [&.react-flow\_\_handle-right:hover]:[transform:translate(50%,-50%)_scale(1.35)]!", "border-[#e11d48]!", selected && "border-primary!")} style={{ top: "68%" }} />
          <span className="pointer-events-none absolute -right-5 top-[calc(32%-7px)] text-[9px] font-semibold text-[#16a34a]">真</span>
          <span className="pointer-events-none absolute -right-5 top-[calc(68%-7px)] text-[9px] font-semibold text-[#e11d48]">假</span>
        </>
      ) : (
        <Handle type="source" position={Position.Right} className={cn("h-[9px]! w-[9px]! rounded-full! border-[1.5px]! border-border-strong! bg-panel! transition-[border-color,transform] duration-100 after:absolute after:-inset-[7px] after:rounded-full after:content-[''] hover:border-primary! group-hover/node:border-primary! [&.react-flow\_\_handle-left:hover]:[transform:translate(-50%,-50%)_scale(1.35)]! [&.react-flow\_\_handle-right:hover]:[transform:translate(50%,-50%)_scale(1.35)]!", selected && "border-primary!")} style={{ top: 22 }} />
      )}
      {showIo && (
        // 接口区做成卡片"页脚条":压进左右 padding、贴住底边、subtle 底色 —
        // 端口行读作独立的接线区,而不是悬在卡片下半的零散小字(空的一侧也不再是大片留白)。
        <div className="-mx-3 -mb-[9px] mt-0.5 flex justify-between gap-4 rounded-b-[9px] border-t border-border bg-panel-subtle px-3 py-[6px]">
          <div className="flex min-w-0 flex-col gap-[3px]">
            {inputs.map((key) => (
              <div className="relative flex min-h-4 items-center" key={key}>
                <Handle
                  id={`in:${key}`}
                  type="target"
                  position={Position.Left}
                  className="h-[9px]! w-[9px]! rounded-full! border-[1.5px]! border-primary! bg-panel! data-[dtype=any]:border-border-strong! data-[dtype=asset]:border-[#c026d3]! data-[dtype=json]:border-[#0891b2]! data-[dtype=number]:border-[#d97706]! data-[dtype=sequence]:border-[#e11d48]! data-[dtype=text]:border-[#64748b]! left-[-12px]!"
                  data-dtype={inputType(d.nodeType, key)}
                />
                {/* 有本地化标签走正文字体;裸标识符(如 items)与输出侧同用 mono,同卡不混排。 */}
                <span className={cn("whitespace-nowrap text-[10.5px] text-muted-foreground", !FIELD_LABEL_KEYS[key] && "font-mono")}>
                  {FIELD_LABEL_KEYS[key] ? t(FIELD_LABEL_KEYS[key]) : key}
                </span>
              </div>
            ))}
          </div>
          <div className="flex min-w-0 flex-col gap-[3px]">
            {outputs.map((output) => (
              <div className="relative flex min-h-4 items-center justify-end" key={output}>
                <span className="whitespace-nowrap font-mono text-[10.5px] text-muted-foreground">{output}</span>
                <Handle
                  id={`out:${output}`}
                  type="source"
                  position={Position.Right}
                  className="h-[9px]! w-[9px]! rounded-full! border-[1.5px]! border-primary! bg-panel! data-[dtype=any]:border-border-strong! data-[dtype=asset]:border-[#c026d3]! data-[dtype=json]:border-[#0891b2]! data-[dtype=number]:border-[#d97706]! data-[dtype=sequence]:border-[#e11d48]! data-[dtype=text]:border-[#64748b]! right-[-12px]!"
                  data-dtype={outputType(d.nodeType, output)}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** 属性面板里一格字段的样式(标签 + 控件 + 说明)。面板里这串还散落在几十处内联,
 *  新写的部分先用这个常量,避免再多复制一遍。 */
const FIELD_BOX =
  "grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none";

/** 助手面板的开合记忆。 */
const AGENT_PANEL_KEY = "openstudio:workflow-agent-open";

const NODE_COMPONENT_TYPES = { wf: WfNode };


/** 贴靠面板的几何:宽度固定,高度自适应但封顶;与节点之间留 10px 间隙,离窗口边至少 12px。 */
const ANCHOR = { width: 320, gap: 10, margin: 12, maxHeight: 560 } as const;

export type AnchorBox = { left: number; top: number; maxHeight: number };

/**
 * 把面板贴到**节点旁边**浮现的定位计算。
 *
 * 为什么不固定在右侧:画布上的节点可能在任何位置,而固定面板逼着视线在「节点」和「屏幕另一头的
 * 表单」之间来回跳;工作流页右侧已经挤了 AI 助手、执行历史等好几层。贴着节点浮现则是「改哪儿看哪儿」。
 *
 * 摆放优先右侧,右边放不下翻左侧,左右都放不下就落到节点下方(再不行放上方),最后统一夹进窗口。
 * 位置随视口变化重算(平移/缩放时面板跟着节点走),所以调用方要在 onMove 时让依赖变化。
 */
export function anchorToNode(
  instance: ReactFlowInstance | null,
  /** 要贴靠的节点,**取自我们自己的 nodes 状态**,不是 instance.getNode()。
   *
   *  读 instance 会拿到过期位置:React Flow 的内部 store 是在**提交后的副作用**里从 nodes
   *  prop 同步的,而这个位置是在 render 期间算的。撤销一次节点拖动时,graph 和 nodes 在同一批
   *  更新里变新,内部 store 还停在旧位置 —— 于是表单留在了节点撤销前的地方,而且之后依赖不再
   *  变化,它就一直留在那儿(除非用户顺手平移一下画布)。这正是「撤销后表单不跟随」的成因。 */
  node: Pick<Node, "position" | "measured" | "width" | "height"> | null,
  /** 可视区尺寸。作为入参而不是直接读 window:这样这段摆放逻辑是纯函数,可以直接单测
   *  (仓库里没装 jsdom,其余测试也都是纯逻辑)。 */
  viewport: { width: number; height: number },
): AnchorBox | null {
  if (!instance || !node) return null;
  // v12:measured 是渲染后的真实尺寸;没测到时用节点默认宽度兜底,别让面板贴到错的地方。
  const width = node.measured?.width ?? node.width ?? 200;
  const height = node.measured?.height ?? node.height ?? 60;
  const topLeft = instance.flowToScreenPosition({ x: node.position.x, y: node.position.y });
  const bottomRight = instance.flowToScreenPosition({
    x: node.position.x + width,
    y: node.position.y + height,
  });

  const { width: viewW, height: viewH } = viewport;
  const maxHeight = Math.min(ANCHOR.maxHeight, viewH - ANCHOR.margin * 2);

  // 侧放只有**真的能放在节点旁边**才算数。早先的写法在左右都放不下时用「节点左缘」兜底,
  // 结果面板压在节点身上,而随后的判定只看窗口边界、不看是否避开了节点 —— 于是「落到下方」
  // 这条分支永远不会触发。单测正是在这里发现的。
  const rightLeft = bottomRight.x + ANCHOR.gap;
  const leftLeft = topLeft.x - ANCHOR.gap - ANCHOR.width;
  let left: number;
  let top = topLeft.y;
  if (rightLeft + ANCHOR.width <= viewW - ANCHOR.margin) {
    left = rightLeft; // 首选:节点右侧
  } else if (leftLeft >= ANCHOR.margin) {
    left = leftLeft; // 次选:翻到左侧
  } else {
    // 左右都放不下(节点很宽或窗口很窄):落到节点下方,下方也放不下就放上方。
    left = topLeft.x;
    const below = bottomRight.y + ANCHOR.gap;
    top = below + maxHeight <= viewH - ANCHOR.margin ? below : topLeft.y - ANCHOR.gap - maxHeight;
  }
  return {
    left: Math.min(Math.max(ANCHOR.margin, left), Math.max(ANCHOR.margin, viewW - ANCHOR.width - ANCHOR.margin)),
    top: Math.min(Math.max(ANCHOR.margin, top), Math.max(ANCHOR.margin, viewH - maxHeight - ANCHOR.margin)),
    maxHeight,
  };
}

/** 配置字段 key → 人类可读标签键(Dify 式:面板不暴露裸 config key)。 */
const FIELD_LABEL_KEYS: Record<string, MessageKey> = {
  prompt: "wffPrompt",
  system: "wffSystem",
  profile_id: "wffProfile",
  model: "wffModel",
  query: "wffQuery",
  limit: "wffLimit",
  plugin_id: "wffPlugin",
  tool_name: "wffTool",
  input: "wffInput",
  asset_id: "wffAsset",
  dataset_id: "wffDataset",
  sequence_id: "wffSequence",
  provider: "wffProvider",
  kind: "wffKind",
  account_id: "wffAccount",
  title: "wffTitle",
  description: "wffDescription",
  left: "wffLeft",
  op: "wffOp",
  right: "wffRight",
  method: "wffMethod",
  url: "wffUrl",
  headers: "wffHeaders",
  body: "wffBody",
  code: "wffCode",
  template: "wffTemplate",
  params: "wffParams",
  negative_prompt: "wffNegativePrompt",
  source_asset_ids: "wffSourceAssets",
};

/** 「AI 生成素材」自己渲染这几项,不走通用字段列表。
 *
 *  provider / model / kind 是**执行器要的形状**,不是用户要做的选择 —— 用户只决定一件事:
 *  用哪个生成模型。三者各自铺成必填框时,面板里会出现两个都叫「模型」的字段(一个选择器、
 *  一个输入框),外加一个能和模型矛盾的「类型」(选了图像模型却把类型填成 video)。
 *  parameters 同理:按模型能力生成的下拉已经在管它,再铺一个原始 JSON 框就是同一份东西两处编辑。 */
const GENERATE_SPECIAL_CONFIG_KEYS = new Set(["provider", "model", "kind", "parameters"]);

const LLM_SPECIAL_CONFIG_KEYS = new Set([
  "preset",
  "temperature",
  "top_p",
  "max_tokens",
  "frequency_penalty",
  "presence_penalty",
  "seed",
  "stop",
  "response_format",
  "json_schema_name",
  "json_schema",
  "json_schema_strict",
]);

/** 连线统一带闭合箭头,方向一目了然。 */
/**
 * 连线走线方式。值直接就是 React Flow 的内置边类型,不另建一层映射 ——
 * 多一层枚举只会在加一种时要改两处。
 *
 * 走线方式是**看图习惯**而不是工作流数据:同一张图,有人要贝塞尔的流畅,有人要直角好对齐。
 * 所以存本地偏好、对所有工作流生效,不写进 graph —— 写进去会让同一张图在两个人眼里长得不一样,
 * 还会让"换了个线型"变成一次图变更、触发自动保存和脏状态。
 */
const EDGE_SHAPES = ["default", "smoothstep"] as const;
type EdgeShape = (typeof EDGE_SHAPES)[number];

const EDGE_SHAPE_ICON: Record<EdgeShape, LucideIcon> = {
  default: Spline,
  smoothstep: Waypoints,
};

/** 走线方式对应的 i18n key。`as const` 不能去掉:t() 只接受字面量键的联合,
 *  标成 Record<EdgeShape, string> 会把值放宽成 string,当场编译不过。 */
const EDGE_SHAPE_LABEL = {
  default: "wfEdgeBezier",
  smoothstep: "wfEdgeSmoothStep",
} as const;

const DEFAULT_EDGE_OPTIONS = {
  markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: "var(--border-strong)" },
};

export function WorkflowsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [menuRenaming, setMenuRenaming] = React.useState<Workflow | null>(null);
  const [menuDeleting, setMenuDeleting] = React.useState<Workflow | null>(null);

  // 通知/任务中心深链(openstudio:open-* 事件通道):直接选中对应工作流。
  React.useEffect(() => {
    const onOpenWorkflow = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (typeof id === "string" && id) setSelectedId(id);
    };
    window.addEventListener("openstudio:open-workflow", onOpenWorkflow);
    return () => window.removeEventListener("openstudio:open-workflow", onOpenWorkflow);
  }, []);

  const workflows = useQuery({
    queryKey: ["workflows", workspace.id],
    queryFn: () => listWorkflows(workspace.id),
    // 智能体经确认卡改图后 updated_at 变化,轮询让画布自动跟进。
    refetchInterval: 5000,
  });
  const nodeTypes = useQuery({ queryKey: ["workflow-node-types"], queryFn: fetchWorkflowNodeTypes, staleTime: Infinity });

  const create = useMutation({
    mutationFn: () => createWorkflow({ workspace_id: workspace.id, name: t("wfDefaultName"), description: "" }),
    onSuccess: (workflow) => {
      setSelectedId(workflow.id);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
  });

  const menuRename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => updateWorkflow(id, { name }),
    onSuccess: () => {
      setMenuRenaming(null);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
  });
  const menuRemove = useMutation({
    mutationFn: (id: string) => deleteWorkflow(id),
    onSuccess: () => {
      setMenuDeleting(null);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
  });
  // 导出:取后端信封(格式/版本权威在后端)→ 落成 .openstudio-workflow.json 文件。
  const menuExport = useMutation({
    mutationFn: async (workflow: Workflow) => {
      const envelope = await exportWorkflowFile(workflow.id);
      saveJsonToDisk(`${workflow.name}.openstudio-workflow.json`, envelope);
    },
    onError: (error: Error) => toast.error(t("wfExportFailed"), { description: error.message }),
  });
  // 导入:读文件 → JSON 解析(坏文件在本地就报)→ 后端校验落库 → 选中新工作流。
  const importInputRef = React.useRef<HTMLInputElement | null>(null);
  const importFile = useMutation({
    mutationFn: async (file: File) => {
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(await file.text()) as Record<string, unknown>;
      } catch {
        throw new Error(t("wfImportInvalid"));
      }
      return importWorkflow({ workspace_id: workspace.id, data });
    },
    onSuccess: (workflow) => {
      toast.success(t("wfImported").replace("{name}", workflow.name));
      setSelectedId(workflow.id);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
    onError: (error: Error) => toast.error(t("wfImportFailed"), { description: error.message }),
  });
  const menuRun = useMutation({
    mutationFn: (id: string) => runWorkflow(id),
    onSuccess: (_data, id) => {
      toast.success(t("wfRunQueued"));
      // Without this the history panel, if already open with nothing in flight, never polls
      // and never refetches — the run appears only after navigating away and back.
      void qc.invalidateQueries({ queryKey: ["workflow-runs", id] });
    },
    onError: (error: Error) => toast.error(t("wfRunFailed"), { description: error.message }),
  });

  const selected = (workflows.data ?? []).find((w) => w.id === selectedId) ?? (workflows.data ?? [])[0] ?? null;

  if (workflows.isSuccess && (workflows.data ?? []).length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
        <EmptyState
          icon={<WorkflowIcon size={22} />}
          title={t("wfEmptyTitle")}
          body={t("wfEmptyBody")}
          action={
            <span className="inline-flex items-center gap-2">
              <Button loading={create.isPending} onClick={() => create.mutate()}>
                <Plus size={15} /> {t("wfCreate")}
              </Button>
              <Button variant="outline" loading={importFile.isPending} onClick={() => importInputRef.current?.click()}>
                <FileUp size={15} /> {t("wfImport")}
              </Button>
              <input
                ref={importInputRef}
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) importFile.mutate(file);
                }}
              />
            </span>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
      <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)] gap-2 max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]">
        <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[auto_minmax(0,1fr)] max-[880px]:flex max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:px-1.5 max-[880px]:py-[5px] max-[880px]:[&>div:first-child]:contents">
          <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
            <h2>{t("navWorkflows")}</h2>
            <span className="inline-flex items-center gap-1">
              <Button variant="outline" size="icon" className="h-7 w-7" title={t("wfImport")} aria-label={t("wfImport")} loading={importFile.isPending} onClick={() => importInputRef.current?.click()}>
                <FileUp size={14} />
              </Button>
              <Button variant="outline" size="icon" className="h-7 w-7" title={t("wfCreate")} aria-label={t("wfCreate")} loading={create.isPending} onClick={() => create.mutate()}>
                <Plus size={14} />
              </Button>
            </span>
            <input
              ref={importInputRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = ""; // 同一文件可再次选择
                if (file) importFile.mutate(file);
              }}
            />
          </div>
          <div className="grid content-start gap-1 overflow-y-auto p-1.5 [&:has(>.empty-inline:only-child)]:content-stretch max-[880px]:order-1 max-[880px]:flex max-[880px]:min-w-0 max-[880px]:flex-1 max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:overflow-x-auto max-[880px]:p-0">
            {workflows.isLoading &&
              (workflows.data ?? []).length === 0 &&
              [0, 1, 2, 3].map((i) => (
                <div key={`sk${i}`} className="flex items-center gap-[9px] px-2 py-1.5" aria-hidden>
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <Skeleton className="h-3.5 w-3/4 rounded" />
                    <Skeleton className="h-2.5 w-1/3 rounded" />
                  </div>
                </div>
              ))}
            {(workflows.data ?? []).map((workflow) => (
              <ContextMenu key={workflow.id}>
                <ContextMenuTrigger asChild>
                  <button
                    type="button"
                    className={cn("flex cursor-pointer items-center gap-[9px] rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted max-[880px]:shrink-0 max-[880px]:py-1", selected?.id === workflow.id && "bg-accent hover:bg-accent")}
                    onClick={() => setSelectedId(workflow.id)}
                  >
                    <span className="min-w-0 [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-[12.5px] [&_strong]:font-semibold max-[880px]:[&_small]:hidden">
                      <strong>{workflow.name}</strong>
                      <small>
                        {t("wfNodeCount").replace("{n}", String((workflow.graph as unknown as WorkflowGraph).nodes?.length ?? 0))}
                      </small>
                    </span>
                  </button>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem onSelect={() => menuRun.mutate(workflow.id)}>
                    <Play /> {t("wfRun")}
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => setMenuRenaming(workflow)}>
                    <Pencil /> {t("rename")}
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => menuExport.mutate(workflow)}>
                    <Download /> {t("wfExport")}
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => importInputRef.current?.click()}>
                    <FileUp /> {t("wfImport")}
                  </ContextMenuItem>
                  <ContextMenuSeparator />
                  <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setMenuDeleting(workflow)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
          </div>
        </aside>
        <div className="grid min-w-0 overflow-y-auto">
          {selected && nodeTypes.data ? (
            <WorkflowEditor
              key={selected.id}
              workflow={selected}
              nodeTypes={nodeTypes.data}
              workspaceId={workspace.id}
            />
          ) : (
            <EmptyState icon={<WorkflowIcon size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
        </div>
      </div>
      <RenameDialog
        open={menuRenaming !== null}
        title={t("rename")}
        initialValue={menuRenaming?.name ?? ""}
        onCancel={() => setMenuRenaming(null)}
        onSubmit={(name) => menuRenaming && menuRename.mutate({ id: menuRenaming.id, name })}
      />
      <ConfirmDialog
        open={menuDeleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("wfDeleteBody")}
        onCancel={() => setMenuDeleting(null)}
        onConfirm={() => menuDeleting && menuRemove.mutate(menuDeleting.id)}
      />
    </div>
  );
}

function toFlowNodes(graph: WorkflowGraph, registry: Map<string, WorkflowNodeType>): Node[] {
  return (graph.nodes ?? []).map((node) => ({
    id: node.id,
    type: "wf",
    position: node.position ?? { x: 80, y: 80 },
    data: {
      label: node.name || registry.get(node.type)?.label || node.type,
      nodeType: node.type,
      typeLabel: registry.get(node.type)?.label ?? node.type,
      inputs: node.inputs ?? [],
      // 过滤通配输出(如 start 的 *params),它们不是可连接的具体接点。
      outputs: (registry.get(node.type)?.outputs ?? []).filter((output) => !output.startsWith("*")),
    } satisfies WfNodeData,
    deletable: true,
  }));
}

function toFlowEdges(graph: WorkflowGraph): Edge[] {
  const nodeType = new Map((graph.nodes ?? []).map((node) => [node.id, node.type]));
  return (graph.edges ?? []).map((edge) => {
    // 数据边:接输出接点 out:x → 输入接点 in:y。蓝色流动虚线,不带箭头(终点是接点)。
    if (edge.kind === "data") {
      // 类型不匹配的数据边染成警示色(软提示,与就绪检查同源,不阻断)。
      const mismatch =
        edge.source_output &&
        edge.target_input &&
        !typesCompatible(
          outputType(nodeType.get(edge.source) ?? "", edge.source_output),
          inputType(nodeType.get(edge.target) ?? "", edge.target_input),
        );
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.source_output ? `out:${edge.source_output}` : undefined,
        targetHandle: edge.target_input ? `in:${edge.target_input}` : undefined,
        className: mismatch ? "wf-edge-data wf-edge-mismatch" : "wf-edge-data",
        animated: true,
        markerEnd: undefined,
        data: { kind: "data" },
      };
    }
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.source_handle ?? undefined,
      label: edge.source_handle === "true" ? "真" : edge.source_handle === "false" ? "假" : undefined,
      className: edge.source_handle ? `wf-edge-${edge.source_handle}` : undefined,
    };
  });
}

/** issue code → 本地化文案(角标 tooltip / checklist 行都用它)。 */
function issueText(t: ReturnType<typeof useI18n>, issue: NodeIssue): string {
  switch (issue.code) {
    case "missing-start":
      return t("wfIssueMissingStart");
    case "required-missing":
      // 显示界面上真实出现的名字。原始 key(provider / json_schema)对用户没有意义,
      // 尤其是它在面板上根本不叫这个名字的时候。
      return t("wfIssueRequired").replace(
        "{k}",
        issue.nodeType === "ai_generate" && issue.configKey === "model"
          ? t("wfGenModel")
          : issue.configKey && FIELD_LABEL_KEYS[issue.configKey]
            ? t(FIELD_LABEL_KEYS[issue.configKey])
            : (issue.configKey ?? ""),
      );
    case "stale-var":
      return t("wfIssueStaleVar").replace("{ref}", issue.ref ?? "");
    case "disconnected":
      return t("wfIssueDisconnected");
    case "no-providers":
      return t("wfIssueNoProviders");
    case "provider-missing":
      return t("wfIssueProviderMissing");
    case "gen-provider-unconfigured":
      return t("wfIssueGenUnconfigured");
    case "type-mismatch":
      return t("wfIssueTypeMismatch")
        .replace("{expected}", typeName(t, issue.expected))
        .replace("{actual}", typeName(t, issue.actual));
    default:
      return issue.code;
  }
}

/** DataType → 本地化名。 */
function typeName(t: ReturnType<typeof useI18n>, type: DataType | undefined): string {
  const key = `wfType_${type ?? "any"}` as MessageKey;
  return t(key);
}

/** 通用「插件工具」节点的类型 id。装了插件之后它就从面板上撤掉 —— 见 useNodePicker。 */
const GENERIC_PLUGIN_NODE = "plugin_tool";

/**
 * 「添加节点」面板的选项。
 *
 * 插件节点跟内置节点走的是**同一份** /api/workflows/node-types —— 它们在这里没有任何特殊
 * 处理,因为在画布上它们本来就不该有区别:同样的表单、同样的输入输出、同样的校验。前端不
 * 认识"插件"这个概念,是这件事做对了的标志。
 *
 * 这里只剩一条与插件有关的规则:装了插件之后,那行泛泛的「插件工具」从面板上撤掉。它能做的
 * 每一件事都已经被具体条目覆盖,留着只是多一个"选完还要在检查器里再选两次"的入口。
 */
function useNodePicker(nodeTypes: WorkflowNodeType[], t: ReturnType<typeof useI18n>) {
  const options = React.useMemo(() => {
    const hasPluginNodes = nodeTypes.some((meta) => meta.type.startsWith("plugin."));
    return nodeTypes
      .filter((meta) => !(hasPluginNodes && meta.type === GENERIC_PLUGIN_NODE))
      .map((meta) => ({
        value: meta.type,
        label: meta.label,
        // 同名工具可能来自不同插件(两个平台的 fetch_one_video),副标题点名是谁提供的。
        description: meta.plugin_name ? `${meta.plugin_name} · ${meta.description}` : meta.description,
        group: meta.category || t("wfNodeGroupOther"),
      }));
  }, [nodeTypes, t]);

  return { options };
}

function WorkflowEditor({
  workflow,
  nodeTypes,
  workspaceId,
}: {
  workflow: Workflow;
  nodeTypes: WorkflowNodeType[];
  workspaceId: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const registry = React.useMemo(() => new Map(nodeTypes.map((item) => [item.type, item])), [nodeTypes]);
  const { options: nodeOptions } = useNodePicker(nodeTypes, t);

  // graph 是唯一事实(configs/names);放进 zustand+zundo store 拿撤销/重做,React Flow 只管几何与选中。
  // 每个 WorkflowEditor 一个 store(按 workflow.id 重挂),历史不跨工作流。
  const graphStoreRef = React.useRef<ReturnType<typeof createWorkflowGraphStore> | null>(null);
  if (graphStoreRef.current === null) {
    graphStoreRef.current = createWorkflowGraphStore(structuredClone(workflow.graph as unknown as WorkflowGraph));
  }
  const graphStore = graphStoreRef.current;
  const graph = useStore(graphStore, (s) => s.graph);
  const graphHasStart = graph.nodes.some((node) => node.type === "start");
  const setGraph = useStore(graphStore, (s) => s.setGraph);
  const canUndo = useStore(graphStore.temporal, (s) => s.pastStates.length > 0);
  const canRedo = useStore(graphStore.temporal, (s) => s.futureStates.length > 0);
  const [nodes, setNodes] = React.useState<Node[]>(() => toFlowNodes(workflow.graph as unknown as WorkflowGraph, registry));
  const [edges, setEdges] = React.useState<Edge[]>(() => toFlowEdges(workflow.graph as unknown as WorkflowGraph));
  const [dirty, setDirty] = React.useState(false);
  const [showHistory, setShowHistory] = React.useState(false);

  // 撤销/重做:temporal 改的是 store.graph,再从新 graph 重建 React Flow 的 nodes/edges。
  const syncFromGraph = React.useCallback(() => {
    const next = graphStore.getState().graph;
    setNodes(toFlowNodes(next, registry));
    setEdges(toFlowEdges(next));
    setDirty(true);
  }, [graphStore, registry]);
  const undo = React.useCallback(() => {
    if (graphStore.temporal.getState().pastStates.length === 0) return;
    graphStore.temporal.getState().undo();
    syncFromGraph();
  }, [graphStore, syncFromGraph]);
  const redo = React.useCallback(() => {
    if (graphStore.temporal.getState().futureStates.length === 0) return;
    graphStore.temporal.getState().redo();
    syncFromGraph();
  }, [graphStore, syncFromGraph]);

  // Cmd/Ctrl+Z 撤销,Cmd+Shift+Z / Ctrl+Y 重做;输入框 / 代码编辑器(contenteditable)内不劫持。
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        undo();
      } else if ((key === "z" && event.shiftKey) || key === "y") {
        event.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);
  const [selectedNodeId, setSelectedNodeId] = React.useState<string | null>(null);
  const [renaming, setRenaming] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  // 默认关闭:进工作流页是来看画布的,助手默认占掉右侧近一半、把节点挤到看不见。
  // 需要时点顶栏「AI 助手」;开关状态记住,下次进来照旧。
  const [agentOpen, setAgentOpen] = React.useState(() => localStorage.getItem(AGENT_PANEL_KEY) === "1");
  React.useEffect(() => {
    localStorage.setItem(AGENT_PANEL_KEY, agentOpen ? "1" : "0");
  }, [agentOpen]);
  const [agentMode, setAgentMode] = React.useState<WorkflowAgentMode>("docked");
  /** 执行历史与助手同一套停靠/悬浮机制,但各记各的模式与几何。 */
  const [historyMode, setHistoryMode] = React.useState<WorkflowAgentMode>("docked");
  const [edgeShape, setEdgeShape] = usePersistentTab<EdgeShape>("wf-edge-shape", "default", EDGE_SHAPES);
  /** 节点的手动层级。只在会话内有效,不写进图 —— 叠放是看图时的临时诉求(把被压住的那个
   *  拎出来看一眼),固化进数据会让每次调整都变成一次图变更、触发自动保存。 */
  const [nodeZ, setNodeZ] = React.useState<Record<string, number>>({});
  const [nodeSearchOpen, setNodeSearchOpen] = React.useState(false);
  const [nodeSearch, setNodeSearch] = React.useState("");
  // While a node is being dragged we pause auto-save: a mid-drag PATCH→refetch would rebuild the
  // graph and interrupt React Flow's drag. The save fires once, right after the drag settles.
  const [dragging, setDragging] = React.useState(false);
  // Drill-in: double-click a loop OR subgraph node to edit its nested body sub-graph in an overlay canvas.
  const [editingLoopId, setEditingLoopId] = React.useState<string | null>(null);
  const rfRef = React.useRef<ReactFlowInstance | null>(null);
  // 首次 fitView 前隐藏画布(挂载首帧节点在默认视口的错误位置,直接可见会闪一下)
  const [viewReady, setViewReady] = React.useState(false);
  // 贴靠面板按节点的**屏幕**位置摆放,视口一动就要重算(平移/缩放时面板跟着节点走)。
  const [viewportTick, setViewportTick] = React.useState(0);
  //  平移画布时,贴靠面板会跟着节点走 —— 一旦它滑到指针底下,浏览器会对这次手势发
  //  pointercancel,而 React Flow 的平移(d3-zoom)把 pointercancel 当作手势结束,于是画布
  //  "自己停住了"。面板在平移期间不吃指针事件就不会发生这件事;它照样跟着节点动,只是不拦。
  const [panning, setPanning] = React.useState(false);

  /**
   * 把视口居中到某坐标上。用坐标而非 getNode:新加节点此刻还没同步进 React Flow 内部 store,
   * getNode 会取空;而 setCenter 只改视口变换,不依赖节点已登记。
   *
   * 不再为「躲开右侧检查器」额外右移:配置面板已改为贴着节点浮现(见 anchorToNode),
   * 右侧不再有常驻遮挡,再偏移反而把节点推离视觉中心。
   */
  const focusPosition = React.useCallback((x: number, y: number, duration = 350) => {
    const instance = rfRef.current;
    if (!instance) return;
    const zoom = Math.max(instance.getZoom(), 0.6);
    instance.setCenter(x + 210 / 2, y + 72 / 2, { zoom, duration });
  }, []);

  /** 选中并聚焦某节点(节点搜索用;从当前 graph 取坐标)。 */
  const focusNode = React.useCallback(
    (nodeId: string) => {
      const target = graph.nodes.find((node) => node.id === nodeId);
      if (!target) return;
      setSelectedNodeId(nodeId);
      focusPosition(target.position?.x ?? 0, target.position?.y ?? 0);
    },
    [graph.nodes, focusPosition],
  );

  // 智能体经确认卡改图后 updated_at 变化:画布无本地改动时自动跟进服务端版本。
  const lastSyncedRef = React.useRef(workflow.updated_at);
  // 自己保存引发的那次 refetch 不能重建画布(重建会丢掉 React Flow 的实测尺寸、造成闪烁与
  // 拖拽中断)。不靠比对 updated_at 字符串——两端序列化只要差一点就会误判。
  const selfSaveRef = React.useRef(false);
  /** 用新图重建画布节点,**保留 React Flow 的选中态**。
   *
   *  这条必须只有一处实现:重建节点的路径有两条(本地编辑走 applyGraph,服务端回传走同步
   *  effect),两条都会把 selection 冲掉。第一次只修了前者,于是"拖完节点过一会儿焦点自己没了"
   *  又冒了出来 —— 因为拖动会触发自动保存,保存回来的 updated_at 走的是后者。 */
  const rebuildNodes = React.useCallback(
    (next: WorkflowGraph) =>
      setNodes((current) => {
        const selectedIds = new Set(current.filter((node) => node.selected).map((node) => node.id));
        return toFlowNodes(next, registry).map((node) =>
          selectedIds.has(node.id) ? { ...node, selected: true } : node,
        );
      }),
    [registry],
  );

  React.useEffect(() => {
    if (workflow.updated_at === lastSyncedRef.current) return;
    if (selfSaveRef.current) {
      selfSaveRef.current = false;
      lastSyncedRef.current = workflow.updated_at;
      return;
    }
    // Only mark a revision as synced once it has actually been applied. Marking first meant an
    // agent edit arriving while the canvas was dirty was recorded as seen, never applied, and
    // then overwritten by the pending autosave — the agent's change vanished with nothing said.
    // Left unmarked, it is applied as soon as the local edit saves and `dirty` clears.
    if (!dirty) {
      lastSyncedRef.current = workflow.updated_at;
      const next = structuredClone(workflow.graph as unknown as WorkflowGraph);
      setGraph(next);
      rebuildNodes(next);
      setEdges(toFlowEdges(next));
    }
  }, [workflow.updated_at, workflow.graph, dirty, rebuildNodes]);

  const applyGraph = React.useCallback(
    (next: WorkflowGraph) => {
      setGraph(next);
      rebuildNodes(next);
      setEdges(toFlowEdges(next));
      setDirty(true);
    },
    [rebuildNodes],
  );

  // 框选 → 折叠为子图(ComfyUI 式):把选中节点收进一个 subgraph 节点,进出边界的引用/数据边自动重写。
  const handleCollapse = React.useCallback(
    (ids: string[]) => {
      const res = collapseToSubgraph(graph, ids);
      if (!res.ok) {
        const description =
          res.reason === "start"
            ? t("wfCollapseErrStart")
            : res.reason === "not-convex"
              ? t("wfCollapseErrNotConvex")
              : res.reason === "condition-branch"
                ? t("wfCollapseErrCondition")
                : t("wfCollapseErrEmpty");
        toast.error(t("wfCollapseFailed"), { description });
        return;
      }
      applyGraph(res.graph);
      setSelectedNodeId(res.subgraphId);
      setNodes((current) => current.map((node) => ({ ...node, selected: node.id === res.subgraphId })));
      toast.success(t("wfCollapseDone"));
    },
    [graph, applyGraph, t],
  );

  // 节点剪贴板(应用内,按 workflow 编辑器实例存活)。存被选中的节点 + 其内部边,
  // 粘贴时整体换新 id、内部连线原样重连、位置向右下错开。
  const clipboardRef = React.useRef<{ nodes: WorkflowGraph["nodes"]; edges: WorkflowGraph["edges"] }>({
    nodes: [],
    edges: [],
  });
  const copySelection = React.useCallback((): boolean => {
    const selectedIds = new Set(nodes.filter((node) => node.selected).map((node) => node.id));
    if (selectedIds.size === 0) return false;
    const pickedNodes = graph.nodes.filter((node) => selectedIds.has(node.id));
    // 只带上"两端都被选中"的边:整段子图连内部接线一起复制,不牵连外部节点。
    const pickedEdges = graph.edges.filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target));
    clipboardRef.current = structuredClone({ nodes: pickedNodes, edges: pickedEdges });
    return true;
  }, [nodes, graph]);
  const pasteClipboard = React.useCallback((): boolean => {
    const clip = clipboardRef.current;
    if (clip.nodes.length === 0) return false;
    const used = new Set(graph.nodes.map((node) => node.id));
    const freshId = (type: string): string => {
      const base = type.replace(/[_.]/g, "-");
      let index = 1;
      while (used.has(`${base}-${index}`)) index += 1;
      const id = `${base}-${index}`;
      used.add(id);
      return id;
    };
    const idMap = new Map<string, string>();
    const newNodes: WorkflowGraph["nodes"] = [];
    for (const node of clip.nodes) {
      if (node.type === "start") continue; // start 唯一,不复制
      const id = freshId(node.type);
      idMap.set(node.id, id);
      newNodes.push({
        ...structuredClone(node),
        id,
        position: { x: (node.position?.x ?? 0) + 48, y: (node.position?.y ?? 0) + 48 },
      });
    }
    if (newNodes.length === 0) return false;
    const newEdges = clip.edges
      .filter((edge) => idMap.has(edge.source) && idMap.has(edge.target))
      .map((edge) => {
        const source = idMap.get(edge.source)!;
        const target = idMap.get(edge.target)!;
        const id =
          edge.kind === "data"
            ? `d-${source}-${edge.source_output}-${target}-${edge.target_input}`
            : `e-${source}${edge.source_handle ? `-${edge.source_handle}` : ""}-${target}`;
        return { ...structuredClone(edge), id, source, target };
      });
    const next: WorkflowGraph = {
      ...graph,
      nodes: [...graph.nodes, ...newNodes],
      edges: [...graph.edges, ...newEdges],
    };
    // 让下次 Cmd+V 继续向右下错开,避免层层重叠。
    clipboardRef.current = structuredClone({
      nodes: clip.nodes.map((node) => ({
        ...node,
        position: { x: (node.position?.x ?? 0) + 48, y: (node.position?.y ?? 0) + 48 },
      })),
      edges: clip.edges,
    });
    setGraph(next);
    const pastedIds = new Set(newNodes.map((node) => node.id));
    // 只让粘贴出来的新节点选中(旧选区取消),方便立刻整体拖走。
    setNodes(toFlowNodes(next, registry).map((node) => ({ ...node, selected: pastedIds.has(node.id) })));
    setEdges(toFlowEdges(next));
    setDirty(true);
    setSelectedNodeId(newNodes[0].id);
    return true;
  }, [graph, registry]);

  // Cmd/Ctrl+C 复制选中节点,Cmd/Ctrl+V 粘贴;输入框 / 代码编辑器里不劫持(交给系统复制粘贴)。
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const key = event.key.toLowerCase();
      if (key === "c") {
        if (copySelection()) event.preventDefault();
      } else if (key === "v") {
        if (pasteClipboard()) event.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [copySelection, pasteClipboard]);

  const onNodesChange = React.useCallback(
    (changes: NodeChange[]) => {
      setNodes((current) => applyNodeChanges(changes, current));
      // 拖拽会连发几十次 position;声明 coalesce,让这一串在历史里塌成一条(存的是拖之前的
      // 图)。删除是离散操作,不合并 —— 连删两个节点该能分别撤销。
      const dragging = changes.some((change) => change.type === "position");
      // 位置/删除同步回 graph
      setGraph((current) => {
        let next = current;
        for (const change of changes) {
          if (change.type === "position" && change.position) {
            next = {
              ...next,
              nodes: next.nodes.map((node) =>
                node.id === change.id ? { ...node, position: { x: change.position!.x, y: change.position!.y } } : node,
              ),
            };
          } else if (change.type === "remove") {
            next = {
              ...next,
              nodes: next.nodes.filter((node) => node.id !== change.id),
              edges: next.edges.filter((edge) => edge.source !== change.id && edge.target !== change.id),
            };
          }
        }
        if (next !== current) setDirty(true);
        return next;
      }, { coalesce: dragging });
    },
    [],
  );

  const onEdgesChange = React.useCallback((changes: EdgeChange[]) => {
    setEdges((current) => applyEdgeChanges(changes, current));
    setGraph((current) => {
      let next = current;
      for (const change of changes) {
        if (change.type === "remove") {
          next = { ...next, edges: next.edges.filter((edge) => edge.id !== change.id) };
        }
      }
      if (next !== current) setDirty(true);
      return next;
    });
  }, []);

  const onConnect = React.useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const srcHandle = connection.sourceHandle ?? undefined;
      const tgtHandle = connection.targetHandle ?? undefined;
      // 数据边:输出接点 out:x → 输入接点 in:y。一个输入只接一条数据边;连上后清字面量交给数据边供值。
      if (srcHandle?.startsWith("out:") && tgtHandle?.startsWith("in:")) {
        const output = srcHandle.slice(4);
        const targetInput = tgtHandle.slice(3);
        const id = `d-${connection.source}-${output}-${connection.target}-${targetInput}`;
        setGraph((current) => {
          const kept = current.edges.filter(
            (edge) => !(edge.kind === "data" && edge.target === connection.target && edge.target_input === targetInput),
          );
          const next: WorkflowGraph = {
            ...current,
            edges: [
              ...kept,
              {
                id,
                source: connection.source!,
                target: connection.target!,
                kind: "data",
                source_output: output,
                target_input: targetInput,
              },
            ],
            nodes: current.nodes.map((node) =>
              node.id === connection.target
                ? {
                    ...node,
                    inputs: Array.from(new Set([...(node.inputs ?? []), targetInput])),
                    config: { ...(node.config ?? {}), [targetInput]: "" },
                  }
                : node,
            ),
          };
          setNodes(toFlowNodes(next, registry));
          setEdges(toFlowEdges(next));
          return next;
        });
        setDirty(true);
        return;
      }
      // 控制边:节点 → 节点(条件分支带 handle)。
      const id = `e-${connection.source}${srcHandle ? `-${srcHandle}` : ""}-${connection.target}`;
      setGraph((current) => {
        if (current.edges.some((edge) => edge.id === id)) return current;
        const next: WorkflowGraph = {
          ...current,
          edges: [
            ...current.edges,
            { id, source: connection.source!, target: connection.target!, source_handle: srcHandle ?? null },
          ],
        };
        setEdges(toFlowEdges(next));
        return next;
      });
      setDirty(true);
    },
    [registry],
  );

  // 连线合法性:禁自环、禁重复、禁成环(拖到一半就给出红色反馈)。
  const isValidConnection = React.useCallback(
    (connection: Connection | Edge) => {
      const source = connection.source ?? "";
      const target = connection.target ?? "";
      if (!source || !target || source === target) return false;
      const srcHandle = ("sourceHandle" in connection ? connection.sourceHandle : undefined) ?? undefined;
      const tgtHandle = ("targetHandle" in connection ? connection.targetHandle : undefined) ?? undefined;
      // 查重按边的种类分开(见 connections.ts):数据边不存 source_handle,若和控制边混比,
      // 「先连属性再连顺序」会把已有数据边误判成重复而拒掉控制边。数据边去重交给 onConnect 替换。
      if (!isDataConnection(srcHandle, tgtHandle) && isDuplicateControlEdge(graph.edges, source, target, srcHandle)) {
        return false;
      }
      // 从 target 出发能走回 source 即成环
      const adjacency = new Map<string, string[]>();
      for (const edge of graph.edges) {
        adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
      }
      const queue = [target];
      const seen = new Set<string>();
      while (queue.length) {
        const current = queue.pop()!;
        if (current === source) return false;
        if (seen.has(current)) continue;
        seen.add(current);
        queue.push(...(adjacency.get(current) ?? []));
      }
      return true;
    },
    [graph.edges],
  );

  const addNode = (type: string) => {
    const meta = registry.get(type);
    if (!meta) return;
    if (type === "start" && graph.nodes.some((node) => node.type === "start")) return;
    const base = type.replace(/[_.]/g, "-");
    let index = 1;
    while (graph.nodes.some((node) => node.id === `${base}-${index}`)) index += 1;
    const id = type === "start" && !graph.nodes.some((node) => node.id === "start") ? "start" : `${base}-${index}`;
    const maxX = Math.max(0, ...graph.nodes.map((node) => node.position?.x ?? 0));
    const config: Record<string, unknown> = {};
    for (const [key, spec] of Object.entries(meta.config as Record<string, { type?: string }>)) {
      // "graph"(循环体子图)必须种成空图,种成 "" 会让子画布打开时 body.nodes.length 崩掉。
      config[key] = spec?.type === "object" ? {} : spec?.type === "graph" ? { nodes: [], edges: [] } : "";
    }
    const position = { x: maxX + 240, y: 140 + (graph.nodes.length % 3) * 90 };
    const next: WorkflowGraph = {
      ...graph,
      nodes: [...graph.nodes, { id, type, name: meta.label, position, config }],
    };
    applyGraph(next);
    setSelectedNodeId(id);
    // 新节点排在最右、又会被右侧检查器盖住 → 加完把视口聚焦过去,别让人找不到。
    // 延后两帧 + 瞬时定位(duration 0):applyGraph 会替换整份节点数组触发重挂重测量,
    // 期间的重渲染会打断 setCenter 的 d3 过渡(动画停在起点=看似没动);瞬时定位无过渡可打断,
    // 一旦落定就不会被后续重渲染重置。
    requestAnimationFrame(() => requestAnimationFrame(() => focusPosition(position.x, position.y, 0)));
  };

  const save = useMutation({
    mutationFn: () => updateWorkflow(workflow.id, { graph }),
    onSuccess: (saved) => {
      setDirty(false);
      // Our own save bumps updated_at. Record it as "already synced" so the sync-from-server
      // effect below treats the imminent refetch as our own change and does NOT rebuild the
      // React Flow nodes array. A rebuild drops React Flow's measured dimensions, which re-hides
      // nodes for a frame (visibility:hidden) — during that window a node grab lands on the pane
      // and pans the canvas instead of dragging the node. With auto-save firing after every edit,
      // that window recurred constantly and made nodes feel undraggable.
      lastSyncedRef.current = saved.updated_at;
      selfSaveRef.current = true; // 兜底:即便两端 updated_at 序列化不一致也不重建画布
      void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
    },
    onError: (error: Error) => toast.error(t("wfSaveFailed"), { description: error.message }),
  });
  // Real-time save (Dify-style): debounce-save the graph whenever it changes, so there's no
  // manual "save" step. A save clears `dirty`; a rapid edit reschedules the pending save.
  const saveRef = React.useRef(save);
  saveRef.current = save;
  // Whether a save is still owed, read by the unmount flush below. A ref, not state, because
  // the cleanup that reads it runs after the last render.
  const pendingSaveRef = React.useRef(false);
  pendingSaveRef.current = dirty;

  React.useEffect(() => {
    if (!dirty || dragging) return;
    const id = window.setTimeout(() => saveRef.current.mutate(), 700);
    return () => window.clearTimeout(id);
  }, [dirty, graph, dragging]);

  // Flush on the way out. The debounce timer is cleared by its own cleanup, so editing a node
  // and then switching workflow, leaving the view, or closing the window inside 700ms threw the
  // edit away — and the 5s poll then repainted the canvas from the server's older graph, so it
  // looked as though the change had undone itself. This editor is keyed by workflow id, so
  // switching workflows unmounts it and is the common way to hit that.
  React.useEffect(() => {
    const flush = () => {
      if (pendingSaveRef.current) saveRef.current.mutate();
    };
    window.addEventListener("beforeunload", flush);
    return () => {
      window.removeEventListener("beforeunload", flush);
      flush();
    };
  }, []);
  const rename = useMutation({
    mutationFn: (name: string) => updateWorkflow(workflow.id, { name }),
    onSuccess: () => {
      setRenaming(false);
      void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteWorkflow(workflow.id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] }),
  });
  /** 本次运行的 job。留着是为了在画布上实时标状态 —— 运行完不清,方便回看这次跑成什么样;
   *  再次运行或切换工作流时被顶掉。 */
  const [runJobId, setRunJobId] = React.useState<string | null>(null);
  React.useEffect(() => setRunJobId(null), [workflow.id]);
  const runEvents = useQuery({
    queryKey: ["job-events", runJobId],
    queryFn: () => listJobEvents(runJobId ?? ""),
    enabled: Boolean(runJobId),
    // 窗口没聚焦也要继续轮询:把应用放在一边看着工作流跑是常态,默认行为会暂停轮询,
    // 于是回头一看画布还停在半小时前的那一步。
    refetchIntervalInBackground: true,
    // 跑动时勤快些,结束后停下来。判据是「有没有收尾事件」而不是 job 状态:
    // 后者要等整条流程收尾,中间那段画布就不动了。
    refetchInterval: (q) => {
      const list = (q.state.data as TaskEvent[] | undefined) ?? [];
      const done = list.some((e) => e.type === "workflow.finished" || e.type === "workflow.failed");
      return done ? false : 800;
    },
  });
  const runByNode = React.useMemo(() => stepsByNode(runEvents.data ?? []), [runEvents.data]);
  const run = useMutation({
    mutationFn: () => runWorkflow(workflow.id),
    onSuccess: (job) => {
      setRunJobId(job.id);
      toast.success(t("wfRunQueued"));
      void qc.invalidateQueries({ queryKey: ["workflow-runs", workflow.id] });
    },
    onError: (error: Error) => toast.error(t("wfRunFailed"), { description: error.message }),
  });
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? null;
  // 拖动时收起(跟着抖没有意义,还挡住落点),松手后 dragging 转 false 自然复现。
  // viewportTick / graph 变化都要重算:前者是平移缩放,后者是节点位置被改。
  const anchor = React.useMemo(
    () =>
      dragging
        ? null
        : anchorToNode(rfRef.current, nodes.find((node) => node.id === selectedNodeId) ?? null, {
            width: window.innerWidth,
            height: window.innerHeight,
          }),
    // nodes 而不是 graph:位置要和画布上真正画出来的那个节点一致。viewportTick 管平移缩放。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedNodeId, dragging, viewportTick, nodes],
  );
  // 框选中的节点(≥2 才给「折叠为子图」入口),从 React Flow 的 selected 态直接派生。
  const selectedFlowIds = nodes.filter((node) => node.selected).map((node) => node.id);

  // 就绪度分析:模型/密钥信号在编辑器层拉取(与属性面板共用 queryKey,自动去重),
  // 供画布角标 + 运行前 checklist。只有图里真有对应节点才请求。
  const hasLlm = graph.nodes.some((node) => node.type === "llm");
  const hasGen = graph.nodes.some((node) => node.type === "ai_generate");
  const providers = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () =>
      api<Array<{ id: string; name: string; vendor: string; capability_ids: string[]; enabled: boolean }>>(
        "/api/settings/providers",
      ),
    enabled: hasLlm || hasGen,
  });
  const analysis = React.useMemo(
    () =>
      analyzeWorkflow(graph, registry, {
        providerIds: new Set((providers.data ?? []).map((p) => p.id)),
        providersLoaded: (!hasLlm && !hasGen) || providers.isSuccess,
        configuredGenProviders: new Set(
          (providers.data ?? [])
            .filter((p) => p.enabled && (p.capability_ids ?? []).some((capability) => capability === "image" || capability === "video"))
            .map((p) => p.vendor),
        ),
        genProvidersLoaded: !hasGen || providers.isSuccess,
      }),
    [graph, registry, providers.data, providers.isSuccess, hasLlm, hasGen],
  );
  const checklistCount = analysis.errorCount + analysis.warnCount;
  const checklistLabel = analysis.errorCount
    ? t("wfChecklistBlocked").replace("{n}", String(analysis.errorCount))
    : analysis.warnCount
      ? t("wfChecklistWarnOnly").replace("{n}", String(analysis.warnCount))
      : t("wfChecklistReady");
  // 角标信息塞进节点 data(不动 nodes 状态本身,避免打断拖拽)。
  /** 本次运行真正走过的边:两端都留下了步骤记录。条件分支没走的那一侧因此保持原样 ——
   *  这正是运行时最想一眼看清的东西。 */
  const dockedAgent = agentOpen && agentMode === "docked";
  /** 右栏里停靠着几个面板(助手 / 执行历史)。0 就不开这一列。 */
  const dockedHistory = showHistory && historyMode === "docked";
  const agentPanel = (
    <WorkflowAgentChat
      workflowId={workflow.id}
      workflowName={workflow.name}
      workspaceId={workflow.workspace_id}
      mode={agentMode}
      onModeChange={setAgentMode}
      onClose={() => setAgentOpen(false)}
    />
  );
  const historyPanel = (
    <WorkflowRunHistory
      workflowId={workflow.id}
      // 历史面板据此判断某一步的输出是不是素材(节点注册表里声明为 asset),
      // 是就渲染成缩略图/播放器而不是一串裸 id。
      nodeTypeById={Object.fromEntries(graph.nodes.map((n) => [n.id, n.type]))}
      mode={historyMode}
      onModeChange={setHistoryMode}
      onClose={() => setShowHistory(false)}
    />
  );
  const rightPanels = (dockedAgent ? 1 : 0) + (dockedHistory ? 1 : 0);

  const displayEdges = React.useMemo(() => {
    // type 显式写到每条边上,而不是只靠 defaultEdgeOptions —— 后者的语义是"新建边的默认值",
    // 指望它去改已存在的边是碰运气。
    const shaped = edges.map((edge) => (edge.type === edgeShape ? edge : { ...edge, type: edgeShape }));
    if (Object.keys(runByNode).length === 0) return shaped;
    return shaped.map((edge) => {
      const from = runByNode[edge.source];
      const to = runByNode[edge.target];
      const taken = from && to && from.status !== "skipped" && to.status !== "skipped";
      // 描边直接给 style:Tailwind 的任意变体要和既有的 wf-edge-* 规则抢优先级,
      // 而 React Flow 本来就支持按边给样式,确定性更高。
      return taken
        ? {
            ...edge,
            className: `${edge.className ?? ""} wf-edge-taken`.trim(),
            style: { ...(edge.style ?? {}), stroke: "#3fb950", strokeWidth: 2.4 },
          }
        : edge;
    });
  }, [edges, runByNode, edgeShape]);

  /**
   * Cmd/Ctrl+] 把选中节点提到最前、[ 压到最后。与悬浮窗、剪辑页片段同键同义。
   *
   * **夹在 ±900 而不是无穷**:React Flow 的 elevateNodesOnSelect 是给选中节点的 z **加** 1000
   * (实测手动置顶的选中节点是 1001、压底的是 999)。手动值只要不越过 1000,"选中的那个恒在
   * 最上面"就一直成立 —— 而选中的正是用户此刻在操作的那个,它被别人压住最说不通。
   *
   * 节点层级永远盖不过悬浮窗,这一点不靠数值保证也保证不了 —— 靠的是 .react-flow__viewport
   * 带 transform 自成层叠上下文,里面的 z 再大也只在画布内部排序。数值只管画布内部的秩序。
   */
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
      if (event.key !== "[" && event.key !== "]") return;
      // 悬浮窗握着焦点时这组键归它。点回画布(onPaneClick / onNodeClick)才交还。
      if (hasFocusedFloatingPanel()) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      const picked = nodes.filter((node) => node.selected).map((node) => node.id);
      if (picked.length === 0) return;
      event.preventDefault(); // Chromium 里这两个键是后退/前进
      setNodeZ((current) => {
        const values = Object.values(current);
        const next = { ...current };
        if (event.key === "]") {
          const top = Math.min(Math.max(0, ...values) + 1, 900);
          for (const id of picked) next[id] = top;
        } else {
          const bottom = Math.max(Math.min(0, ...values) - 1, -900);
          for (const id of picked) next[id] = bottom;
        }
        return next;
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nodes]);

  const displayNodes = React.useMemo(
    () =>
      nodes.map((node) => {
        const nodeIssues = analysis.byNode.get(node.id);
        const severity = analysis.severityByNode.get(node.id);
        const badge =
          nodeIssues && severity
            ? { severity, count: nodeIssues.length, title: nodeIssues.map((i) => issueText(t, i)).join("\n") }
            : null;
        const step = runByNode[node.id];
        return {
          ...node,
          zIndex: nodeZ[node.id],
          data: {
            ...node.data,
            badge,
            run: step ? { status: step.status, ms: step.ms, error: step.error } : null,
            runAssets: step?.outputs ? assetOutputs(node.data.nodeType as string, step.outputs) : [],
          },
        };
      }),
    [nodes, analysis, t, runByNode, nodeZ],
  );

  return (
    <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2.5 px-0.5 pb-2 pt-0.5">
        <button type="button" className="inline-flex cursor-pointer items-center gap-[9px] rounded-md border-0 bg-transparent py-[3px] pl-[3px] pr-1.5 text-left text-foreground hover:bg-secondary" onClick={() => setRenaming(true)} title={t("rename")}>
          <span className="grid h-7 w-7 place-items-center rounded-md bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary">
            <WorkflowIcon size={14} />
          </span>
          <span className="grid leading-[1.3] [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:text-[13px]">
            <strong>{workflow.name}</strong>
            {/* 保存状态只放工具栏的 wf-save-status:标题里再挂一行「未保存」会随每次
                拖动→自动保存增删一行,撑动整条工具栏导致画布跳一下(闪烁)。 */}
          </span>
        </button>
        <div className="flex flex-wrap items-center gap-1.5">
          {/* 工具条统一刻度:胶囊(rounded-full)、h-8、text-xs;图标钮 h-8 w-8。 */}
          <SearchableSelect
            value=""
            onValueChange={addNode}
            searchPlaceholder={t("wfAddNode")}
            options={nodeOptions.filter((option) => option.value !== "start" || !graphHasStart)}
            trigger={
              <button
                type="button"
                className="flex h-8 w-auto items-center gap-1 rounded-full border border-input bg-card px-3 text-xs text-foreground hover:bg-muted"
                aria-label={t("wfAddNode")}
              >
                <Plus size={12} />
                <span>{t("wfAddNode")}</span>
              </button>
            }
          />
          <Button variant="ghost" size="icon" className="h-8 w-8" title={`${t("undo")} ⌘Z`} aria-label={t("undo")} disabled={!canUndo} onClick={undo}>
            <Undo2 size={14} />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" title={`${t("redo")} ⇧⌘Z`} aria-label={t("redo")} disabled={!canRedo} onClick={redo}>
            <Redo2 size={14} />
          </Button>
          <div className="mx-1 h-[18px] w-px bg-border" />
          <Button
            variant={agentOpen ? "secondary" : "outline"}
            size="sm"
            onClick={() => {
              setAgentOpen((value) => !value);
              if (!agentOpen) setAgentMode("docked");
            }}
          >
            <Bot size={13} /> {t("wfAgentTitle")}
          </Button>
          <Popover
            open={nodeSearchOpen}
            onOpenChange={(open) => {
              setNodeSearchOpen(open);
              if (!open) setNodeSearch("");
            }}
          >
            <PopoverTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground" aria-label={t("wfNodeSearch")} title={t("wfNodeSearch")}>
                <Search size={14} />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-[280px] p-1.5">
              {/* 单层输入框 + 内置图标(与素材搜索同款):此前外壳自带边框、内层 Input
                  又画自己的边框和焦点环,聚焦时两层框套着一枚游离的放大镜。 */}
              <div className="relative">
                <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  autoFocus
                  className="h-8 pl-[30px] pr-2 text-[12.5px] focus-visible:border-primary focus-visible:ring-0"
                  value={nodeSearch}
                  onChange={(event) => setNodeSearch(event.target.value)}
                  placeholder={t("wfNodeSearchPlaceholder")}
                />
              </div>
              <div className="mt-1.5 flex max-h-80 flex-col gap-0.5 overflow-auto">
                {(() => {
                  const query = nodeSearch.trim().toLowerCase();
                  const matches = graph.nodes.filter((node) => {
                    if (!query) return true;
                    const label = (registry.get(node.type)?.label ?? node.type).toLowerCase();
                    return (
                      (node.name || "").toLowerCase().includes(query) ||
                      node.type.toLowerCase().includes(query) ||
                      label.includes(query)
                    );
                  });
                  if (matches.length === 0)
                    return <div className="px-2 py-2.5 text-center text-xs text-muted-foreground">{t("wfNodeSearchEmpty")}</div>;
                  return matches.map((node) => {
                    const label = registry.get(node.type)?.label ?? node.type;
                    // 未改名时 name 就是类型标签,再补一列类型纯属重复 → 仅改过名才显示类型。
                    const typeSub = node.name && node.name !== label ? label : null;
                    return (
                      <button
                        key={node.id}
                        type="button"
                        className={cn(
                          "flex cursor-pointer items-baseline justify-between gap-2.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-left hover:bg-muted",
                          node.id === selectedNodeId && "bg-accent hover:bg-accent",
                        )}
                        onClick={() => {
                          focusNode(node.id);
                          setNodeSearchOpen(false);
                          setNodeSearch("");
                        }}
                      >
                        <span className="truncate text-[12.5px] font-semibold text-foreground">{node.name || label}</span>
                        {typeSub && <span className="shrink-0 text-[11px] text-muted-foreground">{typeSub}</span>}
                      </button>
                    );
                  });
                })()}
              </div>
            </PopoverContent>
          </Popover>
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className={cn(
                  "inline-flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-panel px-3 text-xs font-[650] text-muted-foreground transition-[background,border-color,color] duration-[120ms] hover:border-border-strong hover:text-foreground",
                  analysis.errorCount
                    ? "border-[color-mix(in_srgb,var(--destructive)_45%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_10%,var(--panel))] text-destructive hover:text-destructive"
                    : analysis.warnCount
                      ? "border-[color-mix(in_srgb,#d97706_40%,var(--border))] bg-[color-mix(in_srgb,#f59e0b_10%,var(--panel))] text-[#f59e0b] hover:text-[#f59e0b]"
                      : "border-[color-mix(in_srgb,#22c55e_30%,var(--border))] bg-[color-mix(in_srgb,#22c55e_8%,var(--panel))] text-[#22c55e] hover:text-[#22c55e]",
                )}
                aria-label={`${t("wfChecklist")}: ${checklistLabel}`}
                title={checklistLabel}
              >
                {analysis.errorCount || analysis.warnCount ? <AlertTriangle size={13} /> : <CircleCheck size={13} />}
                <span>{checklistCount > 0 ? t("wfChecklist") : t("wfChecklistReadyShort")}</span>
                {checklistCount > 0 && <em className="inline-grid h-[15px] min-w-[15px] place-items-center rounded-full border border-[color-mix(in_srgb,currentColor_35%,transparent)] bg-[color-mix(in_srgb,currentColor_14%,transparent)] px-1 text-[10px] font-bold not-italic leading-none text-current">{checklistCount}</em>}
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-1.5">
              {analysis.issues.length === 0 ? (
                <div className="flex items-center gap-1.5 p-2 text-[12.5px] text-[#16a34a]">
                  <CircleCheck size={14} /> {t("wfChecklistReady")}
                </div>
              ) : (
                <>
                  <div className="px-2 pb-1.5 pt-1 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                    {analysis.errorCount
                      ? t("wfChecklistBlocked").replace("{n}", String(analysis.errorCount))
                      : t("wfChecklistWarnOnly").replace("{n}", String(analysis.warnCount))}
                  </div>
                  <div className="flex max-h-80 flex-col gap-0.5 overflow-auto">
                    {[...analysis.issues]
                      .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1))
                      .map((issue, i) => (
                        <button
                          key={`${issue.nodeId}-${issue.code}-${i}`}
                          type="button"
                          className={cn(
                            "grid cursor-pointer grid-cols-[14px_auto_1fr] items-center gap-1.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-left hover:bg-muted",
                            issue.severity === "error" ? "[&>svg]:text-destructive" : "[&>svg]:text-[#d97706]",
                          )}
                          onClick={() => setSelectedNodeId(issue.nodeId)}
                        >
                          <AlertTriangle size={12} />
                          <span className="whitespace-nowrap text-xs font-semibold">{issue.nodeName}</span>
                          <span className="truncate text-[11.5px] text-muted-foreground">{issueText(t, issue)}</span>
                        </button>
                      ))}
                  </div>
                </>
              )}
            </PopoverContent>
          </Popover>
          {/* 不再挂「未保存/保存中」文案:自动保存本就静默,状态条只会闪来闪去制造焦虑;
              脏状态期间运行按钮自会禁用并带「保存中」提示,足够了。 */}
          <Button
            size="sm"
            disabled={dirty || !analysis.runnable} loading={run.isPending}
            title={dirty ? t("wfSaving") : !analysis.runnable ? t("wfRunBlocked") : undefined}
            onClick={() => run.mutate()}
          >
            <Play size={13} /> {t("wfRun")}
          </Button>
          <div className="mx-1 h-[18px] w-px bg-border" />
          {/* 走线方式:四种够用,直接摆成一排图标钮而不是下拉 —— 它是"试一下看哪种顺眼"的
              设置,藏进下拉就得点两次才能比较一次。 */}
          <div className="flex items-center gap-0.5 rounded-md border border-border p-0.5">
            {EDGE_SHAPES.map((shape) => {
              const Icon = EDGE_SHAPE_ICON[shape];
              return (
                <Button
                  key={shape}
                  variant={edgeShape === shape ? "secondary" : "ghost"}
                  size="icon"
                  className="h-7 w-7 rounded-[5px]"
                  aria-label={t(EDGE_SHAPE_LABEL[shape])}
                  title={t(EDGE_SHAPE_LABEL[shape])}
                  aria-pressed={edgeShape === shape}
                  onClick={() => setEdgeShape(shape)}
                >
                  <Icon size={13} />
                </Button>
              );
            })}
          </div>
          <div className="mx-1 h-[18px] w-px bg-border" />
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("wfHistory")}
            title={t("wfHistory")}
            className="h-8 w-8"
            onClick={() => setShowHistory((v) => !v)}
          >
            <History size={14} />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={t("delete")} onClick={() => setDeleting(true)}>
            <Trash2 size={14} />
          </Button>
        </div>
      </div>

      <div className={cn(
        "relative grid min-h-0 grid-cols-[minmax(0,1fr)] gap-2 [&_.react-flow\_\_background]:bg-background [&_.react-flow\_\_controls]:overflow-hidden [&_.react-flow\_\_controls]:rounded-md [&_.react-flow\_\_controls]:border [&_.react-flow\_\_controls]:border-border [&_.react-flow\_\_controls]:shadow-none [&_.react-flow\_\_controls-button]:border-b [&_.react-flow\_\_controls-button]:border-border [&_.react-flow\_\_controls-button]:bg-panel [&_.react-flow\_\_controls-button]:text-foreground [&_.react-flow\_\_controls-button:hover]:bg-secondary [&_.react-flow\_\_edge-path]:stroke-border-strong [&_.react-flow\_\_edge-path]:[stroke-width:1.5] [&_.react-flow\_\_edge-path]:[stroke-linecap:round] [&_.react-flow\_\_edge-path]:[transition:stroke_120ms,stroke-width_120ms] [&_.react-flow\_\_edge.selected_.react-flow\_\_edge-path]:stroke-primary [&_.react-flow\_\_edge.selected_.react-flow\_\_edge-path]:[stroke-width:2.2] [&_.react-flow\_\_edge:hover_.react-flow\_\_edge-path]:[stroke-width:2.2] [&_.react-flow\_\_edge-textbg]:fill-panel [&_.react-flow\_\_edge-text]:fill-muted-foreground [&_.react-flow\_\_edge-text]:text-[9.5px] [&_.react-flow\_\_attribution]:bg-transparent [&_.react-flow\_\_attribution]:text-muted-foreground [&_.wf-edge-true_.react-flow\_\_edge-path]:stroke-[#16a34a] [&_.wf-edge-false_.react-flow\_\_edge-path]:stroke-[#e11d48] [&_.wf-edge-data_.react-flow\_\_edge-path]:animate-wf-dash [&_.wf-edge-data_.react-flow\_\_edge-path]:stroke-primary [&_.wf-edge-data_.react-flow\_\_edge-path]:[stroke-width:2] [&_.wf-edge-data_.react-flow\_\_edge-path]:[stroke-dasharray:6_5] [&_.wf-edge-data.selected_.react-flow\_\_edge-path]:[stroke-width:2.6] [&_.wf-edge-data.wf-edge-mismatch_.react-flow\_\_edge-path]:stroke-[#d97706] [&_.react-flow\_\_minimap]:overflow-hidden [&_.react-flow\_\_minimap]:rounded-md [&_.react-flow\_\_minimap]:border [&_.react-flow\_\_minimap]:border-border [&_.react-flow\_\_minimap]:bg-background [&_.react-flow\_\_minimap-mask]:fill-[color-mix(in_srgb,var(--foreground)_6%,transparent)] [&_.react-flow\_\_minimap-node]:fill-border-strong",
        rightPanels > 0 && "grid-cols-[minmax(0,1fr)_minmax(360px,420px)]",
      )}>
        <div className="min-h-0 overflow-hidden rounded-lg border border-border bg-panel">
          <ReactFlow
            className={cn("[--xy-attribution-background-color:color-mix(in_srgb,var(--panel)_70%,transparent)]", !viewReady && "opacity-0")}
            nodes={displayNodes}
            edges={displayEdges}
            nodeTypes={NODE_COMPONENT_TYPES}
            onInit={(instance) => {
              rfRef.current = instance as unknown as ReactFlowInstance;
              // 只在挂载时 fit 一次(切换工作流会因 key 重挂而重跑)。用命令式而非声明式
              // fitView 属性:后者会在每次新增未测量节点时重新 fit,把手动聚焦覆盖掉。
              // fit 完成前画布不可见:首帧按默认视口渲染会让所有节点在错位处闪一下。
              requestAnimationFrame(() => {
                instance.fitView({ padding: 0.25, maxZoom: 1 });
                setViewReady(true);
              });
            }}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onMoveStart={() => setPanning(true)}
            onMove={() => setViewportTick((n) => n + 1)}
            onMoveEnd={() => setPanning(false)}
            onNodeDragStart={() => setDragging(true)}
            onNodeDragStop={() => setDragging(false)}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            connectionRadius={36}
            connectionLineType={edgeShape as ConnectionLineType}
            connectionLineStyle={{ stroke: "var(--primary)", strokeWidth: 1.5, strokeDasharray: "5 4" }}
            onNodeClick={(_event, node) => {
              blurFloatingPanels(); // 层级快捷键交还给画布
              setSelectedNodeId(node.id);
            }}
            onNodeDoubleClick={(_event, node) => {
              const g = graph.nodes.find((item) => item.id === node.id);
              if (g && (g.type === "loop_foreach" || g.type === "loop_while" || g.type === "subgraph"))
                setEditingLoopId(node.id);
            }}
            onPaneClick={() => {
              blurFloatingPanels();
              setSelectedNodeId(null);
            }}
            /* 触控板约定(Figma / Miro 那套):双指滑动 = 平移,捏合 = 缩放。
               React Flow 默认 zoomOnScroll:true,而 macOS 触控板双指滑动发出的正是 wheel 事件,
               于是「想拖画布」变成了「缩放」。捏合发的是 ctrlKey 的 wheel,归 zoomOnPinch 管,
               所以关掉 zoomOnScroll 不影响捏合;鼠标用户按住 ctrl/⌘ 滚轮同样落进这条,仍可缩放。 */
            panOnScroll
            zoomOnScroll={false}
            zoomOnPinch
          defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
            proOptions={{ hideAttribution: false }}
            deleteKeyCode={["Backspace", "Delete"]}
          >
            {selectedFlowIds.length >= 2 && (
              <Panel position="top-center">
                <button
                  type="button"
                  onClick={() => handleCollapse(selectedFlowIds)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-input bg-card px-3 py-1.5 text-xs font-medium text-foreground shadow-sm hover:bg-muted"
                  title={t("wfCollapseHint")}
                >
                  <Boxes size={13} /> {t("wfCollapseToSubgraph").replace("{n}", String(selectedFlowIds.length))}
                </button>
              </Panel>
            )}
            <Background gap={20} size={1.2} />
            {/* 缩放钮/预览图不吃应用主题(xyflow 默认一律白底),把 --xy-* 变量
                映射到设计令牌,昼夜两版都跟着色板走;投影按全局规范去掉。 */}
            <Controls
              showInteractive={false}
              position="bottom-left"
              className="overflow-hidden rounded-md border border-border [--xy-controls-box-shadow:none] [--xy-controls-button-background-color:var(--panel)] [--xy-controls-button-background-color-hover:var(--secondary)] [--xy-controls-button-border-color:var(--border)] [--xy-controls-button-color:var(--muted-foreground)] [--xy-controls-button-color-hover:var(--foreground)]"
            />
            <MiniMap
              pannable
              zoomable
              position="bottom-right"
              className="overflow-hidden rounded-md border border-border"
              bgColor="var(--panel)"
              maskColor="color-mix(in srgb, var(--background) 55%, transparent)"
              nodeColor="var(--border-strong)"
              nodeStrokeColor="transparent"
            />
          </ReactFlow>
        </div>
        {/* 右栏:助手与执行历史共用。两个都开就上下平分 —— 运行时经常要一边看画布状态、
            一边翻某一步的输出。助手切到浮动模式时自己脱离文档流,所以只按停靠中的个数分行。 */}
        {(dockedAgent || dockedHistory) && (
          <div
            className={cn(
              "grid min-h-0 min-w-0 gap-2",
              dockedAgent && dockedHistory ? "grid-rows-[minmax(0,1fr)_minmax(0,1fr)]" : "grid-rows-[minmax(0,1fr)]",
            )}
          >
            {dockedAgent && agentPanel}
            {dockedHistory && historyPanel}
          </div>
        )}
        {/* 浮动的面板不在右栏里(fixed 定位,自己脱离文档流),单独挂 —— 挂在栏内的话,
            两个都浮动时右栏根本不渲染,面板就跟着消失了。 */}
        {showHistory && !dockedHistory && historyPanel}
        {agentOpen && !dockedAgent && agentPanel}
        {editingLoopId &&
          (() => {
            const loopNode = graph.nodes.find((item) => item.id === editingLoopId);
            if (!loopNode) return null;
            return (
              <LoopBodyEditor
                loopNode={loopNode}
                registry={registry}
                nodeTypes={nodeTypes}
                workspaceId={workspaceId}
                onChange={(body) =>
                  applyGraph({
                    ...graph,
                    nodes: graph.nodes.map((item) =>
                      item.id === editingLoopId ? { ...item, config: { ...(item.config ?? {}), body } } : item,
                    ),
                  })
                }
                onClose={() => setEditingLoopId(null)}
              />
            );
          })()}
        {/* 钻进循环体时不渲染外层检查器:它和覆盖层同为 z-index:30 且在 DOM 里更靠后,会盖住
            子画布头部(返回/面包屑/添加节点)。子画布有自己的检查器;外层节点回主流程再编辑。 */}
        {selectedNode && !editingLoopId && anchor && (
          <NodeInspector
            anchor={anchor}
            inert={panning}
            node={selectedNode}
            meta={registry.get(selectedNode.type) ?? null}
            graph={graph}
            registry={registry}
            workspaceId={workspaceId}
            onChange={(patch) => {
              applyGraph({
                ...graph,
                nodes: graph.nodes.map((node) => (node.id === selectedNode.id ? { ...node, ...patch } : node)),
              });
            }}
            onApplyGraph={applyGraph}
            onDelete={() => {
              applyGraph({
                ...graph,
                nodes: graph.nodes.filter((node) => node.id !== selectedNode.id),
                edges: graph.edges.filter(
                  (edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id,
                ),
              });
              setSelectedNodeId(null);
            }}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </div>

      <RenameDialog
        open={renaming}
        title={t("rename")}
        initialValue={workflow.name}
        onCancel={() => setRenaming(false)}
        onSubmit={(name) => rename.mutate(name)}
      />
      <ConfirmDialog
        open={deleting}
        title={t("deleteConfirmTitle")}
        body={t("wfDeleteBody")}
        onCancel={() => setDeleting(false)}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}

interface ConfigSpec {
  type?: string;
  description?: string;
  required?: boolean;
  options?: string[];
  /** 后端声明的默认值,拿来做占位提示(告诉用户"留空会用什么")。 */
  default?: string;
  /** 留空也能跑的专业旋钮 —— 收进折叠的「高级选项」,不在第一眼糊到用户脸上。 */
  advanced?: boolean;
}

/** 选中节点的所有上游变量(祖先节点输出 + start 参数),供插入器使用。 */
function upstreamVariables(
  graph: WorkflowGraph,
  nodeId: string,
  registry: Map<string, WorkflowNodeType>,
): string[] {
  const parents = new Map<string, string[]>();
  for (const edge of graph.edges) {
    parents.set(edge.target, [...(parents.get(edge.target) ?? []), edge.source]);
  }
  const ancestors = new Set<string>();
  const queue = [...(parents.get(nodeId) ?? [])];
  while (queue.length) {
    const current = queue.pop()!;
    if (ancestors.has(current)) continue;
    ancestors.add(current);
    queue.push(...(parents.get(current) ?? []));
  }
  const refs: string[] = [];
  for (const node of graph.nodes) {
    if (!ancestors.has(node.id)) continue;
    if (node.type === "start") {
      const params = ((node.config as { params?: Record<string, unknown> })?.params ?? {}) as object;
      for (const key of Object.keys(params)) refs.push(`{{${node.id}.${key}}}`);
    } else {
      for (const output of registry.get(node.type)?.outputs ?? []) refs.push(`{{${node.id}.${output}}}`);
    }
  }
  return refs;
}

/** object(JSON)字段:CodeMirror JSON 编辑,失焦解析回对象;非法给提示不写入。 */
function JsonField({ value, onChange }: { value: unknown; onChange: (parsed: unknown) => void }) {
  const t = useI18n();
  const [text, setText] = React.useState(() => JSON.stringify(value ?? {}, null, 2));
  // 上游(智能体改图)更新时回显,但不打断正在输入:仅当序列化值真变才重置。
  const synced = React.useRef(text);
  React.useEffect(() => {
    const next = JSON.stringify(value ?? {}, null, 2);
    if (next !== synced.current) {
      synced.current = next;
      setText(next);
    }
  }, [value]);
  return (
    <CodeEditor
      value={text}
      language="json"
      minHeight={34}
      gutter={false}
      onChange={setText}
      onBlur={() => {
        try {
          const parsed = JSON.parse(text || "{}");
          synced.current = JSON.stringify(parsed ?? {}, null, 2);
          onChange(parsed);
        } catch {
          toast.error(t("wfBadJson"));
        }
      }}
    />
  );
}

/** code 字段:CodeMirror Python + 上游变量 chip(插到光标处)。 */
function CodeField({
  value,
  onChange,
  variables,
}: {
  value: string;
  onChange: (value: string) => void;
  variables: string[];
}) {
  const t = useI18n();
  const handle = React.useRef<CodeEditorHandle>(null);
  return (
    <>
      <CodeEditor ref={handle} value={value} language="python" minHeight={140} onChange={onChange} />
      {variables.length > 0 && (
        <div className="flex flex-wrap gap-[3px]">
          {variables.map((ref) => (
            <button
              key={ref}
              type="button"
              className="cursor-pointer rounded-md border border-border bg-[color-mix(in_srgb,var(--primary)_6%,transparent)] px-1.5 py-px font-mono text-[10px] text-primary transition-[border-color,background] duration-100 hover:border-primary hover:bg-[color-mix(in_srgb,var(--primary)_12%,transparent)]"
              title={t("wfInsertVar")}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => handle.current?.insertAtCursor(ref)}
            >
              {ref.replace(/[{}]/g, "")}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

/** Dify 式节点属性浮层:枚举字段用 Select,模板字段带上游变量插入器。 */
/** Drill-in editor for a loop / subgraph node's nested `body` sub-graph (Dify / ComfyUI-style).
 *  A self-contained mini-canvas: add/connect/move/delete/config body nodes; changes flow up via
 *  onChange. Header/hints switch on the node type (loop scope {{loop.*}} vs subgraph {{input.*}}). */
function LoopBodyEditor({
  loopNode,
  registry,
  nodeTypes,
  workspaceId,
  onChange,
  onClose,
}: {
  loopNode: WorkflowGraph["nodes"][number];
  registry: Map<string, WorkflowNodeType>;
  nodeTypes: WorkflowNodeType[];
  workspaceId: string;
  onChange: (body: WorkflowGraph) => void;
  onClose: () => void;
}) {
  const t = useI18n();
  const { options: subOptions } = useNodePicker(nodeTypes, t);
  const [bodyViewReady, setBodyViewReady] = React.useState(false);
  // config.body may be missing, or "" (addNode seeds unknown field types with an empty string) —
  // anything not shaped like a graph must become an empty one, or body.nodes.length blows up the
  // whole app on open.
  const initialBody = React.useMemo<WorkflowGraph>(() => {
    const raw = loopNode.config?.body as unknown;
    return raw && typeof raw === "object" && Array.isArray((raw as WorkflowGraph).nodes)
      ? (raw as WorkflowGraph)
      : { nodes: [], edges: [] };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seed once; body state owns it after
  }, []);
  const [body, setBody] = React.useState<WorkflowGraph>(() => structuredClone(initialBody));
  const [nodes, setNodes] = React.useState<Node[]>(() => toFlowNodes(initialBody, registry));
  const [edges, setEdges] = React.useState<Edge[]>(() => toFlowEdges(initialBody));
  // 循环体编辑器读同一个偏好:主画布是圆角折线、点进循环体却变回贝塞尔,会让人以为进错了地方。
  const [edgeShape] = usePersistentTab<EdgeShape>("wf-edge-shape", "default", EDGE_SHAPES);
  const shapedEdges = React.useMemo(
    () => edges.map((edge) => (edge.type === edgeShape ? edge : { ...edge, type: edgeShape })),
    [edges, edgeShape],
  );
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const commit = React.useCallback(
    (next: WorkflowGraph) => {
      setBody(next);
      setNodes(toFlowNodes(next, registry));
      setEdges(toFlowEdges(next));
      onChange(next);
    },
    [registry, onChange],
  );

  const onNodesChange = React.useCallback(
    (changes: NodeChange[]) => {
      setNodes((current) => applyNodeChanges(changes, current));
      setBody((current) => {
        let next = current;
        for (const change of changes) {
          if (change.type === "position" && change.position) {
            next = {
              ...next,
              nodes: next.nodes.map((node) =>
                node.id === change.id ? { ...node, position: { x: change.position!.x, y: change.position!.y } } : node,
              ),
            };
          } else if (change.type === "remove") {
            next = {
              ...next,
              nodes: next.nodes.filter((node) => node.id !== change.id),
              edges: next.edges.filter((edge) => edge.source !== change.id && edge.target !== change.id),
            };
          }
        }
        if (next !== current) onChange(next);
        return next;
      });
    },
    [onChange],
  );

  const onEdgesChange = React.useCallback(
    (changes: EdgeChange[]) => {
      setEdges((current) => applyEdgeChanges(changes, current));
      setBody((current) => {
        let next = current;
        for (const change of changes) {
          if (change.type === "remove") next = { ...next, edges: next.edges.filter((edge) => edge.id !== change.id) };
        }
        if (next !== current) onChange(next);
        return next;
      });
    },
    [onChange],
  );

  const onConnect = React.useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const srcHandle = connection.sourceHandle ?? undefined;
      const tgtHandle = connection.targetHandle ?? undefined;
      let next: WorkflowGraph;
      if (srcHandle?.startsWith("out:") && tgtHandle?.startsWith("in:")) {
        const output = srcHandle.slice(4);
        const targetInput = tgtHandle.slice(3);
        const kept = body.edges.filter(
          (edge) => !(edge.kind === "data" && edge.target === connection.target && edge.target_input === targetInput),
        );
        next = {
          ...body,
          edges: [
            ...kept,
            { id: `d-${connection.source}-${output}-${connection.target}-${targetInput}`, source: connection.source, target: connection.target, kind: "data", source_output: output, target_input: targetInput },
          ],
          nodes: body.nodes.map((node) =>
            node.id === connection.target
              ? { ...node, inputs: Array.from(new Set([...(node.inputs ?? []), targetInput])), config: { ...(node.config ?? {}), [targetInput]: "" } }
              : node,
          ),
        };
      } else {
        const id = `e-${connection.source}${srcHandle ? `-${srcHandle}` : ""}-${connection.target}`;
        if (body.edges.some((edge) => edge.id === id)) return;
        next = { ...body, edges: [...body.edges, { id, source: connection.source, target: connection.target, source_handle: srcHandle ?? null }] };
      }
      commit(next);
    },
    [body, commit],
  );

  const addNode = (type: string) => {
    const meta = registry.get(type);
    if (!meta || type === "start") return;
    const base = type.replace(/[_.]/g, "-");
    let index = 1;
    while (body.nodes.some((node) => node.id === `${base}-${index}`)) index += 1;
    const maxX = Math.max(0, ...body.nodes.map((node) => node.position?.x ?? 0));
    const config: Record<string, unknown> = {};
    for (const [key, spec] of Object.entries(meta.config as Record<string, { type?: string }>)) {
      // "graph"(循环体子图)必须种成空图,种成 "" 会让子画布打开时 body.nodes.length 崩掉。
      config[key] = spec?.type === "object" ? {} : spec?.type === "graph" ? { nodes: [], edges: [] } : "";
    }
    commit({
      ...body,
      nodes: [
        ...body.nodes,
        { id: `${base}-${index}`, type, name: meta.label, position: { x: maxX + 240, y: 140 + (body.nodes.length % 3) * 90 }, config },
      ],
    });
  };

  const selectedNode = selectedId ? (body.nodes.find((node) => node.id === selectedId) ?? null) : null;

  return (
    <div className="absolute inset-0 z-30 grid grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-lg border border-border bg-panel">
      <div className="flex items-center gap-2.5 border-b border-border bg-card px-2 py-1.5">
        <button type="button" className="inline-flex items-center gap-[5px] rounded-md border border-input bg-card px-2 py-1 text-xs text-foreground hover:bg-muted" onClick={onClose}>
          <ArrowLeft size={14} /> {t("wfLoopBack")}
        </button>
        <span className="inline-flex items-center gap-[5px] text-[12.5px] font-semibold text-foreground">
          {loopNode.type === "subgraph" ? <Boxes size={13} /> : <Repeat size={13} />} {loopNode.name} ·{" "}
          {t(loopNode.type === "subgraph" ? "wfSubgraphBody" : "wfLoopBody")}
        </span>
        <SearchableSelect
          value=""
          onValueChange={addNode}
          searchPlaceholder={t("wfAddNode")}
          options={subOptions.filter((option) => option.value !== "start")}
          trigger={
            <button
              type="button"
              className="ml-auto flex h-8 w-auto items-center gap-1 rounded-full border border-input bg-card px-3 text-xs text-foreground hover:bg-muted"
              aria-label={t("wfAddNode")}
            >
              <Plus size={12} />
              <span>{t("wfAddNode")}</span>
            </button>
          }
        />
      </div>
      <div className="relative min-h-0">
        <ReactFlow
          className={cn("[--xy-attribution-background-color:color-mix(in_srgb,var(--panel)_70%,transparent)]", !bodyViewReady && "opacity-0")}
          nodes={nodes}
          edges={shapedEdges}
          nodeTypes={NODE_COMPONENT_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_event, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId(null)}
          /* 触控板约定(Figma / Miro 那套):双指滑动 = 平移,捏合 = 缩放。
             React Flow 默认 zoomOnScroll:true,而 macOS 触控板双指滑动发出的正是 wheel 事件,
             于是「想拖画布」变成了「缩放」。捏合发的是 ctrlKey 的 wheel,归 zoomOnPinch 管,
             所以关掉 zoomOnScroll 不影响捏合;鼠标用户按住 ctrl/⌘ 滚轮同样落进这条,仍可缩放。 */
          panOnScroll
          zoomOnScroll={false}
          zoomOnPinch
          connectionLineType={edgeShape as ConnectionLineType}
          defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
          deleteKeyCode={["Backspace", "Delete"]}
          onInit={(instance) =>
            requestAnimationFrame(() => {
              instance.fitView({ padding: 0.3, maxZoom: 1 });
              setBodyViewReady(true);
            })
          }
        >
          <Background gap={20} size={1.2} />
          <Controls
            showInteractive={false}
            position="bottom-left"
            className="overflow-hidden rounded-md border border-border [--xy-controls-box-shadow:none] [--xy-controls-button-background-color:var(--panel)] [--xy-controls-button-background-color-hover:var(--secondary)] [--xy-controls-button-border-color:var(--border)] [--xy-controls-button-color:var(--muted-foreground)] [--xy-controls-button-color-hover:var(--foreground)]"
          />
        </ReactFlow>
        {body.nodes.length === 0 && <div className="pointer-events-none absolute left-1/2 top-4 max-w-[70%] -translate-x-1/2 rounded-lg border border-dashed border-border bg-muted px-3 py-2 text-center text-xs text-muted-foreground">{t(loopNode.type === "subgraph" ? "wfSubgraphEmptyHint" : "wfLoopEmptyHint")}</div>}
        {selectedNode && (
          <NodeInspector
            node={selectedNode}
            meta={registry.get(selectedNode.type) ?? null}
            graph={body}
            registry={registry}
            workspaceId={workspaceId}
            onChange={(patch) =>
              commit({ ...body, nodes: body.nodes.map((node) => (node.id === selectedNode.id ? { ...node, ...patch } : node)) })
            }
            onApplyGraph={(next) => commit(next)}
            onDelete={() => {
              commit({
                ...body,
                nodes: body.nodes.filter((node) => node.id !== selectedNode.id),
                edges: body.edges.filter((edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id),
              });
              setSelectedId(null);
            }}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
}

function NodeInspector({
  anchor,
  inert = false,
  node,
  meta,
  graph,
  registry,
  workspaceId,
  onChange,
  onApplyGraph,
  onDelete,
  onClose,
}: {
  /** 贴靠几何:给出就浮现在节点旁(见 anchorToNode);不给就沿用贴右边占满高度的老样式。 */
  anchor?: AnchorBox | null;
  /** 画布正在平移:此时面板不吃指针事件(见 WorkflowsView 里 panning 的说明)。 */
  inert?: boolean;
  node: WorkflowGraph["nodes"][number];
  meta: WorkflowNodeType | null;
  graph: WorkflowGraph;
  registry: Map<string, WorkflowNodeType>;
  workspaceId: string;
  onChange: (patch: Partial<WorkflowGraph["nodes"][number]>) => void;
  onApplyGraph: (next: WorkflowGraph) => void;
  onDelete?: () => void;
  onClose?: () => void;
}) {
  const t = useI18n();
  const config = (node.config ?? {}) as Record<string, unknown>;
  const specs = Object.entries((meta?.config ?? {}) as Record<string, ConfigSpec>);
  // 变量插入要按光标位置写回,input 和 textarea 都有 selectionStart,两者都收。
  const fieldRefs = React.useRef<Record<string, HTMLTextAreaElement | HTMLInputElement | null>>({});
  // 每字段的输入方式:手动填写 vs 连接上游输出(ComfyUI 式)。默认从值推断(纯引用=连接)。
  const variables = React.useMemo(
    () => upstreamVariables(graph, node.id, registry),
    [graph, node.id, registry],
  );

  // 失效引用:本节点配置里引用了图中已不存在的节点(通常是上游被删)。
  const staleRefs = React.useMemo(() => {
    const ids = new Set(graph.nodes.map((n) => n.id));
    const found: Array<{ key: string; ref: string }> = [];
    for (const [key, val] of Object.entries(node.config ?? {})) {
      for (const { ref, sourceId } of extractRefs(val)) {
        if (!ids.has(sourceId) && !found.some((f) => f.key === key && f.ref === ref)) {
          found.push({ key, ref });
        }
      }
    }
    return found;
  }, [node.config, graph.nodes]);

  // 动态选项源:按需拉取,只有对应节点类型选中时才请求。
  const providers = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
    enabled: node.type === "llm" || node.type === "ai_generate",
  });
  const pluginTools = useQuery({
    queryKey: ["plugin-tools"],
    queryFn: () =>
      api<Array<{ instance_id: string; instance_name: string; package_id: string; name: string }>>(
        "/api/plugins/tools",
      ),
    enabled: node.type === "plugin_tool",
  });
  const callableWorkflows = useQuery({
    queryKey: ["workflows", workspaceId],
    queryFn: () => listWorkflows(workspaceId),
    enabled: node.type === "call_workflow",
  });
  const publishAccounts = useQuery({
    queryKey: ["publish-accounts", workspaceId],
    queryFn: () => listPublishAccounts(workspaceId),
    enabled: node.type === "publish",
  });
  // llm 节点的模型列表:所选供应商端点上真实可用的模型。以前这里是个纯文本框,
  // 要用户凭记忆手打模型名 —— 打错了要等到运行时才报错。
  const llmProfileId = node.type === "llm" ? String(config.profile_id || "") : "";
  const llmModels = useQuery({
    queryKey: ["provider-models", llmProfileId],
    queryFn: () => listProviderModels(llmProfileId),
    enabled: node.type === "llm" && Boolean(llmProfileId),
    staleTime: 60_000,
  });
  const generationModels = useQuery({
    queryKey: ["generation-options", "all"],
    // 要完整类型:参数区靠 capabilities 决定渲染什么。以前这里只取了四个字段,
    // 于是「模型支持哪些参数」这份信息在工作流侧根本拿不到。
    // 现在两种能力各取一次再合并 —— 和 AI 工作台看到的是同一份(后端联接好的)。
    queryFn: async () => {
      const [image, video] = await Promise.all([
        api<GenerationModel[]>("/api/generation/options?kind=image"),
        api<GenerationModel[]>("/api/generation/options?kind=video"),
      ]);
      return [...image, ...video];
    },
    enabled: node.type === "ai_generate",
  });
  const providerDefaults = useQuery({
    queryKey: ["provider-defaults"],
    queryFn: () => api<ProviderDefault[]>("/api/settings/provider-defaults"),
    enabled: node.type === "ai_generate",
  });
  const voices = useQuery({
    queryKey: ["workflow-voices", workspaceId],
    queryFn: () => listVoices(workspaceId),
    enabled: node.type === "synthesize_speech",
  });
  // 强类型 asset 字段(如 素材转写.asset_id)手动模式下,给工作区素材下拉,免手填 UUID。
  const hasAssetField = specs.some(([key]) => inputType(node.type, key) === "asset");
  const assets = useQuery({
    queryKey: ["workflow-assets", workspaceId],
    queryFn: () => listAssets(workspaceId),
    enabled: hasAssetField,
  });
  // 绑定校验:节点依赖的模型/服务没配好(空列表)或引用已失效(指向不存在的项)→ 顶部给提醒 + 配置入口。
  const bindingNotice = ((): { message: string; section: string; error?: boolean } | null => {
    if (node.type === "llm") {
      const list = providers.data ?? [];
      if (providers.isSuccess && list.length === 0) return { message: t("wfNoProviders"), section: "providers" };
      const pid = config.profile_id;
      if (pid && providers.isSuccess && !list.some((p) => p.id === pid))
        return { message: t("wfProviderMissing"), section: "providers", error: true };
    }
    if (node.type === "ai_generate") {
      const chosenProvider = config.provider as string | undefined;
      const chosenModel = config.model as string | undefined;
      const models = generationModels.data ?? [];
      const matchedModel = models.find(
        (model) =>
          model.provider === chosenProvider &&
          model.model === chosenModel &&
          (!config.kind || model.kind === config.kind),
      );
      const capability = String(config.kind || matchedModel?.kind || "image");
      const capabilityLabel = capability === "image" ? t("capImage") : capability === "video" ? t("capVideo") : capability;
      const section = `providers:${capability}`;
      if (chosenProvider && chosenModel && generationModels.isSuccess && !matchedModel) {
        return { message: t("wfGenModelMissing"), section, error: true };
      }
      const defaultForCapability = (providerDefaults.data ?? []).find((item) => item.capability === capability);
      const defaultProfile = defaultForCapability?.provider_profile_id
        ? (providers.data ?? []).find((profile) => profile.id === defaultForCapability.provider_profile_id)
        : null;
      if (
        providerDefaults.isSuccess &&
        providers.isSuccess &&
        (!defaultForCapability?.provider_profile_id || !defaultForCapability.model || !defaultProfile?.enabled)
      ) {
        return {
          message: t("aiCapabilityNotConfigured").replace("{capability}", capabilityLabel),
          section,
        };
      }
    }
    return null;
  })();

  // Esc 收起检查器 —— 输入框/代码编辑器里不劫持(那里 Esc 另有用途)。
  React.useEffect(() => {
    if (!onClose) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const setConfig = (key: string, value: unknown) => onChange({ config: { ...config, [key]: value } });
  const responseFormat = String(config.response_format || "text");
  const setTextConfig = (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => setConfig(key, event.target.value);

  // 重新指向:把某字段里的失效引用整体替换为新引用(空串=移除该引用)。
  const repoint = (key: string, oldRef: string, newRef: string) => {
    setConfig(key, String(config[key] ?? "").split(oldRef).join(newRef));
  };

  // 连接态字段(node.inputs)+ 数据边管理。
  const connectedInputs = node.inputs ?? [];
  // 本节点的后代(顺边正向可达),绑数据边时排除它们避免成环。
  const descendants = React.useMemo(() => {
    const adjacency = new Map<string, string[]>();
    for (const edge of graph.edges) {
      adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
    }
    const seen = new Set<string>();
    const queue = [...(adjacency.get(node.id) ?? [])];
    while (queue.length) {
      const current = queue.pop()!;
      if (seen.has(current)) continue;
      seen.add(current);
      queue.push(...(adjacency.get(current) ?? []));
    }
    return seen;
  }, [graph.edges, node.id]);
  // 可绑定来源:任意非后代、非自身节点的具体输出(数据边本身即建立依赖/排序)。
  const upstreamOptions = graph.nodes.flatMap((source) => {
    if (source.id === node.id || descendants.has(source.id)) return [];
    return (registry.get(source.type)?.outputs ?? [])
      .filter((output) => !output.startsWith("*"))
      .map((output) => ({ ref: `{{${source.id}.${output}}}`, sourceId: source.id, output }));
  });
  const dataEdgeFor = (key: string) =>
    graph.edges.find((edge) => edge.kind === "data" && edge.target === node.id && edge.target_input === key) ?? null;

  // 切换字段的连接态:连接=进 inputs;断开=移出 inputs 并删对应数据边。
  const setConnected = (key: string, connected: boolean) => {
    const inputs = new Set(connectedInputs);
    if (connected) inputs.add(key);
    else inputs.delete(key);
    onApplyGraph({
      ...graph,
      edges: connected
        ? graph.edges
        : graph.edges.filter(
            (edge) => !(edge.kind === "data" && edge.target === node.id && edge.target_input === key),
          ),
      nodes: graph.nodes.map((n) => (n.id === node.id ? { ...n, inputs: [...inputs] } : n)),
    });
  };

  // 绑定输入到某上游输出:建/换数据边,清字面量交给数据边供值。
  const bindInput = (key: string, sourceId: string, output: string) => {
    const id = `d-${sourceId}-${output}-${node.id}-${key}`;
    onApplyGraph({
      ...graph,
      edges: [
        ...graph.edges.filter((edge) => !(edge.kind === "data" && edge.target === node.id && edge.target_input === key)),
        { id, source: sourceId, target: node.id, kind: "data" as const, source_output: output, target_input: key },
      ],
      nodes: graph.nodes.map((n) =>
        n.id === node.id
          ? { ...n, inputs: [...new Set([...connectedInputs, key])], config: { ...(n.config ?? {}), [key]: "" } }
          : n,
      ),
    });
  };

  const insertVariable = (key: string, ref: string) => {
    const el = fieldRefs.current[key];
    const current = String(config[key] ?? "");
    if (!el) {
      setConfig(key, current + ref);
      return;
    }
    const start = el.selectionStart ?? current.length;
    const end = el.selectionEnd ?? current.length;
    setConfig(key, current.slice(0, start) + ref + current.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      el.selectionStart = el.selectionEnd = start + ref.length;
    });
  };

  // ── AI 生成节点:所选模型 + 它声明支持的参数 ────────────────────────────────
  /** 是否展开「手动指定 provider/model/类型」。目录里有的模型不需要看见这三项。 */
  const [genCustom, setGenCustom] = React.useState(false);
  const genModel =
    node.type === "ai_generate"
      ? (generationModels.data ?? []).find(
          (item) => item.provider === config.provider && item.model === config.model && item.kind === config.kind,
        ) ?? null
      : null;
  const genParams = (config.parameters ?? {}) as Record<string, unknown>;
  const setGenParam = (key: string, value: string) => {
    const next = { ...genParams };
    // 空值就删掉这一项,而不是塞空串:后端会把空串当"显式指定了空"传给供应商。
    if (value === "") delete next[key];
    else next[key] = /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value;
    setConfig("parameters", next);
  };
  /** 该模型声明支持、且是「从若干可选值里挑一个」的那些参数。 */
  const genParamKeys: Array<{ key: string; label: string; options: string[] }> = React.useMemo(() => {
    if (!genModel) return [];
    const out: Array<{ key: string; label: string; options: string[] }> = [];
    const ratios = aspectRatioOptions(genModel);
    if (ratios.length > 0) out.push({ key: "aspect_ratio", label: t("wfGenAspectRatio"), options: ratios });
    if (genModel.kind === "image") {
      const sizes = imageSizeOptions(genModel);
      if (sizes.length > 0) out.push({ key: "size", label: t("wfGenSize"), options: sizes });
    } else {
      const resolutions = videoResolutionOptions(genModel);
      if (resolutions.length > 0) out.push({ key: "resolution", label: t("wfGenResolution"), options: resolutions });
      const durations = durationOptions(genModel);
      if (durations.length > 0)
        out.push({ key: "duration_seconds", label: t("wfGenDuration"), options: durations.map(String) });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genModel]);

  /** 哪些动态下拉允许手填值。
   *
   * 素材/账号/音色这类**资源**是闭集:填一个不存在的 id 只会在运行时报错,所以下拉即全集。
   * 模型名不是:供应商上新模型往往早于我们的目录更新,只给下拉等于把人堵在「列表里没有、
   * 于是填不进去」的死角里。 */
  const allowsCustomValue = (key: string) => key === "model";

  /** (nodeType, key) → 动态下拉选项;返回 null 表示该字段不是动态选择。 */
  const dynamicOptions = (
    key: string,
    spec?: { plugin_instances?: boolean },
  ): Array<{ value: string; label: string }> | null => {
    if (node.type === "llm" && key === "profile_id") {
      return (providers.data ?? []).map((p) => ({ value: p.id, label: `${p.name} (${p.vendor})` }));
    }
    if (node.type === "llm" && key === "model") {
      // 端点上真实存在的模型。allowsCustomValue 同时放行手填 —— 新模型上线往往早于目录更新,
      // 只给下拉会把人堵死在一个「列表里没有,于是填不进去」的死角。
      return (llmModels.data ?? []).map((m) => ({ value: m.id, label: m.id }));
    }
    // 「用哪个连接」:声明里标了 plugin_instances 的字段都走这里。插件节点(plugin.<包>.<工具>)
    // 只列这个包的连接;老的通用 plugin_tool 节点按它 config 里选的包过滤。
    if (spec?.plugin_instances) {
      const parsed = node.type.startsWith("plugin.") ? node.type.slice("plugin.".length) : "";
      const packageId = parsed ? parsed.slice(0, parsed.lastIndexOf(".")) : String(config.plugin_id ?? "");
      const seen = new Map<string, string>();
      for (const tool of pluginTools.data ?? []) {
        if (packageId && tool.package_id !== packageId) continue;
        seen.set(tool.instance_id, tool.instance_name);
      }
      return [...seen].map(([value, label]) => ({ value, label }));
    }
    if (node.type === "plugin_tool" && key === "plugin_id") {
      const seen = new Map<string, string>();
      for (const tool of pluginTools.data ?? []) seen.set(tool.package_id, tool.instance_name);
      return [...seen].map(([value, label]) => ({ value, label }));
    }
    if (node.type === "plugin_tool" && key === "tool_name") {
      return (pluginTools.data ?? [])
        .filter((tool) => !config.plugin_id || tool.package_id === config.plugin_id)
        .map((tool) => ({ value: tool.name, label: tool.name }));
    }
    if (node.type === "publish" && key === "account_id") {
      return (publishAccounts.data ?? []).map((account) => ({ value: account.id, label: account.name }));
    }
    if (node.type === "synthesize_speech" && key === "voice_id") {
      return (voices.data ?? []).map((voice) => ({ value: voice.id, label: voice.name }));
    }
    if (node.type === "call_workflow" && key === "workflow_id") {
      // 列出可调用的工作流;选到自己/成环由后端运行时守卫拒绝。
      return (callableWorkflows.data ?? []).map((wf) => ({ value: wf.id, label: wf.name }));
    }
    // asset 型字段:工作区素材下拉(label 用素材名,回退原始文件名)。
    if (inputType(node.type, key) === "asset") {
      return (assets.data ?? []).map((asset) => ({
        value: asset.id,
        label: asset.name || asset.original_filename,
      }));
    }
    return null;
  };

  // 面板真正要渲染的字段:llm / ai_generate 的那几项由各自的专区管,不走通用列表。
  const visibleSpecs = specs
    .filter(([key]) => !(node.type === "llm" && LLM_SPECIAL_CONFIG_KEYS.has(key)))
    .filter(([key]) => !(node.type === "ai_generate" && GENERATE_SPECIAL_CONFIG_KEYS.has(key)));
  // 分级:留空也能跑的专业旋钮收进折叠区(由后端 NODE_TYPES 的 advanced 声明),第一眼只留下
  // 决定「这个节点在做什么」的字段 —— 十几个采样参数一上来就糊到脸上,新手根本无从下手。
  const basicSpecs = visibleSpecs.filter(([, spec]) => !spec?.advanced);
  const advancedSpecs = visibleSpecs.filter(([, spec]) => Boolean(spec?.advanced));

  /** 一个配置字段的渲染。抽出来是因为要渲染两遍:基础项直接铺开,高级项收进折叠区。 */
  const renderField = ([key, spec]: [string, ConfigSpec]) => {
          // 循环体 / 子图都是内嵌子图(graph 类型):不铺原始 JSON 文本框,给个只读概览(子画布编辑见 L3)。
          if (spec?.type === "graph") {
            const bodyNodes = ((config[key] as { nodes?: unknown[] } | undefined)?.nodes ?? []).length;
            const isSubgraph = node.type === "subgraph";
            return (
              <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none" key={key}>
                <label>{t(isSubgraph ? "wfSubgraphBody" : "wfLoopBody")}</label>
                <div className="rounded-md border border-dashed border-border bg-muted px-2.5 py-2 text-[11.5px] leading-normal text-muted-foreground">{t(isSubgraph ? "wfSubgraphBodyNote" : "wfLoopBodyNote").replace("{n}", String(bodyNodes))}</div>
              </div>
            );
          }
          const value = config[key];
          const isObject = spec?.type === "object";
          const options = spec?.options
            ? spec.options.map((option) => ({ value: option, label: option }))
            : dynamicOptions(key, spec as { plugin_instances?: boolean } | undefined);
          const labelKey = FIELD_LABEL_KEYS[key];
          // ComfyUI 式:非 object 字段都可切到"连接"(暴露输入接点,再从画布拖数据边或下拉选源)。
          const canConnect = !isObject;
          const connected = canConnect && connectedInputs.includes(key);
          const boundEdge = connected ? dataEdgeFor(key) : null;
          const boundValue = boundEdge ? `${boundEdge.source}.${boundEdge.source_output}` : "";
          return (
            <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none" key={key}>
              <span>
                {labelKey ? t(labelKey) : key}
                {spec?.required ? <em className="font-bold not-italic text-destructive">*</em> : null}
                {canConnect && (
                  <button
                    type="button"
                    className={cn(
                      "ml-auto inline-flex cursor-pointer items-center gap-[3px] rounded-full border border-border bg-transparent px-1.5 py-px text-[10px] font-medium text-muted-foreground transition-[border-color,color,background] duration-100 hover:border-border-strong hover:text-foreground",
                      connected && "border-[color-mix(in_srgb,var(--primary)_45%,transparent)] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary hover:text-primary",
                    )}
                    title={t("wfInputModeHint")}
                    onClick={(event) => {
                      event.preventDefault();
                      setConnected(key, !connected);
                    }}
                  >
                    {connected ? <Link2 size={11} /> : <PenLine size={11} />}
                    {connected ? t("wfInputRef") : t("wfInputManual")}
                  </button>
                )}
              </span>
              {connected ? (
                <div className="relative pl-3 before:absolute before:left-0 before:top-1/2 before:h-[7px] before:w-[7px] before:-translate-y-1/2 before:rounded-full before:bg-primary before:content-[''] [&_:where(button,[role=combobox])]:w-full">
                  <Select
                    value={boundValue}
                    onValueChange={(next) => {
                      const dot = next.indexOf(".");
                      bindInput(key, next.slice(0, dot), next.slice(dot + 1));
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t("wfPickUpstream")} />
                    </SelectTrigger>
                    <SelectContent>
                      {upstreamOptions.map((option) => (
                        <SelectItem key={option.ref} value={`${option.sourceId}.${option.output}`}>
                          {option.sourceId}.{option.output}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : options ? (
                spec?.options ? (
                  <Select value={String(value ?? "")} onValueChange={(next) => setConfig(key, next)}>
                    <SelectTrigger>
                      <SelectValue placeholder={t("wfPickOption")} />
                    </SelectTrigger>
                    <SelectContent>
                      {options.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  // 动态资源列表(素材/账号/数据集/音色…)可能很长 → 可搜索。
                  <Combobox
                    value={String(value ?? "")}
                    options={options}
                    placeholder={t("wfPickOption")}
                    emptyText={t("cmdkEmpty")}
                    allowCustomValue={allowsCustomValue(key)}
                    className="w-full"
                    onValueChange={(next) => setConfig(key, next)}
                  />
                )
              ) : isObject ? (
                <JsonField value={value} onChange={(parsed) => setConfig(key, parsed)} />
              ) : spec?.type === "code" ? (
                <CodeField value={String(value ?? "")} onChange={(next) => setConfig(key, next)} variables={variables} />
              ) : spec?.type === "template" ? (
                // 只有模板字段需要多行:它要放 {{变量}}、要支持 `/` 唤起变量菜单。
                <VarTextarea
                  textareaRef={(el) => {
                    fieldRefs.current[key] = el;
                  }}
                  rows={2}
                  value={String(value ?? "")}
                  onChange={(next) => setConfig(key, next)}
                  variables={variables}
                />
              ) : (
                // string / number 是单行值,以前也铺成可拖拽的多行文本域 —— 于是同一个面板里
                // 并排出现三种控件(Select / Combobox / 带拖拽手柄的文本域),看着像没做完。
                // 控件跟着字段声明的类型走。
                <Input
                  ref={(el) => {
                    fieldRefs.current[key] = el;
                  }}
                  type={spec?.type === "number" ? "number" : "text"}
                  value={String(value ?? "")}
                  placeholder={spec?.default ? String(spec.default) : ""}
                  onChange={(event) => setConfig(key, event.target.value)}
                />
              )}
              {!connected && spec?.type === "template" && variables.length > 0 && (
                <div className="flex flex-wrap gap-[3px]">
                  {variables.map((ref) => (
                    <button
                      key={ref}
                      type="button"
                      className="cursor-pointer rounded-md border border-border bg-[color-mix(in_srgb,var(--primary)_6%,transparent)] px-1.5 py-px font-mono text-[10px] text-primary transition-[border-color,background] duration-100 hover:border-primary hover:bg-[color-mix(in_srgb,var(--primary)_12%,transparent)]"
                      title={t("wfInsertVar")}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => insertVariable(key, ref)}
                    >
                      {ref.replace(/[{}]/g, "")}
                    </button>
                  ))}
                </div>
              )}
              {spec?.description && <small>{spec.description}</small>}
            </div>
          );
  };

  return (
    <aside
      className={cn(
        "z-30 grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-lg border border-border-strong bg-panel shadow-[var(--shadow-panel)]",
        anchor
          ? "fixed w-[320px] max-w-[calc(100vw-24px)]"
          : "absolute bottom-2 right-2 top-2 w-[min(300px,calc(100%-32px))]",
        inert && "pointer-events-none",
      )}
      style={anchor ? { left: anchor.left, top: anchor.top, maxHeight: anchor.maxHeight } : undefined}
      aria-label={node.name || meta?.label || node.type}
    >
      <div className="flex min-h-[38px] items-center justify-between gap-2 border-b border-border px-2.5">
        <span className="grid h-6 w-6 flex-none place-items-center rounded-md bg-[color-mix(in_srgb,var(--wf-node-color,var(--primary))_12%,transparent)] text-[color:var(--wf-node-color,var(--primary))]" style={{ "--wf-node-color": WF_NODE_COLORS[node.type] } as React.CSSProperties}>
          {NODE_ICONS[node.type] ?? <Type size={13} />}
        </span>
        <div className="grid min-w-0 flex-1 gap-0 [&_small]:pl-0 [&_small]:text-[10.5px] [&_small]:text-muted-foreground">
          {/* 节点名直接在头部内联编辑(Dify 式),不再单列一个"节点名称"字段。
              h-6 收掉 Input 基础款的 h-9:38px 头部里塞 36px 输入框会把整行撑満,
              名字看着像一只大号表单框而不是可改的标题。 */}
          <Input
            className="-ml-1 h-6 min-w-0 rounded-md border border-transparent bg-transparent px-1 py-px text-[13px] font-semibold text-foreground shadow-none hover:border-border focus-visible:border-primary focus-visible:bg-background focus-visible:outline-none focus-visible:ring-0"
            value={node.name ?? ""}
            placeholder={meta?.label ?? node.type}
            aria-label={t("wfNodeName")}
            onChange={(event) => onChange({ name: event.target.value })}
          />
          {/* 名称输入的 placeholder 已是类型名;仅在改过名(与类型不同)时才补一行类型。 */}
          {node.name && node.name !== (meta?.label ?? node.type) && <small>{meta?.label ?? node.type}</small>}
        </div>
        {onDelete && (
          <button type="button" className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive" aria-label={t("delete")} onClick={onDelete}>
            <Trash2 size={13} />
          </button>
        )}
        {onClose && (
          <button type="button" className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-secondary hover:text-foreground" aria-label={t("close")} title={`${t("close")} (Esc)`} onClick={onClose}>
            <X size={14} />
          </button>
        )}
      </div>
      <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] content-start gap-2 overflow-x-hidden overflow-y-auto p-2.5">
        {meta && <p className="m-0 text-[11.5px] leading-normal text-muted-foreground">{meta.description}</p>}
        {bindingNotice && (
          <ConfigNotice
            message={bindingNotice.message}
            actionLabel={t("wfGoConfigure")}
            section={bindingNotice.section}
            tone={bindingNotice.error ? "error" : "warn"}
          />
        )}
        {staleRefs.length > 0 && (
          <div className="flex flex-col gap-1.5 rounded-md border border-[color-mix(in_srgb,var(--destructive)_40%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_6%,transparent)] px-2.5 py-2">
            <span className="flex items-center gap-[5px] text-[11px] font-semibold text-destructive">
              <AlertTriangle size={12} /> {t("wfStaleRefsTitle")}
            </span>
            {staleRefs.map(({ key, ref }) => (
              <div className="flex items-center justify-between gap-2" key={`${key}-${ref}`}>
                <code className="rounded-md border border-[color-mix(in_srgb,var(--destructive)_45%,transparent)] bg-[color-mix(in_srgb,var(--destructive)_10%,transparent)] px-1.5 py-px font-mono text-[10.5px] text-destructive line-through">{ref}</code>
                <Popover>
                  <PopoverTrigger asChild>
                    <button type="button" className="flex-none cursor-pointer rounded-md border border-border bg-panel px-2 py-0.5 text-[11px] text-foreground hover:border-border-strong">
                      {t("wfRepoint")}
                    </button>
                  </PopoverTrigger>
                  <PopoverContent align="end" className="flex w-[200px] flex-col gap-0.5 p-[5px]">
                    {variables.map((valid) => (
                      <button
                        key={valid}
                        type="button"
                        className="cursor-pointer rounded-md border-0 bg-transparent px-2 py-1.5 text-left font-mono text-xs hover:bg-muted"
                        onClick={() => repoint(key, ref, valid)}
                      >
                        {valid.replace(/[{}]/g, "")}
                      </button>
                    ))}
                    <button
                      type="button"
                      className="cursor-pointer rounded-md border-0 bg-transparent px-2 py-1.5 text-left text-xs text-destructive hover:bg-muted"
                      onClick={() => repoint(key, ref, "")}
                    >
                      {t("wfRemoveRef")}
                    </button>
                  </PopoverContent>
                </Popover>
              </div>
            ))}
          </div>
        )}
        {node.type === "ai_generate" && (
          <div className="grid min-w-0 gap-2">
            <div className={FIELD_BOX}>
              <span>
                {t("wfGenModel")}
                <em className="font-bold not-italic text-destructive">*</em>
              </span>
              <Combobox
                value={genModel?.id ?? ""}
                options={(generationModels.data ?? []).map((model) => ({
                  value: model.id,
                  label: `${model.model} · ${model.kind === "video" ? t("capVideo") : t("capImage")}`,
                }))}
                placeholder={t("wfGenModelHint")}
                emptyText={t("cmdkEmpty")}
                className="w-full"
                onValueChange={(id) => {
                  const model = (generationModels.data ?? []).find((item) => item.id === id);
                  if (!model) return;
                  // 三者一起写:分开填就会出现「图像模型 + 类型 video」这种自相矛盾的组合。
                  // 换模型时清空参数 —— 上一个模型的比例/时长在新模型上未必存在。
                  onChange({
                    config: { ...config, provider: model.provider, model: model.model, kind: model.kind, parameters: {} },
                  });
                  setGenCustom(false);
                }}
              />
              {!genModel && !genCustom && (config.provider || config.model) ? (
                <small className="text-destructive">{t("wfGenModelUnknown")}</small>
              ) : (
                <small>{t("wfGenModelDesc")}</small>
              )}
              <button
                type="button"
                className="w-fit cursor-pointer border-0 bg-transparent p-0 text-[11px] font-medium text-primary underline-offset-2 hover:underline"
                onClick={() => setGenCustom((prev) => !prev)}
              >
                {genCustom ? t("wfGenCustomHide") : t("wfGenCustomShow")}
              </button>
            </div>

            {/* 自定义端点上的模型目录里没有 —— 这时才需要看见执行器那三个字段。
                已配置但对不上目录时自动展开,否则用户会看到一个空选择器却不知道值存在哪。 */}
            {(genCustom || (!genModel && Boolean(config.provider || config.model))) && (
              <div className="grid min-w-0 gap-2 border-l-2 border-border pl-2">
                <div className={FIELD_BOX}>
                  <span>{t("wffProvider")}</span>
                  <Input
                    value={String(config.provider ?? "")}
                    placeholder="openai-compatible"
                    onChange={(event) => setConfig("provider", event.target.value)}
                  />
                </div>
                <div className={FIELD_BOX}>
                  <span>{t("wffModel")}</span>
                  <Input
                    value={String(config.model ?? "")}
                    onChange={(event) => setConfig("model", event.target.value)}
                  />
                </div>
                <div className={FIELD_BOX}>
                  <span>{t("wffKind")}</span>
                  <Select value={String(config.kind ?? "image")} onValueChange={(next) => setConfig("kind", next)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="image">{t("capImage")}</SelectItem>
                      <SelectItem value="video">{t("capVideo")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )}

            {/* 生成参数按所选模型的 capabilities 渲染 —— 目录声明支持什么就出现什么。 */}
            {genModel && genParamKeys.length > 0 && (
              <>
                {genParamKeys.map(({ key, label, options }) => (
                  <div className={FIELD_BOX} key={key}>
                    <span>{label}</span>
                    <Select value={String(genParams[key] ?? "")} onValueChange={(next) => setGenParam(key, next)}>
                      <SelectTrigger>
                        <SelectValue placeholder={t("wfPickOption")} />
                      </SelectTrigger>
                      <SelectContent>
                        {options.map((option) => (
                          <SelectItem key={option} value={option}>
                            {option}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ))}
                {supportsParameter(genModel, "seed") && (
                  <div className={FIELD_BOX}>
                    <span>{t("wfGenSeed")}</span>
                    <Input
                      type="number"
                      value={String(genParams.seed ?? "")}
                      placeholder={t("wfGenSeedHint")}
                      onChange={(event) => setGenParam("seed", event.target.value)}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        )}
        {node.type === "llm" && (
          <div className="grid gap-[9px] rounded-lg border border-border bg-[color-mix(in_srgb,var(--muted)_58%,transparent)] p-[9px]">
            <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
              <span>{t("wfLlmPreset")}</span>
              <Select
                value={(config.preset as string) || "balanced"}
                onValueChange={(next) => setConfig("preset", next)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="precise">{t("wfPresetPrecise")}</SelectItem>
                  <SelectItem value="balanced">{t("wfPresetBalanced")}</SelectItem>
                  <SelectItem value="creative">{t("wfPresetCreative")}</SelectItem>
                </SelectContent>
              </Select>
              <small>
                {config.preset === "precise"
                  ? t("wfPresetPreciseHint")
                  : config.preset === "creative"
                    ? t("wfPresetCreativeHint")
                    : t("wfPresetBalancedHint")}
              </small>
            </div>
            <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
              <span>{t("wfLlmResponseFormat")}</span>
              <Select value={responseFormat} onValueChange={(next) => setConfig("response_format", next)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="text">{t("wfLlmResponseText")}</SelectItem>
                  <SelectItem value="json_object">{t("wfLlmResponseJsonObject")}</SelectItem>
                  <SelectItem value="json_schema">{t("wfLlmResponseJsonSchema")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-2 max-[1180px]:grid-cols-1">
              <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
                <span>{t("wfLlmTemperature")}</span>
                <Input
                  type="number"
                  min={0}
                  max={2}
                  step="0.1"
                  value={String(config.temperature ?? "")}
                  placeholder={t("wfLlmTemperaturePlaceholder")}
                  onChange={setTextConfig("temperature")}
                />
              </div>
              <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
                <span>{t("wfLlmTopP")}</span>
                <Input
                  type="number"
                  min={0}
                  max={1}
                  step="0.05"
                  value={String(config.top_p ?? "")}
                  placeholder="0-1"
                  onChange={setTextConfig("top_p")}
                />
              </div>
              <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
                <span>{t("wfLlmMaxTokens")}</span>
                <Input
                  type="number"
                  min={1}
                  step="1"
                  value={String(config.max_tokens ?? "")}
                  placeholder={t("wfLlmBlankDefault")}
                  onChange={setTextConfig("max_tokens")}
                />
              </div>
              <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
                <span>{t("wfLlmSeed")}</span>
                <Input
                  type="number"
                  step="1"
                  value={String(config.seed ?? "")}
                  placeholder={t("wfLlmBlankDefault")}
                  onChange={setTextConfig("seed")}
                />
              </div>
              <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
                <span>{t("wfLlmFrequencyPenalty")}</span>
                <Input
                  type="number"
                  min={-2}
                  max={2}
                  step="0.1"
                  value={String(config.frequency_penalty ?? "")}
                  placeholder="-2 到 2"
                  onChange={setTextConfig("frequency_penalty")}
                />
              </div>
              <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
                <span>{t("wfLlmPresencePenalty")}</span>
                <Input
                  type="number"
                  min={-2}
                  max={2}
                  step="0.1"
                  value={String(config.presence_penalty ?? "")}
                  placeholder="-2 到 2"
                  onChange={setTextConfig("presence_penalty")}
                />
              </div>
            </div>
            <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
              <span>{t("wfLlmStop")}</span>
              <VarTextarea
                rows={2}
                value={String(config.stop ?? "")}
                onChange={(next) => setConfig("stop", next)}
                variables={variables}
              />
              <small>{t("wfLlmStopHint")}</small>
            </div>
            {responseFormat === "json_schema" && (
              <>
                <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
                  <span>{t("wfLlmJsonSchemaName")}</span>
                  <Input
                    value={String(config.json_schema_name ?? "")}
                    placeholder="workflow_output"
                    onChange={setTextConfig("json_schema_name")}
                  />
                </div>
                <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
                  <span>{t("wfLlmJsonStrict")}</span>
                  <Select
                    value={String(config.json_schema_strict ?? "true")}
                    onValueChange={(next) => setConfig("json_schema_strict", next)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="true">{t("wfLlmJsonStrictOn")}</SelectItem>
                      <SelectItem value="false">{t("wfLlmJsonStrictOff")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
                  <span>{t("wfLlmJsonSchema")}</span>
                  <JsonField
                    value={config.json_schema ?? { type: "object", properties: {} }}
                    onChange={(parsed) => setConfig("json_schema", parsed)}
                  />
                </div>
              </>
            )}
          </div>
        )}
        {basicSpecs.map(renderField)}
        {advancedSpecs.length > 0 && (
          <details className="group min-w-0 rounded-md border border-border bg-[color-mix(in_srgb,var(--muted)_40%,transparent)]">
            <summary className="flex cursor-pointer list-none items-center gap-1 px-2 py-1.5 text-[11.5px] font-semibold text-muted-foreground marker:content-none hover:text-foreground">
              <ChevronRight size={12} className="transition-transform group-open:rotate-90" />
              {t("wfAdvanced")}
              <span className="font-normal opacity-60">{advancedSpecs.length}</span>
            </summary>
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2 border-t border-border p-2">
              {advancedSpecs.map(renderField)}
            </div>
          </details>
        )}
        {meta && (
          <div className="grid gap-[5px] border-t border-border pt-2.5 [&>span]:text-[11px] [&>span]:font-semibold [&>span]:uppercase [&>span]:tracking-[0.05em] [&>span]:text-muted-foreground">
            <span>{t("wfOutputs")}</span>
            <div className="flex flex-wrap gap-1">
              {meta.outputs.map((output) => {
                const ref = `{{${node.id}.${output}}}`;
                return (
                  <button
                    key={output}
                    type="button"
                    className="cursor-copy rounded-md border border-border bg-secondary px-[7px] py-0.5 font-mono text-[10.5px] text-foreground transition-[border-color] duration-100 hover:border-primary"
                    title={t("wfCopyRef")}
                    onClick={() => {
                      void navigator.clipboard.writeText(ref);
                      toast.success(t("wfRefCopied"), { description: ref });
                    }}
                  >
                    {ref}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
