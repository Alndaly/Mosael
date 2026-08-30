import React from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useStore } from "zustand";
import {
  Background,
  Handle,
  ConnectionLineType,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  NodeToolbar,
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
import { AlertTriangle, AlignLeft, Film, Maximize2, Image as ImageIcon, Map as MapIcon, AppWindow, ArrowLeft, AudioLines, Bell, BookOpen, Bot, Boxes, Braces, CaseSensitive, Check, CheckCircle2, ChevronLeft, ChevronRight, CircleCheck, Code2, Download, FileOutput, FileUp, Filter, Flag, FolderInput, FolderPlus, GitBranch, Globe, History, Hourglass, Keyboard, Languages, Link2, ListChecks, Loader2, Mic, MousePointer2, MousePointerClick, PanelTopClose, PenLine, Pencil, Play, Plus, Redo2, RefreshCw, Repeat, Rocket, ScanText, Search, SkipForward, Sparkles, Spline, Tags, Timer, Trash2, Type, Undo2, Wand2, Waypoints, Workflow as WorkflowIcon, Wrench, X, XCircle, type LucideIcon } from "lucide-react";
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
  importAsset,
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
import { useI18n, usePreferences } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import {
  extraLines,
  parseSourceAssets,
  serializeSourceAssets,
  valueForRole,
  withRole,
} from "@/features/workflows/sourceAssetLines";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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
import { useCanvasPosture } from "@/features/workflows/useCanvasPosture";
import { withDependentsCleared } from "@/features/workflows/dependents";
import { RefEditor } from "@/features/workflows/RefEditor";
import { MapField } from "@/features/workflows/MapField";
import { CodeEditor, type CodeEditorHandle } from "@/components/app/code-editor";
import { CanvasAgentChat, type CanvasAgentMode } from "@/components/agent/CanvasAgentChat";
import { WorkflowRunHistory } from "@/features/workflows/WorkflowRunHistory";
import { createWorkflowGraphStore } from "@/stores/workflowGraphStore";
import { saveJsonToDisk } from "@/lib/download";
import { ROW_HANDLE_CLASS, SIDEBAR_HANDLE_CLASS, handleOffset, useResizableRow, useResizableSidebar } from "@/lib/useResizableSidebar";
import { isMediaFile, useFileDrop } from "@/lib/useFileDrop";
import {
  aspectRatioOptions,
  capabilityNumber,
  durationRange,
  capabilityString,
  durationOptions,
  sizeOptions,
  maxImages,
  supportsParameter,
  sourceLimit,
  videoResolutionOptions,
} from "@/lib/generationCapabilities";
import { cn } from "@/lib/utils";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { relativeTime } from "@/lib/time";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { usePersistentSelection, usePersistentTab, usePersistentViewport } from "@/lib/usePersistentTab";

const AGENT_MODES = ["docked", "floating"] as const;
import { blurFloatingPanels, hasFocusedFloatingPanel } from "@/features/workflows/useFloatingPanel";
import {
  analyzeWorkflow,
  extractRefs,
  fieldDataType,
  inputType,
  outputType,
  typesCompatible,
  type DataType,
  type NodeIssue,
} from "@/features/workflows/analyze";
import { AssetInlinePreview } from "@/components/app/asset-preview";
import { RunOutputs, outputSummary } from "@/features/workflows/RunOutputs";
import { collapseToSubgraph } from "@/features/workflows/collapse";
import { assetOutputs, stepsByNode, type Step } from "@/features/workflows/runSteps";
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
/** 素材节点按**素材本身**取图标 —— 图片、视频、音频各是各的样子。 */
const ASSET_KIND_ICONS: Record<string, React.ReactNode> = {
  image: <ImageIcon size={13} />,
  video: <Film size={13} />,
  audio: <AudioLines size={13} />,
};

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
  /** 非素材产出的一行摘要 —— 节点上直接看见"这步给了什么"。 */
  runSummary?: string;
  /** **配置里指向的素材**(不是跑出来的)。素材节点没跑之前也该看得见自己指着哪张图。 */
  configAssetId?: string;
  /** 一行配置摘要:这个节点被配成做什么。没有它,一屏节点长得只有标题不一样。 */
  configSummary?: string;
  /** 每个输入接点收什么类型 —— 卡片按它给接点上色。 */
  inputTypes?: Record<string, string>;
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
    // 预览层:**自己就是通栏的**,因为卡片不带内边距(见卡片那段说明)。多份并排时用 1px 的
    // 底色缝隙隔开,不画框 —— 框会让它读成贴上去的独立元件,而它是卡片自己的一段。
    <div className="grid grid-flow-col justify-stretch gap-px overflow-hidden border-t border-border bg-border [&:last-child]:rounded-b-[7px]">
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
              ? "block h-[74px] w-full object-cover"
              : asset.kind === "video"
                ? "h-[74px] w-full bg-black object-cover"
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
  // 素材节点的图标要跟着**这份素材本身**走:一张图和一段视频不该长同一个样子。
  // 取不到就退回类型图标 —— 素材可能已被删除,那是正常路径。
  const configAsset = useQuery({
    queryKey: ["asset", d.configAssetId],
    queryFn: () => api<Asset>(`/api/assets/${d.configAssetId}`),
    enabled: Boolean(d.configAssetId),
    staleTime: 60_000,
    retry: false,
  });
  const kindIcon = ASSET_KIND_ICONS[configAsset.data?.kind ?? ""];
  const subtitle = d.configAssetId
    ? ""
    : d.configSummary || (d.label !== d.typeLabel ? d.typeLabel : "");
  const isCondition = d.nodeType === "condition";
  const badge = d.badge ?? null;
  const inputs = d.inputs ?? [];
  const outputs = d.outputs ?? [];
  // 条件节点保持紧凑(真/假分支端点),不上数据 IO 体;其余节点显示输入/输出接点。
  const showIo = !isCondition && (inputs.length > 0 || outputs.length > 0);
  return (
    <div
      className={cn(
        // **要有上界。** 标题里塞进一个 43 字符的文件名时,卡片会被撑到 375px(普通节点是 172),
        // 而 truncate 没有上界根本不会生效。撑宽不只是难看:贴节点浮现的检查器先试右侧,
        // 放不下才翻左侧 —— 一个过宽的节点会把面板推到左边,正好压在邻居身上。
        // **卡片自己不带内边距,分三层:标题层 / 预览层 / 参数层,各自带自己的。**
        //
        // 此前是"卡片统一 px-3 py-2,预览再用 -mx-3 顶回去、页脚再用 -mb-2 贴上去" ——
        // 负 margin 是把 padding 加错了层之后的补丁:每加一个新区块都要重新算一遍该抵消多少,
        // 而算错了只会看出来一点点歪。分层之后预览天然就是通栏的,不需要抵消任何东西。
        // **不能用 overflow-hidden。** 有些东西是**故意挂在卡片外面**的:右上角的告警角标
        // (-top-[7px] -right-[7px])、左右两侧的连接点(left-[-12px])。裁掉之后角标只剩半个、
        // 连接点变成贴边的半圆 —— 而它们正是要突出到边界之外才看得见。
        // 预览夹在标题层和接点层之间,本来就不碰圆角;真正需要圆角的是最底下那一层,
        // 由它自己 rounded-b 处理(见参数层)。
        "group/node relative flex min-w-[172px] max-w-[264px] flex-col rounded-lg border border-border bg-panel transition-[border-color] duration-100 hover:border-border-strong",
        // **两侧都有接点时才撑宽。** 单侧接点(比如只有输出的 LLM)撑到 210px 的话,那一列被
        // 推到最右边,左半张卡片是空的 —— 看着像排版坏了,其实是宽度给多了。
        showIo && inputs.length > 0 && outputs.length > 0 && "min-w-[210px]",
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
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="grid h-7 w-7 flex-none place-items-center rounded-md bg-[color-mix(in_srgb,var(--wf-node-color,var(--primary))_12%,transparent)] text-[color:var(--wf-node-color,var(--primary))]" style={{ "--wf-node-color": WF_NODE_COLORS[d.nodeType] } as React.CSSProperties}>{kindIcon ?? NODE_ICONS[d.nodeType] ?? <Type size={13} />}</span>
        <span className="grid min-w-0 gap-px [&_small]:truncate [&_small]:text-ui-2xs [&_small]:text-muted-foreground [&_strong]:truncate [&_strong]:text-ui-sm">
          <strong>{d.label}</strong>
          {/* **副标题只有一行**,而且优先说"这个节点被配成做什么"(模型名、被调的工作流),
              其次才是类型名 —— 类型名在同一屏里重复度最高,信息量最低。
              配置摘要此前是卡片里一条满宽的灰底,读起来像个禁用的输入框;它本来就是标题的
              附注,归到副标题位就不用再画一个框。
              指着某份素材时两者都不显示:图标已经说了是图还是视频,底下还有缩略图。 */}
          {subtitle && <small title={subtitle}>{subtitle}</small>}
        </span>
      </div>
      {/* 配置指向的素材:**没跑之前也该看得见自己指着哪张图**。跑过之后让位给产出预览 ——
          两张图并排会让人分不清哪张是输入哪张是输出。 */}
      {d.configAssetId && (d.runAssets ?? []).length === 0 && (
        <NodeResultPreview assetIds={[d.configAssetId]} />
      )}
      <NodeResultPreview assetIds={d.runAssets ?? []} />
      {/* 非素材的产出:模型回的那段话、抽出来的那个值。**跑完了却看不见**是此前最别扭的地方 ——
          想知道这一步到底给了什么,得在后面再接一个"通知"节点把它打出来。
          两行封顶:节点是张名片,不是日志窗口;全文在检查器里。 */}
      {d.runSummary && (
        <p className="m-0 line-clamp-2 whitespace-pre-wrap break-words border-t border-border bg-[color-mix(in_srgb,var(--muted)_45%,transparent)] px-3 py-1.5 text-ui-2xs leading-[1.45] text-muted-foreground">
          {d.runSummary}
        </p>
      )}
      {badge && (
        <span
          className={cn(
            "absolute -right-[7px] -top-[7px] inline-flex h-4 min-w-4 items-center gap-0.5 rounded-full px-1 text-ui-2xs font-bold leading-none text-white",
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
          {/* 真/假走 i18n:英文界面下这两个字此前还是中文 —— 它们贴在连线端点上,是整张图里
              最该看懂的两个词。 */}
          {/* **锚左边缘,不是右边缘。** `-right-5` 钉的是文字的右边,于是文字一变长就往左长 ——
              中文「真/假」两个字时看着还行,换成 True/False 就压在连接点上了。 */}
          <span className="pointer-events-none absolute left-full top-[calc(32%-7px)] ml-2 whitespace-nowrap text-ui-2xs font-semibold text-[#16a34a]">{t("wfBranchTrue")}</span>
          <span className="pointer-events-none absolute left-full top-[calc(68%-7px)] ml-2 whitespace-nowrap text-ui-2xs font-semibold text-[#e11d48]">{t("wfBranchFalse")}</span>
        </>
      ) : (
        <Handle type="source" position={Position.Right} className={cn("h-[9px]! w-[9px]! rounded-full! border-[1.5px]! border-border-strong! bg-panel! transition-[border-color,transform] duration-100 after:absolute after:-inset-[7px] after:rounded-full after:content-[''] hover:border-primary! group-hover/node:border-primary! [&.react-flow\_\_handle-left:hover]:[transform:translate(-50%,-50%)_scale(1.35)]! [&.react-flow\_\_handle-right:hover]:[transform:translate(50%,-50%)_scale(1.35)]!", selected && "border-primary!")} style={{ top: 22 }} />
      )}
      {showIo && (
        // 接口区做成卡片"页脚条":压进左右 padding、贴住底边、subtle 底色 —
        // 端口行读作独立的接线区,而不是悬在卡片下半的零散小字(空的一侧也不再是大片留白)。
        <div className="flex justify-between gap-4 rounded-b-[7px] border-t border-border bg-panel-subtle px-3 py-[6px]">
          <div className="flex min-w-0 flex-col gap-[3px]">
            {inputs.map((key) => (
              <div className="relative flex min-h-4 items-center" key={key}>
                <Handle
                  id={`in:${key}`}
                  type="target"
                  position={Position.Left}
                  className="h-[9px]! w-[9px]! rounded-full! border-[1.5px]! border-primary! bg-panel! data-[dtype=any]:border-border-strong! data-[dtype=asset]:border-[#c026d3]! data-[dtype=json]:border-[#0891b2]! data-[dtype=number]:border-[#d97706]! data-[dtype=sequence]:border-[#e11d48]! data-[dtype=text]:border-[#64748b]! left-[-12px]!"
                  data-dtype={(d.inputTypes ?? {})[key] ?? "any"}
                />
                {/* 有本地化标签走正文字体;裸标识符(如 items)与输出侧同用 mono,同卡不混排。 */}
                <span className={cn("whitespace-nowrap text-ui-2xs text-muted-foreground", !FIELD_LABEL_KEYS[key] && "font-mono")}>
                  {FIELD_LABEL_KEYS[key] ? t(FIELD_LABEL_KEYS[key]) : key}
                </span>
              </div>
            ))}
          </div>
          <div className="flex min-w-0 flex-col gap-[3px]">
            {outputs.map((output) => (
              <div className="relative flex min-h-4 items-center justify-end" key={output}>
                <span className="whitespace-nowrap font-mono text-ui-2xs text-muted-foreground">{output}</span>
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

/**
 * 属性面板里一格字段的样式(标签 + 控件 + 说明)。
 *
 * 这个常量早就有了,但注释里写着「面板里这串还散落在几十处内联」—— 那些内联已经在
 * 2026-08 的重做里全部收进来了(当时是十五处)。控件尺寸随之统一:输入框 h-8、
 * 内边距 px-2.5,不再有 p-1.5 和 h-9 两种说法。
 */
/** 素材角色在检查器里的排列顺序与名字。和后端 ai/providers/base.SOURCE_ROLES 同一套。 */
const SOURCE_ROLE_ORDER = [
  "first_frame",
  "last_frame",
  "reference_image",
  "reference_video",
  "reference_audio",
  "source_video",
  "first_clip",
  "driving_audio",
] as const;

const SOURCE_ROLE_LABELS: Record<(typeof SOURCE_ROLE_ORDER)[number], MessageKey> = {
  first_frame: "genFirstFrame",
  last_frame: "genLastFrame",
  reference_image: "genReferenceImage",
  reference_video: "genReferenceVideo",
  reference_audio: "genReferenceAudio",
  source_video: "genSourceVideo",
  first_clip: "genFirstClip",
  driving_audio: "genDrivingAudio",
};

/** 生成节点里的一个参数控件:枚举给下拉、区间给数字框、布尔给开关。 */
interface GenField {
  key: string;
  label: string;
  options: string[];
  range?: { min: number; max: number };
  toggle?: boolean;
}

/** 开关类参数 —— 描述符声明了才出现。有声比无声贵,不替用户默认打开。 */
const TOGGLE_PARAMS: Array<[string, MessageKey]> = [
  ["generate_audio", "wfGenAudio"],
  ["multi_shot", "wfGenMultiShot"],
];

const FIELD_BOX =
  "grid gap-1.5 [&>span]:flex [&>span]:items-center [&>span]:gap-1 [&>span]:text-ui-sm [&>span]:font-medium [&>span]:text-foreground " +
  "[&_small]:text-ui-xs [&_small]:leading-[1.5] [&_small]:text-muted-foreground " +
  "[&_input]:h-8 [&_input]:w-full [&_input]:rounded-md [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:px-2.5 [&_input]:text-ui-sm [&_input]:text-foreground " +
  "[&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-md [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:px-2.5 [&_textarea]:py-2 [&_textarea]:text-ui-sm [&_textarea]:text-foreground " +
  "[&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none " +
  "[&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none";

/** 助手面板的开合记忆。 */
const AGENT_PANEL_KEY = "openstudio:workflow-agent-open";

const NODE_COMPONENT_TYPES = { wf: WfNode };


/** 贴靠面板的几何:宽度固定,高度自适应但封顶;与节点之间留 10px 间隙,离窗口边至少 12px。 */


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
//: 生成节点里由专区自己渲染的配置项,不走通用字段列表。source_assets 在这里,是因为它在配置里
//: 是一段 `id:role` 的文本,而界面上该是**按角色一行一格** —— 让用户手写那段文本,角色名要背、
//: 冒号要记,写错了还不报错(后端拿不到角色就按默认走,于是"我明明挂了尾帧"的片子里没有尾帧)。
const GENERATE_SPECIAL_CONFIG_KEYS = new Set(["provider", "model", "kind", "parameters", "source_assets"]);

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

  // 列表页 / 详情页两态:**没选中就是列表**。
  //
  // 用 usePersistentSelection 而不是普通 state:页面是条件挂载的(切走整棵卸载),纯 state
  // 会让"进了详情、去别的页面看一眼、回来"变成回到列表 —— 用户报过。
  //
  // 之前我为了去掉"回落到第一条"把这个 hook 一起换掉了,那是看错了地方:回落写在下面那句
  // `?? list[0]` 里,hook 本身返回 null 就是 null(存的是空 = 列表页),正是这里要的。
  const [selectedId, setSelectedId] = usePersistentSelection("workflows", (workflows.data ?? []).map((w) => w.id));
  const selected = (workflows.data ?? []).find((w) => w.id === selectedId) ?? null;
  // 多选与素材页同一份状态机(见 lib/useMultiSelect)。
  const { selectMode, setSelectMode, selectedIds, toggle, selectAll, allSelected, clear, exit } =
    useMultiSelect(workflows.data ?? [], (workflow) => workflow.id);
  const [batchDeleting, setBatchDeleting] = React.useState(false);
  const batchRemove = useMutation({
    mutationFn: async () => {
      // 没有批量接口:逐条删,失败的报出去(和素材页同一种做法)。
      const failures: string[] = [];
      for (const id of selectedIds) {
        try {
          await deleteWorkflow(id);
        } catch (error) {
          failures.push(String((error as Error).message));
        }
      }
      return failures;
    },
    onSuccess: (failures) => {
      setBatchDeleting(false);
      clear();
      if (failures.length > 0) toast.error(failures.join("\n"));
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
  });

  if (workflows.isSuccess && (workflows.data ?? []).length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2 [&>*]:shrink-0">
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

  const importControl = (
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
  );

  // ── 详情页:整页给画布。返回列表是**唯一**的出口,所以放在最左、和标题同一行。
  if (selected && nodeTypes.data) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-hidden p-2 [&>*]:shrink-0">
        {/* 这一层给编辑器高度:页面容器是 [&>*]:shrink-0,不套 flex-1 的话画布会塌成 0。 */}
        <div className="grid min-h-0 flex-1">
          <WorkflowEditor
            key={selected.id}
            workflow={selected}
            nodeTypes={nodeTypes.data}
            workspaceId={workspace.id}
            onBack={() => setSelectedId(null)}
          />
        </div>
        {importControl}
        </div>
      );
  }

  // ── 列表页:卡片 grid。卡面上给的是**判断"是不是这一条"所需的**:名字、说明、
  //     多少个节点、上次改动是什么时候。
  return (
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2 [&>*]:shrink-0">
      <div className="flex items-center justify-between pb-2">
        <h2 className="m-0 inline-flex items-center gap-1.5 text-ui-md font-semibold text-foreground">
          <WorkflowIcon size={13} /> {t("navWorkflows")}
        </h2>
        <span className="flex flex-wrap items-center gap-1.5">
          {selectMode ? (
            <>
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                {t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}
              </span>
              <Button variant="outline" size="sm" onClick={() => selectAll(workflows.data ?? [])}>
                <ListChecks size={13} /> {allSelected(workflows.data ?? []) ? t("mediaDeselectAll") : t("mediaSelectAll")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="hover:border-destructive/50 hover:text-destructive"
                disabled={selectedIds.size === 0}
                onClick={() => setBatchDeleting(true)}
              >
                <Trash2 size={13} /> {t("delete")}
              </Button>
              <Button variant="ghost" size="sm" onClick={exit}>
                <X size={13} /> {t("cancel")}
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" size="sm" onClick={() => setSelectMode(true)}>
                <Check size={13} /> {t("mediaSelectMode")}
              </Button>
              <Button variant="outline" size="sm" loading={importFile.isPending} onClick={() => importInputRef.current?.click()}>
                <FileUp size={13} /> {t("wfImport")}
              </Button>
              <Button size="sm" loading={create.isPending} onClick={() => create.mutate()}>
                <Plus size={13} /> {t("wfCreate")}
              </Button>
            </>
          )}
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(232px,1fr))] gap-2">
          {workflows.isLoading &&
            (workflows.data ?? []).length === 0 &&
            [0, 1, 2, 3].map((i) => <Skeleton key={`sk${i}`} className="h-[104px] rounded-lg" />)}
          {(workflows.data ?? []).map((workflow) => (
            <ContextMenu key={workflow.id}>
              <ContextMenuTrigger asChild>
                <button
                  type="button"
                  className="relative h-full text-left"
                  onClick={() => (selectMode ? toggle(workflow.id) : setSelectedId(workflow.id))}
                >
                  <WorkflowCard workflow={workflow} />
                  {selectMode && <SelectionCheck selected={selectedIds.has(workflow.id)} />}
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
                <ContextMenuSeparator />
                <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setMenuDeleting(workflow)}>
                  <Trash2 /> {t("delete")}
                </ContextMenuItem>
              </ContextMenuContent>
            </ContextMenu>
          ))}
        </div>
      </div>
      {importControl}
      <RenameDialog
        open={menuRenaming !== null}
        title={t("rename")}
        initialValue={menuRenaming?.name ?? ""}
        onCancel={() => setMenuRenaming(null)}
        onSubmit={(name) => menuRenaming && menuRename.mutate({ id: menuRenaming.id, name })}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        body={t("wfDeleteBody")}
        onCancel={() => setBatchDeleting(false)}
        onConfirm={() => batchRemove.mutate()}
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


/**
 * 工作流卡片。**卡面上要能认出"是不是这一条"** —— 名字、一句说明、多大(几个节点)、
 * 上次改动是什么时候。此前列表只给名字和节点数,同名的「新工作流」并排五个时分不出来。
 */
function WorkflowCard({ workflow }: { workflow: Workflow }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const nodes = (workflow.graph as unknown as WorkflowGraph).nodes ?? [];
  return (
    // 同 PublishCard:名字贴顶、"几个节点 · 多久前"贴底,中间留给长短不一的说明。
    <article className="flex h-full flex-col gap-1.5 rounded-lg border border-border bg-panel p-2.5 shadow-[var(--shadow-panel)] transition-colors hover:border-border-strong">
      <div className="flex items-center gap-1.5">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary">
          <WorkflowIcon size={13} />
        </span>
        <strong className="min-w-0 truncate text-ui-md font-[650] text-foreground">{workflow.name}</strong>
      </div>
      {workflow.description ? (
        <p className="m-0 line-clamp-2 text-ui-xs leading-[1.45] text-muted-foreground [overflow-wrap:anywhere]">
          {workflow.description}
        </p>
      ) : (
        <p className="m-0 text-ui-xs text-muted-foreground/60">{t("wfNoDescription")}</p>
      )}
      <div className="mt-auto flex items-center gap-1.5 pt-0.5 text-ui-xs text-muted-foreground">
        <span className="tabular-nums">{t("wfNodeCount").replace("{n}", String(nodes.length))}</span>
        <span aria-hidden>·</span>
        <span className="truncate">{relativeTime(workflow.updated_at, locale)}</span>
      </div>
    </article>
  );
}

/** 配置里那份素材的 id。
 *
 *  按**字段类型**找(注册表里标了 asset 的那些),而不是认死"素材节点" —— 别的节点也可能
 *  收素材,认类型的话它们自动都有图,认名字就得一个个补。
 *
 *  值是模板({{上游.asset_id}})时返回空:那时候还不知道会是哪一份,画不出图来。 */
function configAsset(node: WorkflowGraph["nodes"][number], registry: Map<string, WorkflowNodeType>): string {
  for (const [key, value] of Object.entries(node.config ?? {})) {
    if (inputType(registry, node.type, key) !== "asset") continue;
    const text = String(value ?? "").trim();
    if (text && !text.includes("{{")) return text;
  }
  return "";
}

/** 一行配置摘要:这个节点被配成做什么。
 *
 *  一屏节点如果只有标题不一样,想知道"这个 LLM 用的哪个模型"就得一个个点开。挑的是**最能
 *  区分同类节点**的那个字段,而不是把配置全铺上去 —— 卡片是名片,不是配置表。 */
const SUMMARY_KEYS = ["model", "workflow_id", "voice_id", "seconds", "url", "tool_name"] as const;

function configSummary(node: WorkflowGraph["nodes"][number]): string {
  const config = node.config ?? {};
  for (const key of SUMMARY_KEYS) {
    const text = String(config[key] ?? "").trim();
    // 模板不摘要:`{{a.b}}` 摆在卡片上既占地方又什么都没说明。
    if (text && !text.includes("{{")) return text;
  }
  return "";
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
      configSummary: configSummary(node),
    } satisfies WfNodeData,
    deletable: true,
  }));
}

function toFlowEdges(graph: WorkflowGraph, t: ReturnType<typeof useI18n>, registry: Map<string, WorkflowNodeType>): Edge[] {
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
          inputType(registry, nodeType.get(edge.target) ?? "", edge.target_input),
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
      label:
        edge.source_handle === "true"
          ? t("wfEdgeTrue")
          : edge.source_handle === "false"
            ? t("wfEdgeFalse")
            : undefined,
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
  onBack,
}: {
  workflow: Workflow;
  nodeTypes: WorkflowNodeType[];
  workspaceId: string;
  /** 返回列表。**和标题同一行** —— 单独占一行会把整条工具栏挤下去(第一版就是这么做的)。 */
  onBack: () => void;
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
  const [edges, setEdges] = React.useState<Edge[]>(() => toFlowEdges(workflow.graph as unknown as WorkflowGraph, t, registry));
  const [dirty, setDirty] = React.useState(false);
  const [showHistory, setShowHistory] = React.useState(false);

  // 撤销/重做:temporal 改的是 store.graph,再从新 graph 重建 React Flow 的 nodes/edges。
  const syncFromGraph = React.useCallback(() => {
    const next = graphStore.getState().graph;
    setNodes(toFlowNodes(next, registry));
    setEdges(toFlowEdges(next, t, registry));
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
  // 导出走后端信封(格式和版本的权威在后端),落成 .openstudio-workflow.json —— 和列表页
  // 右键那条是同一个函数,不另写一份:两份迟早会在文件名或格式上分叉。
  const exportFile = useMutation({
    mutationFn: async () => {
      const envelope = await exportWorkflowFile(workflow.id);
      saveJsonToDisk(`${workflow.name}.openstudio-workflow.json`, envelope);
    },
    onError: (error: Error) => toast.error(t("wfExportFailed"), { description: error.message }),
  });
  // 默认关闭:进工作流页是来看画布的,助手默认占掉右侧近一半、把节点挤到看不见。
  // 需要时点顶栏「AI 助手」;开关状态记住,下次进来照旧。
  const [agentOpen, setAgentOpen] = React.useState(() => localStorage.getItem(AGENT_PANEL_KEY) === "1");
  React.useEffect(() => {
    localStorage.setItem(AGENT_PANEL_KEY, agentOpen ? "1" : "0");
  }, [agentOpen]);
  // 停靠还是浮窗,是布局偏好 —— 每次回来都弹回"停靠"等于每次都要重摆一遍。
  const [agentMode, setAgentMode] = usePersistentTab<CanvasAgentMode>("wf-agent-mode", "docked", AGENT_MODES);
  /** 执行历史与助手同一套停靠/悬浮机制,但各记各的模式与几何。 */
  const [historyMode, setHistoryMode] = usePersistentTab<CanvasAgentMode>("wf-history-mode", "docked", AGENT_MODES);
  const [edgeShape, setEdgeShape] = usePersistentTab<EdgeShape>("wf-edge-shape", "default", EDGE_SHAPES);
  //: 右下角的全览。默认开着 —— 大图时它最有用,而"图大不大"只有用户自己知道。
  const [minimapMode, setShowMinimap] = usePersistentTab<"on" | "off">("wf-minimap", "on", ["on", "off"] as const);
  const showMinimap = minimapMode === "on";
  /** 节点的手动层级。只在会话内有效,不写进图 —— 叠放是看图时的临时诉求(把被压住的那个
   *  拎出来看一眼),固化进数据会让每次调整都变成一次图变更、触发自动保存。 */
  const [nodeZ, setNodeZ] = React.useState<Record<string, number>>({});
  const [nodeSearchOpen, setNodeSearchOpen] = React.useState(false);
  const [nodeSearch, setNodeSearch] = React.useState("");
  // While a node is being dragged we pause auto-save: a mid-drag PATCH→refetch would rebuild the
  // graph and interrupt React Flow's drag. The save fires once, right after the drag settles.
  const [dragging, setDragging] = React.useState(false);
  // Drill-in: double-click a loop OR subgraph node to edit its nested body sub-graph in an overlay canvas.
  /**
   * 钻进了哪个子图。**记在本地,不是纯 state** —— 刷新一下就被弹回上一层是不对的:
   * 用户正在子图里编辑,按了刷新(或者应用自己重载),回来发现自己站在主流程上,
   * 而刚才改到一半的地方还得再点进去找。
   *
   * 和"选中哪个工作流"用的是同一个 hook:它会拿 ids 校验,那个节点被删掉之后自动回到主流程,
   * 不会卡在一个不存在的子图里。key 按工作流分,免得 A 工作流记下的节点 id 跑去 B 里生效。
   */
  const drillableIds = React.useMemo(
    () => graph.nodes.filter((node) => node.type === "subgraph" || node.type.startsWith("loop_")).map((node) => node.id),
    [graph.nodes],
  );
  const [editingLoopId, setEditingLoopId] = usePersistentSelection(`workflow-drill:${workflow.id}`, drillableIds);
  const rfRef = React.useRef<ReactFlowInstance | null>(null);
  // 画布姿态(是否已 fitView、视口动过几次、正不正在平移)。三条各自的来历见 useCanvasPosture
  // —— 它们是 React Flow 的机制,不是工作流的概念,所以不和图 / 弹窗 / 搜索那些 state 混在一起。
  const canvas = useCanvasPosture();
  // 每张工作流各记各的位置 —— 换一张图不该继承上一张停在哪儿。
  const viewport = usePersistentViewport(`workflow:${workflow.id}`);

  /**
   * 把视口居中到某坐标上。用坐标而非 getNode:新加节点此刻还没同步进 React Flow 内部 store,
   * getNode 会取空;而 setCenter 只改视口变换,不依赖节点已登记。
   *
   * 不再为「躲开右侧检查器」额外右移:配置面板贴着节点浮现(NodeToolbar,和节点同层),
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
      setEdges(toFlowEdges(next, t, registry));
    }
  }, [workflow.updated_at, workflow.graph, dirty, rebuildNodes]);

  const applyGraph = React.useCallback(
    (next: WorkflowGraph, options?: { coalesce?: boolean }) => {
      setGraph(next, options);
      rebuildNodes(next);
      setEdges(toFlowEdges(next, t, registry));
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
    setEdges(toFlowEdges(next, t, registry));
    setDirty(true);
    setSelectedNodeId(newNodes[0].id);
    return true;
  }, [graph, registry]);

  // Cmd/Ctrl+C 复制选中节点,Cmd/Ctrl+V 粘贴,Cmd/Ctrl+G 把选中的折叠成子图;
  // 输入框 / 代码编辑器里不劫持(交给系统复制粘贴)。
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
      } else if (key === "g") {
        // G = group,和别处"编组"是同一个键位。**要拦下浏览器的"查找下一个"** ——
        // 不 preventDefault 的话 Safari/Chrome 会在折叠的同时弹出查找栏。
        // 少于两个节点时不接管:那时这个操作本来就不成立,让系统的 ⌘G 照常工作。
        // 就地从 nodes 取选中项:selectedFlowIds 声明在这条 effect 后面,而它本来就是
        // nodes 的派生量 —— 为了顺序去搬一个几百行外的声明,只会让下一个人更难读。
        const picked = nodes.filter((node) => node.selected).map((node) => node.id);
        if (picked.length >= 2) {
          event.preventDefault();
          handleCollapse(picked);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [copySelection, pasteClipboard, nodes, handleCollapse]);

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
          setEdges(toFlowEdges(next, t, registry));
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
        setEdges(toFlowEdges(next, t, registry));
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

  /**
   * 把拖进来的文件上传成素材,并在**鼠标落点**放一个「素材」节点。
   *
   * 落在鼠标那儿而不是排在最右:拖放这个动作本身就指明了位置 —— 把它扔到别处去,
   * 用户得先找一下自己刚拖的东西去哪了。
   *
   * 逐个传而不是并发:一次拖十个视频,并发会把带宽和后端转码队列同时打满,
   * 而用户看到的是十个都卡着不动。
   */
  const dropUpload = useMutation({
    mutationFn: async ({ files, at }: { files: File[]; at: { x: number; y: number } }) => {
      const created: Array<{ id: string; name: string }> = [];
      for (const file of files) {
        const asset = await importAsset({ workspaceId, file });
        created.push({ id: asset.id, name: asset.name });
      }
      return { created, at };
    },
    onSuccess: ({ created, at }) => {
      let next = graph;
      created.forEach((asset, index) => {
        const base = "asset";
        let seq = 1;
        while (next.nodes.some((node) => node.id === `${base}-${seq}`)) seq += 1;
        const id = `${base}-${seq}`;
        next = {
          ...next,
          nodes: [
            ...next.nodes,
            {
              id,
              type: "asset",
              name: asset.name,
              // 多个文件斜着摞开,不然它们会精确重叠成一个。
              position: { x: at.x + index * 24, y: at.y + index * 24 },
              config: { asset_id: asset.id },
            },
          ],
        };
      });
      applyGraph(next);
      toast.success(t("wfDropped").replace("{n}", String(created.length)));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  // React Flow 的坐标换算要在 drop 那一刻做(那时才有鼠标位置),而 useFileDrop 的回调
  // 拿不到事件 —— 用一个 ref 把落点从事件里带出来。
  const pendingDropAt = React.useRef<{ x: number; y: number } | null>(null);
  const canvasDrop = useFileDrop((files) => {
    dropUpload.mutate({ files, at: pendingDropAt.current ?? { x: 120, y: 140 } });
  }, isMediaFile);

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
  // canvas.tick / graph 变化都要重算:前者是平移缩放,后者是节点位置被改。
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
    <CanvasAgentChat
      contextLine={t("wfAgentContext").replace("{id}", workflow.id).replace("{name}", workflow.name)}
      emptyHint={t("wfAgentEmpty")}
      placeholder={t("wfAgentPlaceholder")}
      rectKey="openstudio.wf.agent.rect.v2"
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
  // 右栏可拖 —— 和别处同一套(lib/useResizableSidebar)。此前是 minmax(360,420) 的固定范围:
  // AI 助手里的长回复和执行历史的步骤名在 360px 里都读得很挤,而画布这边常常有大片空白。
  const rightPanel = useResizableSidebar("workflow-right", { min: 320, max: 640, fallback: 400 });
  // 助手与执行历史上下分。上界给得宽 —— 只想看助手时把它拉满是合理的用法。
  const agentRow = useResizableRow("workflow-agent", { min: 160, max: 900, fallback: 420 });

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
   * 画布快捷键。
   *
   * ⌘/Ctrl+N 打开「添加节点」;⌘/Ctrl+S 存盘;⌘/Ctrl+Enter 运行。
   *
   * **在输入框里一律不劫持** —— 在节点检查器里打字时按 ⌘N,想要的是浏览器的新建窗口
   * (或什么都不发生),而不是画布上冒出一个节点。这和撤销那条同一个判据。
   */
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const key = event.key.toLowerCase();
      if (key === "n") {
        // 点那个按钮,而不是给 SearchableSelect 加一个受控 prop —— 它的开合是内部状态,
        // 为一个快捷键把它改成受控,调用它的另外几处都要跟着改。
        const trigger = document.querySelector<HTMLButtonElement>("[data-wf-add-node]");
        if (!trigger) return;
        event.preventDefault();
        trigger.click();
      } else if (key === "s") {
        event.preventDefault();
        if (!save.isPending) save.mutate();
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (!run.isPending) run.mutate();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

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
    () => {
      //: 画布节点(react-flow 的)身上没有 config,配置在图里。按 id 取回来。
      const graphNode = (id: string) =>
        graph.nodes.find((one) => one.id === id) ?? { id, type: "", config: {} };
      return nodes.map((node) => {
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
            runSummary: outputSummary(node.data.nodeType as string, step?.outputs),
            // **这两项算在这里,不在 toFlowNodes。** 那个函数跑在 useState 的初始化里,
            // 那一刻节点类型还没拉回来、registry 是空的 —— 算出来的永远是空值,而且不会重算。
            // (素材节点的缩略图和图标就是这么丢的:改成读注册表之后,读的是一张还没到货的表。)
            configAssetId: configAsset(graphNode(node.id), registry),
            inputTypes: Object.fromEntries(
              ((node.data as WfNodeData).inputs ?? []).map((key) => [
                key,
                inputType(registry, node.data.nodeType as string, key),
              ]),
            ),
          },
        };
      });
    },
    // registry / graph 也要在里面:缩略图和接点类型都读它们,漏了就一直是加载前的空值。
    [nodes, analysis, t, runByNode, nodeZ, registry, graph],
  );

  return (
    // 间距和别的页面一样是 8px:外框已经有 p-2,这里给 gap-2 就够,工具条自己不再另加
    // 上下内边距 —— 此前是 pb-2 pt-0.5(下 8 上 2),上下差四倍,顶栏看着往上贴。
    // **工具条浮在画布上,不再占一整行。** 画布因此从上到下是完整的一块 —— 此前顶上那条
    // 实心横带把可视区切掉一截,而工作流恰恰是越大越好看的东西。
    //
    // 没有照搬参考产品的左侧竖直悬浮栏:我们左边**已经有一条全局导航栏**,再加一条竖栏就是
    // 两条并排的竖条,用户得先分辨"哪条是应用的、哪条是这一页的"。所以横向成组、浮在顶部,
    // 保持"这一页的操作"和"整个应用的导航"在方向上就分得开。
    <div className="relative grid min-h-0">
      <div className="pointer-events-none absolute inset-x-2 top-2 z-20 flex flex-wrap items-start justify-between gap-2 [&>*]:pointer-events-auto">
        {/* 左边这组是**身份**(回哪儿去、这是谁),右边那组是**操作**。浮起来之后两组各自要有
            自己的底,否则它们会散在画布上,和节点抢注意力 —— 悬浮不等于没有边界。 */}
        <div className="flex items-center gap-1 rounded-full border border-border bg-panel/95 p-1 pr-2.5 shadow-[var(--shadow-panel)] backdrop-blur">
        {/* 返回键**给它一个底**。透明底的图标钮在胶囊里没有自己的轮廓,左边和胶囊边缘之间那点
            空白就显得忽大忽小 —— 有了底,它的占位是确定的,和右边的竖线、名字也就对齐了。 */}
        <Button
          variant="secondary"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={onBack}
          title={t("navWorkflows")}
          aria-label={t("navWorkflows")}
        >
          <ChevronLeft size={16} />
        </Button>
        {/* 返回和名字之间一根竖线:一个是"离开这里",一个是"这里是什么" —— 两件事,
            挨着放需要一道界。 */}
        <span aria-hidden className="mx-0.5 h-4 w-px shrink-0 bg-border" />
        {/* 工作流图标去掉了:左边导航栏里那一格已经亮着"工作流",顶上再画一次是同一句话说两遍,
            而这一格真正要回答的是"**哪一个**工作流"。 */}
        <button type="button" className="inline-flex cursor-pointer items-center rounded-full border-0 bg-transparent px-1.5 py-[3px] text-left text-ui-md font-semibold text-foreground hover:bg-secondary" onClick={() => setRenaming(true)} title={t("rename")}>
          {/* strong 的浏览器默认字重是 bolder(700),会**压过**外面的 font-semibold(600)——
              于是这块标题比创意画板左上角那块明显更粗,而两者是同一类东西。显式钉回 600。 */}
          <span className="grid leading-[1.3] [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:text-ui-md [&_strong]:font-semibold">
            <strong>{workflow.name}</strong>
            {/* 保存状态只放工具栏的 wf-save-status:标题里再挂一行「未保存」会随每次
                拖动→自动保存增删一行,撑动整条工具栏导致画布跳一下(闪烁)。 */}
          </span>
        </button>
        </div>
        {/* 右边按**作用对象**分组,每组自己一颗胶囊 —— 此前十来个按钮挤在一条里,只靠两道
            细竖线隔开,找一个键要从头扫到尾。分组是:编辑图 / 理解图 / 跑这张图 / 看的方式 /
            这份文档。竖线换成真正断开,因为断开比线更快被看见。 */}
        <div className="flex flex-wrap items-start justify-end gap-2">
        <div className="flex flex-wrap items-center gap-1 rounded-full border border-border bg-panel/95 p-1 shadow-[var(--shadow-panel)] backdrop-blur">
          {/* 工具条统一刻度:胶囊(rounded-full)、h-8、text-xs;图标钮 h-8 w-8。 */}
          <SearchableSelect
            value=""
            onValueChange={addNode}
            searchPlaceholder={t("wfAddNode")}
            options={nodeOptions.filter((option) => option.value !== "start" || !graphHasStart)}
            trigger={
              <button
                type="button"
                data-wf-add-node=""
                // 组里全是圆形图标钮,只有它带文字就会显得突出一截 —— 而它并不比「运行」更重要。
                // 名字进 title/aria-label,悬停仍然说得出自己是谁。
                className="grid h-8 w-8 place-items-center rounded-full border-0 bg-transparent text-foreground transition-colors hover:bg-secondary"
                aria-label={t("wfAddNode")}
                title={t("wfAddNode")}
              >
                <Plus size={15} />
              </button>
            }
          />
          <Button variant="ghost" size="icon" className="h-8 w-8" title={`${t("undo")} ⌘Z`} aria-label={t("undo")} disabled={!canUndo} onClick={undo}>
            <Undo2 size={14} />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" title={`${t("redo")} ⇧⌘Z`} aria-label={t("redo")} disabled={!canRedo} onClick={redo}>
            <Redo2 size={14} />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-1 rounded-full border border-border bg-panel/95 p-1 shadow-[var(--shadow-panel)] backdrop-blur">
          <Button
            variant="ghost"
            size="icon"
            className={cn("h-8 w-8", agentOpen && "bg-secondary text-foreground")}
            aria-label={t("wfAgentTitle")}
            title={t("wfAgentTitle")}
            aria-pressed={agentOpen}
            onClick={() => {
              setAgentOpen((value) => !value);
              if (!agentOpen) setAgentMode("docked");
            }}
          >
            <Bot size={14} />
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
                  className="h-8 pl-[30px] pr-2 text-ui-sm focus-visible:border-primary focus-visible:ring-0"
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
                        <span className="truncate text-ui-sm font-semibold text-foreground">{node.name || label}</span>
                        {typeSub && <span className="shrink-0 text-ui-xs text-muted-foreground">{typeSub}</span>}
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
                  // 组已经有自己的边框和底了,按钮**不再各带一层** —— 那是胶囊套胶囊。
                  // 状态靠颜色说,不靠再画一圈线。
                  "inline-flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border-0 bg-transparent text-xs font-[650] text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground",
                  checklistCount > 0 ? "gap-1 px-2" : "w-8 justify-center",
                  analysis.errorCount
                    ? "bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive hover:bg-[color-mix(in_srgb,var(--destructive)_18%,transparent)] hover:text-destructive"
                    : analysis.warnCount
                      ? "bg-[color-mix(in_srgb,#f59e0b_12%,transparent)] text-[#f59e0b] hover:bg-[color-mix(in_srgb,#f59e0b_18%,transparent)] hover:text-[#f59e0b]"
                      : "bg-[color-mix(in_srgb,#22c55e_10%,transparent)] text-[#22c55e] hover:bg-[color-mix(in_srgb,#22c55e_16%,transparent)] hover:text-[#22c55e]",
                )}
                aria-label={`${t("wfChecklist")}: ${checklistLabel}`}
                title={checklistLabel}
              >
                {/* **没问题时缩成一个图标。** "一切就绪"是无聊的默认态,不该占一整个词的宽度;
                    有问题时才值得展开 —— 那时数字才是要看的东西。
                    图标 + 文字 + 数字三样一起上,是同一个状态编码了三遍。 */}
                {checklistCount > 0 ? <AlertTriangle size={13} /> : <CircleCheck size={14} />}
                {checklistCount > 0 && (
                  <em className="inline-grid h-[15px] min-w-[15px] place-items-center rounded-full bg-[color-mix(in_srgb,currentColor_18%,transparent)] px-1 text-ui-2xs font-bold not-italic leading-none text-current">
                    {checklistCount}
                  </em>
                )}
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-1.5">
              {analysis.issues.length === 0 ? (
                <div className="flex items-center gap-1.5 p-2 text-ui-sm text-[#16a34a]">
                  <CircleCheck size={14} /> {t("wfChecklistReady")}
                </div>
              ) : (
                <>
                  <div className="px-2 pb-1.5 pt-1 text-ui-xs font-semibold uppercase tracking-[0.04em] text-muted-foreground">
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
                          <span className="truncate text-ui-xs text-muted-foreground">{issueText(t, issue)}</span>
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
            size="icon"
            className="h-8 w-8"
            disabled={dirty || !analysis.runnable} loading={run.isPending}
            aria-label={t("wfRun")}
            title={dirty ? t("wfSaving") : !analysis.runnable ? t("wfRunBlocked") : t("wfRun")}
            onClick={() => run.mutate()}
          >
            <Play size={14} />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-1 rounded-full border border-border bg-panel/95 p-1 shadow-[var(--shadow-panel)] backdrop-blur">
          {/* 走线方式:四种够用,直接摆成一排图标钮而不是下拉 —— 它是"试一下看哪种顺眼"的
              设置,藏进下拉就得点两次才能比较一次。 */}
          {/* **不再套一个方框。** 分段控件自带 rounded-md 边框,而外层组是 rounded-full ——
              方框套胶囊,两种圆角打架,而且组里别的按钮都是圆的。选中态用填色表达就够了,
              不需要再画一圈线把它们框起来。 */}
          <div className="flex items-center gap-1">
            {EDGE_SHAPES.map((shape) => {
              const Icon = EDGE_SHAPE_ICON[shape];
              return (
                <Button
                  key={shape}
                  variant={edgeShape === shape ? "secondary" : "ghost"}
                  size="icon"
                  className={cn("h-8 w-8", edgeShape === shape && "bg-secondary text-foreground")}
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
          {/* 全览可关。它占着右下角一块不小的地方,图小的时候纯属挡视线;而图大的时候
              又是最有用的东西 —— 所以给开关,不替用户决定。记在本地,下次进来还是这个样子。 */}
          <Button
            variant="ghost"
            size="icon"
            className={cn("h-8 w-8", showMinimap && "bg-secondary text-foreground")}
            aria-label={t("wfMinimap")}
            title={t("wfMinimap")}
            aria-pressed={showMinimap}
            onClick={() => setShowMinimap(showMinimap ? "off" : "on")}
          >
            <MapIcon size={14} />
          </Button>
          {/* 全览:把整张图框回视野里。此前它藏在左下角 React Flow 自带的那组控件里,
              而那组控件被撤掉了 —— 缩放有触控板和滚轮,「我找不到我的图了」却只有它能解。 */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={t("boardsFitView")}
            title={t("boardsFitView")}
            onClick={() => rfRef.current?.fitView({ padding: 0.3, duration: 250 })}
          >
            <Maximize2 size={14} />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-1 rounded-full border border-border bg-panel/95 p-1 shadow-[var(--shadow-panel)] backdrop-blur">
          {/* 导出。**放在这一组**(历史/删除)而不是运行旁边:这几个都是对"这份工作流"整体
              做的事,而运行、就绪检查、加节点是对**画布内容**做的事。此前导出只藏在列表页的
              右键菜单里 —— 而人想导出的时机,恰恰是刚在详情页里把它调好的那一刻。 */}
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("wfExport")}
            title={t("wfExport")}
            className="h-8 w-8"
            loading={exportFile.isPending}
            onClick={() => exportFile.mutate()}
          >
            <Download size={14} />
          </Button>
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
      </div>

      <div className={cn(
        "relative grid min-h-0 grid-cols-[minmax(0,1fr)] gap-2 [&_.react-flow\_\_background]:bg-background [&_.react-flow\_\_controls]:overflow-hidden [&_.react-flow\_\_controls]:rounded-md [&_.react-flow\_\_controls]:border [&_.react-flow\_\_controls]:border-border [&_.react-flow\_\_controls]:shadow-none [&_.react-flow\_\_controls-button]:border-b [&_.react-flow\_\_controls-button]:border-border [&_.react-flow\_\_controls-button]:bg-panel [&_.react-flow\_\_controls-button]:text-foreground [&_.react-flow\_\_controls-button:hover]:bg-secondary [&_.react-flow\_\_edge-path]:stroke-border-strong [&_.react-flow\_\_edge-path]:[stroke-width:1.5] [&_.react-flow\_\_edge-path]:[stroke-linecap:round] [&_.react-flow\_\_edge-path]:[transition:stroke_120ms,stroke-width_120ms] [&_.react-flow\_\_edge.selected_.react-flow\_\_edge-path]:stroke-primary [&_.react-flow\_\_edge.selected_.react-flow\_\_edge-path]:[stroke-width:2.2] [&_.react-flow\_\_edge:hover_.react-flow\_\_edge-path]:[stroke-width:2.2] [&_.react-flow\_\_edge-textbg]:fill-panel [&_.react-flow\_\_edge-text]:fill-muted-foreground [&_.react-flow\_\_edge-text]:text-[9.5px] [&_.react-flow\_\_attribution]:bg-transparent [&_.react-flow\_\_attribution]:text-muted-foreground [&_.wf-edge-true_.react-flow\_\_edge-path]:stroke-[#16a34a] [&_.wf-edge-false_.react-flow\_\_edge-path]:stroke-[#e11d48] [&_.wf-edge-data_.react-flow\_\_edge-path]:animate-wf-dash [&_.wf-edge-data_.react-flow\_\_edge-path]:stroke-primary [&_.wf-edge-data_.react-flow\_\_edge-path]:[stroke-width:2] [&_.wf-edge-data_.react-flow\_\_edge-path]:[stroke-dasharray:6_5] [&_.wf-edge-data.selected_.react-flow\_\_edge-path]:[stroke-width:2.6] [&_.wf-edge-data.wf-edge-mismatch_.react-flow\_\_edge-path]:stroke-[#d97706] [&_.react-flow\_\_minimap]:overflow-hidden [&_.react-flow\_\_minimap]:rounded-md [&_.react-flow\_\_minimap]:border [&_.react-flow\_\_minimap]:border-border [&_.react-flow\_\_minimap]:bg-background [&_.react-flow\_\_minimap-mask]:fill-[color-mix(in_srgb,var(--foreground)_6%,transparent)] [&_.react-flow\_\_minimap-node]:fill-border-strong",
      )}
        // 画布**始终占满**:助手和执行历史改成浮在上面,不再从画布身上切走一列。
        // 工具条已经浮起来了,右边再留一条实心栏,画布就被两面夹住 —— 而这一页的主角是画布。
      >
        {/* 画布和右栏之间的拖柄。右栏是从右往左量的,所以给 right 而不是 left。 */}
        {/* 拖柄:面板浮起来之后它不再是"两栏之间的界",而是浮窗自己的左边缘 —— 所以贴着
            浮窗左侧,并跟着浮窗一起压在画布上(z-10),否则会被画布吃掉指针事件。 */}
        {rightPanels > 0 && (
          <div
            className={cn(SIDEBAR_HANDLE_CLASS, "z-10")}
            style={{ right: rightPanel.width + 8, top: 54, bottom: 8 }}
            onPointerDown={rightPanel.startDragFromRight}
          />
        )}
        {/* 从访达直接把视频/图片拖进画布:先进素材库,再在**落点**放一个「素材」节点。
            省掉「先去素材页上传 → 回来找那个 id」那一圈。 */}
        <div
          //: 底色和创意画板那张画布同一个(bg-background)—— 两者都是「摊开东西的地方」,
          //: 而 bg-panel 是「一块面板」。用两种底色的话,在两页之间切换会觉得走进了另一个应用。
          className="relative min-h-0 overflow-hidden rounded-lg border border-border bg-background"
          {...canvasDrop.handlers}
          onDrop={(event) => {
            // 落点要在这一刻算 —— 只有事件里才有鼠标位置。存进 ref 给上面那个回调用。
            const instance = rfRef.current;
            pendingDropAt.current = instance
              ? instance.screenToFlowPosition({ x: event.clientX, y: event.clientY })
              : null;
            canvasDrop.handlers.onDrop(event);
          }}
        >
          {/* inset-0 一点不留:留边就会在四角露出没被盖住的缝。虚线框收到中间那块提示上,
              而不是描在整块区域的边上 —— 后者会和画布自己的圆角错开。 */}
          {(canvasDrop.active || dropUpload.isPending) && (
            // **要盖过画布上的一切**,包括节点检查器那张浮层(z-30)和子流程面板(同样 z-30)。
            // z-20 的时候,选中某个节点再拖文件进来,检查器就压在提示上面 —— 用户看到的是
            // 半块被切掉的虚线框,不知道松手到底会发生什么。拖拽反馈是**全局态**,不该和
            // 画布里某个局部面板比高矮。
            <div className="pointer-events-none absolute inset-0 z-40 grid place-items-center rounded-lg bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
              <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
                {dropUpload.isPending ? (
                  <>
                    <Loader2 size={20} className="animate-openstudio-spin" />
                    {t("mediaDropUploading")}
                  </>
                ) : (
                  <>
                    <FileUp size={20} />
                    {t("wfDropHint")}
                  </>
                )}
              </span>
            </div>
          )}
          <ReactFlow
            className={cn("[--xy-attribution-background-color:color-mix(in_srgb,var(--panel)_70%,transparent)]", !canvas.ready && "opacity-0")}
            nodes={displayNodes}
            edges={displayEdges}
            nodeTypes={NODE_COMPONENT_TYPES}
            onInit={(instance) => {
              rfRef.current = instance as unknown as ReactFlowInstance;
              // 只在挂载时定位一次(切换工作流会因 key 重挂而重跑)。用命令式而非声明式
              // fitView 属性:后者会在每次新增未测量节点时重新 fit,把手动聚焦覆盖掉。
              // 定位完成前画布不可见:首帧按默认视口渲染会让所有节点在错位处闪一下。
              //
              // **上次停在哪儿就回哪儿**,只有第一次进来才 fitView。此前每次刷新/重进都 fit,
              // 把所有节点框回视野 —— 图一大,用户每次回来都得重新找到刚才在看的那一块,
              // 而他离开时的位置本来就是最有价值的信息。
              requestAnimationFrame(() => {
                if (viewport.saved) instance.setViewport(viewport.saved);
                else instance.fitView({ padding: 0.25, maxZoom: 1 });
                canvas.handlers.onInit();
              });
            }}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onMoveStart={canvas.handlers.onMoveStart}
            onMove={canvas.handlers.onMove}
            onMoveEnd={(event, next) => {
              canvas.handlers.onMoveEnd();
              viewport.remember(next);
            }}
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
                  // **select-none**:它出现的时机正是框选拖拽刚结束的那一刻,而那一下拖拽会把
                  // 按钮上的字一起选中 —— 于是文字顶着一层系统选区的紫色,看着像坏了。
                  className="inline-flex select-none items-center gap-1.5 rounded-full border border-input bg-card px-3 py-1.5 text-xs font-medium text-foreground shadow-sm hover:bg-muted"
                  title={`${t("wfCollapseHint")} ⌘G`}
                >
                  <Boxes size={13} /> {t("wfCollapseToSubgraph").replace("{n}", String(selectedFlowIds.length))}
                </button>
              </Panel>
            )}
            <Background gap={20} size={1.2} />
            {/* 缩放钮/预览图不吃应用主题(xyflow 默认一律白底),把 --xy-* 变量
                映射到设计令牌,昼夜两版都跟着色板走;投影按全局规范去掉。 */}
            {showMinimap && <MiniMap
              pannable
              zoomable
              position="bottom-right"
              className="overflow-hidden rounded-md border border-border"
              bgColor="var(--panel)"
              maskColor="color-mix(in srgb, var(--background) 55%, transparent)"
              nodeColor="var(--border-strong)"
              nodeStrokeColor="transparent"
            />}
        {selectedNode && !editingLoopId && (
          <NodeInspector
            inert={canvas.panning}
            step={runByNode[selectedNode.id] ?? null}
            node={selectedNode}
            meta={registry.get(selectedNode.type) ?? null}
            graph={graph}
            registry={registry}
            workspaceId={workspaceId}
            onChange={(patch) => {
              // **打字是连发,不是离散编辑。** 每敲一个字符记一条历史的话,Cmd+Z 一次只退回
              // 一个字母 —— 用户以为撤销坏了,其实是它太尽责。用拖拽那同一套合并机制:
              // 一串输入在历史里塌成一条,存的是这串开始前的图(见 stores/workflowGraphStore)。
              //
              // 只有改文字才合并;改开关、换下拉那些仍然一步一条 —— 它们本来就是离散的。
              const typing = "config" in patch || "name" in patch;
              applyGraph(
                {
                  ...graph,
                  nodes: graph.nodes.map((node) => (node.id === selectedNode.id ? { ...node, ...patch } : node)),
                },
                { coalesce: typing },
              );
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
            onDrillIn={
              selectedNode.type === "subgraph" || selectedNode.type.startsWith("loop_")
                ? () => setEditingLoopId(selectedNode.id)
                : undefined
            }
            onClose={() => setSelectedNodeId(null)}
          />
        )}
          </ReactFlow>
        </div>
        {/* 右栏:助手与执行历史共用。两个都开就上下平分 —— 运行时经常要一边看画布状态、
            一边翻某一步的输出。助手切到浮动模式时自己脱离文档流,所以只按停靠中的个数分行。 */}
        {(dockedAgent || dockedHistory) && (
          <div
            className={cn(
              // 浮窗:贴右侧,从工具条底下起、到画布底边止。z-10 —— 压过画布,让过工具条(z-20)
              // 和节点检查器(z-30):检查器是"你正在改的那个东西",它该在最上面。
              "absolute bottom-2 right-2 top-[54px] z-10 grid min-h-0 min-w-0 gap-2",
              dockedAgent && dockedHistory ? "grid-rows-[minmax(0,1fr)_minmax(0,1fr)]" : "grid-rows-[minmax(0,1fr)]",
            )}
            // 两个都开时上面那块用记住的高度,下面那块吃掉剩下的 —— 运行时想看某一步的输出
            // 就把历史那块拉大,而平分是个谁都不满意的折中。
            style={{
              width: rightPanel.width,
              ...(dockedAgent && dockedHistory
                ? { gridTemplateRows: `${agentRow.height}px minmax(0,1fr)` }
                : {}),
            }}
          >
            {dockedAgent && agentPanel}
            {/* 上下之间的横拖柄。和左右那条同一套外观(HANDLE_ROW),只是转了九十度。 */}
            {dockedAgent && dockedHistory && (
              <div
                className={ROW_HANDLE_CLASS}
                style={{ top: handleOffset(agentRow.height) }}
                onPointerDown={agentRow.startDrag}
              />
            )}
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
                workflowId={workflow.id}
                loopNode={loopNode}
                registry={registry}
                nodeTypes={nodeTypes}
                workspaceId={workspaceId}
                canUndo={canUndo}
                canRedo={canRedo}
                undo={undo}
                redo={redo}
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
  /** 这个字段的值跟着谁走(后端 NODE_TYPES 声明)。父字段一换,这里的旧值就失效了。 */
  depends_on?: string;
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
              className="cursor-pointer rounded-md border border-border bg-[color-mix(in_srgb,var(--primary)_6%,transparent)] px-1.5 py-px font-mono text-ui-2xs text-primary transition-[border-color,background] duration-100 hover:border-primary hover:bg-[color-mix(in_srgb,var(--primary)_12%,transparent)]"
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
  workflowId,
  loopNode,
  registry,
  nodeTypes,
  workspaceId,
  onChange,
  onClose,
  canUndo,
  canRedo,
  undo,
  redo,
}: {
  /** 只用来给「子图停在哪儿」当存储键 —— 节点 id 在不同工作流里会重名。 */
  workflowId: string;
  loopNode: WorkflowGraph["nodes"][number];
  registry: Map<string, WorkflowNodeType>;
  nodeTypes: WorkflowNodeType[];
  workspaceId: string;
  onChange: (body: WorkflowGraph) => void;
  onClose: () => void;
  /** 撤销/重做走主图那一套 —— 子图的每次编辑本来就是主图的一次变更。 */
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
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
  const [edges, setEdges] = React.useState<Edge[]>(() => toFlowEdges(initialBody, t, registry));
  // 循环体编辑器读同一个偏好:主画布是圆角折线、点进循环体却变回贝塞尔,会让人以为进错了地方。
  const [edgeShape, setEdgeShape] = usePersistentTab<EdgeShape>("wf-edge-shape", "default", EDGE_SHAPES);
  const shapedEdges = React.useMemo(
    () => edges.map((edge) => (edge.type === edgeShape ? edge : { ...edge, type: edgeShape })),
    [edges, edgeShape],
  );
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  /**
   * 子图里的检查器**和主图长一样**。
   *
   * 这里此前不传 anchor,于是走了"贴右边占满整条高度"的兜底样式 —— 同一个东西在主图是贴着
   * 节点浮现的小面板,进了子图变成一条右侧长栏,还把工具条右边那组盖住。用户会以为自己进错了
   * 地方,而这只是少传了一个参数。
   */
  const subRf = React.useRef<ReactFlowInstance | null>(null);
  //: 和主图同一套画布姿态。**平移/缩放时把检查器设成 inert** —— 否则滚轮滚到面板上就被它吃掉,
  //: 画布停住不动:用户以为滚坏了,其实是指针从画布挪到了浮层上。
  const subCanvas = useCanvasPosture();
  // 子图按「哪张工作流的哪个节点」各记各的。
  const subViewport = usePersistentViewport(`workflow:${workflowId}:${loopNode.id}`);

  //: 最后一次**我们自己发出去**的 body。用来分辨"这次 prop 变化是我引起的"还是"外面改的"。
  const emitted = React.useRef<string>("");

  const commit = React.useCallback(
    (next: WorkflowGraph) => {
      setBody(next);
      setNodes(toFlowNodes(next, registry));
      setEdges(toFlowEdges(next, t, registry));
      emitted.current = JSON.stringify(next);
      onChange(next);
    },
    [registry, onChange],
  );

  /**
   * **外面改了 body 就跟上。**
   *
   * 子图的每次编辑本来就走主图的 applyGraph(body 存在父节点的 config 里),所以撤销栈里
   * 一直记着它 —— 缺的不是历史,是这一层不听外面的话:body 只在挂载时取一次,撤销把主图
   * 改回去了,覆盖层还显示着改之前的样子。用户按下 Cmd+Z,画面纹丝不动,再按一次就退过头了。
   *
   * 只在**不是自己发出去的那一版**时才跟 —— 否则每次自己的编辑都会被 prop 回流覆盖一遍,
   * 打字打到一半光标就跳。
   */
  React.useEffect(() => {
    const incoming = JSON.stringify(initialBody);
    if (incoming === emitted.current) return;
    emitted.current = incoming;
    setBody(structuredClone(initialBody));
    setNodes(toFlowNodes(initialBody, registry));
    setEdges(toFlowEdges(initialBody, t, registry));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialBody, registry]);

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
    // 工具条和主编辑器一样浮在画布上 —— 子图也是画布,没有理由这里就顶一条实心横带。
    //: 底色用 bg-background,和创意画板那张画布同一个 —— 画布是「摊开东西的地方」,
    //: 而 bg-panel 是「一块面板」;两种画布用两种底色,切过去时会觉得走进了另一个应用。
    <div className="absolute inset-0 z-30 grid overflow-hidden rounded-lg border border-border bg-background">
      <div className="pointer-events-none absolute inset-x-2 top-2 z-20 flex flex-wrap items-start justify-between gap-2 [&>*]:pointer-events-auto">
        <div className="flex items-center gap-1 rounded-full border border-border bg-panel/95 p-1 pr-2.5 shadow-[var(--shadow-panel)] backdrop-blur">
          <Button
            variant="secondary"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={onClose}
            aria-label={t("wfLoopBack")}
            title={t("wfLoopBack")}
          >
            <ArrowLeft size={16} />
          </Button>
          <span aria-hidden className="mx-0.5 h-4 w-px shrink-0 bg-border" />
          {/* 字号字重和创意画板左上角那块一致(text-ui-md / semibold)—— 它们是同一类东西:
              「你现在在哪儿」。 */}
          <span className="inline-flex items-center gap-[5px] text-ui-md font-semibold text-foreground">
            {loopNode.type === "subgraph" ? <Boxes size={13} /> : <Repeat size={13} />} {loopNode.name} ·{" "}
            {t(loopNode.type === "subgraph" ? "wfSubgraphBody" : "wfLoopBody")}
          </span>
        </div>
        {/* 这里**只放子图自己用得上的**:加节点、走线方式。
            运行 / 就绪检查 / 导出 / 历史 / 删除都是主图或整份文档的事,放进来只会让人以为
            自己能在子图里跑一次;撤销也没有 —— 子图编辑器没有历史栈,画一个按钮却不能用,
            比没有更糟。 */}
        <div className="flex flex-wrap items-center gap-1 rounded-full border border-border bg-panel/95 p-1 shadow-[var(--shadow-panel)] backdrop-blur">
          <SearchableSelect
            value=""
            onValueChange={addNode}
            searchPlaceholder={t("wfAddNode")}
            options={subOptions.filter((option) => option.value !== "start")}
            trigger={
              <button
                type="button"
                className="grid h-8 w-8 place-items-center rounded-full border-0 bg-transparent text-foreground transition-colors hover:bg-secondary"
                aria-label={t("wfAddNode")}
                title={t("wfAddNode")}
              >
                <Plus size={15} />
              </button>
            }
          />
          {/* 撤销/重做走的是**主图那一套历史** —— 子图的每次编辑本来就是主图的一次变更
              (body 存在父节点的 config 里),所以这里不该另开一个栈:两个栈会各记各的,
              退出子图之后再按撤销,退回去的是哪一步就说不清了。 */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            title={`${t("undo")} ⌘Z`}
            aria-label={t("undo")}
            disabled={!canUndo}
            onClick={undo}
          >
            <Undo2 size={14} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            title={`${t("redo")} ⇧⌘Z`}
            aria-label={t("redo")}
            disabled={!canRedo}
            onClick={redo}
          >
            <Redo2 size={14} />
          </Button>
          <span aria-hidden className="mx-0.5 h-4 w-px shrink-0 bg-border" />
          {EDGE_SHAPES.map((shape) => {
            const Icon = EDGE_SHAPE_ICON[shape];
            return (
              <Button
                key={shape}
                variant={edgeShape === shape ? "secondary" : "ghost"}
                size="icon"
                className={cn("h-8 w-8", edgeShape === shape && "bg-secondary text-foreground")}
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
          onInit={(instance) => {
            subRf.current = instance as unknown as ReactFlowInstance;
            subCanvas.handlers.onInit();
            requestAnimationFrame(() => {
              if (subViewport.saved) instance.setViewport(subViewport.saved);
              else instance.fitView({ padding: 0.3, maxZoom: 1 });
              setBodyViewReady(true);
            });
          }}
          onMoveStart={subCanvas.handlers.onMoveStart}
          onMove={subCanvas.handlers.onMove}
          onMoveEnd={(event, next) => {
            subCanvas.handlers.onMoveEnd();
            subViewport.remember(next);
          }}
          // 和主图一致:署名照常显示 —— 隐藏它是 Pro 授权才允许的事,不能因为"看着干净"就关掉。
          proOptions={{ hideAttribution: false }}
        >
          <Background gap={20} size={1.2} />
        {selectedNode && (
          <NodeInspector
            inert={subCanvas.panning}
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
        </ReactFlow>
        {body.nodes.length === 0 && <div className="pointer-events-none absolute left-1/2 top-4 max-w-[70%] -translate-x-1/2 rounded-lg border border-dashed border-border bg-muted px-3 py-2 text-center text-xs text-muted-foreground">{t(loopNode.type === "subgraph" ? "wfSubgraphEmptyHint" : "wfLoopEmptyHint")}</div>}
      </div>
    </div>
  );
}

function NodeInspector({
  inert = false,
  step = null,
  node,
  meta,
  graph,
  registry,
  workspaceId,
  onChange,
  onApplyGraph,
  onDelete,
  onDrillIn,
  onClose,
}: {
  /** 画布正在平移:此时面板不吃指针事件(见 WorkflowsView 里 panning 的说明)。 */
  inert?: boolean;
  /** 这个节点在**最近一次运行**里的那一步。没跑过就是 null。 */
  step?: Step | null;
  node: WorkflowGraph["nodes"][number];
  meta: WorkflowNodeType | null;
  graph: WorkflowGraph;
  registry: Map<string, WorkflowNodeType>;
  workspaceId: string;
  onChange: (patch: Partial<WorkflowGraph["nodes"][number]>) => void;
  onApplyGraph: (next: WorkflowGraph) => void;
  onDelete?: () => void;
  /** 只有子图 / 循环节点给 —— 双击进子画布的那件事,在悬浮键上也给一个入口。 */
  onDrillIn?: () => void;
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
  const hasAssetField = specs.some(([, spec]) => fieldDataType(spec) === "asset");
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

  // 换了父字段就清掉依赖它的子字段 —— 规则抽在 dependents.ts(有测试),这里只负责接线。
  const setConfig = (key: string, value: unknown) =>
    onChange({ config: withDependentsCleared(config, key, value, (meta?.config ?? {}) as Record<string, ConfigSpec>) });
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
  /**
   * 该模型声明支持的参数。两种形状:
   *
   * - **枚举** —— 从若干可选值里挑一个(分辨率、宽高比);
   * - **区间** —— min..max 内的任意整数(时长)。Seedance 2 收 4–15 秒,写成枚举就只剩
   *   两个档,而用户看不出少了什么。
   */
  const genParamKeys: GenField[] = React.useMemo(() => {
    if (!genModel) return [];
    const out: GenField[] = [];
    const ratios = aspectRatioOptions(genModel);
    if (ratios.length > 0) out.push({ key: "aspect_ratio", label: t("wfGenAspectRatio"), options: ratios });
    if (genModel.kind === "image") {
      const sizes = sizeOptions(genModel);
      if (sizes.length > 0) out.push({ key: "size", label: t("wfGenSize"), options: sizes });
      // 一次出几张。此前工作流里没有这一栏 —— 而它是图像那边最常调的一个,
      // 生成面板有、节点没有,同一个模型两处能力不一样。
      const images = maxImages(genModel);
      if (supportsParameter(genModel, "num_images") && images > 1) {
        out.push({ key: "num_images", label: t("wfGenNumImages"), options: [], range: { min: 1, max: images } });
      }
    } else {
      const resolutions = videoResolutionOptions(genModel);
      if (resolutions.length > 0) out.push({ key: "resolution", label: t("wfGenResolution"), options: resolutions });
      const durations = durationOptions(genModel);
      if (durations.length > 0) {
        out.push({ key: "duration_seconds", label: t("wfGenDuration"), options: durations.map(String) });
      } else {
        // 枚举为空 = 这是个区间。上下界从描述符来 —— 写死的话,界面允许的值供应商会当场拒。
        const range = durationRange(genModel);
        if (range) out.push({ key: "duration_seconds", label: t("wfGenDuration"), options: [], range });
      }
    }
    // 开关类。**只在模型声明了的时候出现** —— 声明即接口,这里不按 kind 猜。
    for (const [key, labelKey] of TOGGLE_PARAMS) {
      if (supportsParameter(genModel, key)) out.push({ key, label: t(labelKey), options: [], toggle: true });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genModel]);

  /** 配置里那段 `id:role` 文本,解析成一条条素材。 */
  const genSourceLines = React.useMemo(
    () => parseSourceAssets(String(config.source_assets ?? "")),
    [config.source_assets],
  );
  /** 这个模型认哪几种素材角色 —— 描述符说了算,不按 kind 猜。 */
  const genSourceRoles = React.useMemo(
    () => (genModel ? SOURCE_ROLE_ORDER.filter((role) => supportsParameter(genModel, role)) : []),
    [genModel],
  );
  const genExtraSourceLines = React.useMemo(
    () => extraLines(genSourceLines, genSourceRoles as readonly string[]),
    [genSourceLines, genSourceRoles],
  );

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
    if (fieldDataType(spec as ConfigSpec | undefined) === "asset") {
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

  // ── 功能区 ──────────────────────────────────────────────────────────────
  // 节点上方那条悬浮键分两组(中间一道竖线):左边是**这个节点有哪几块内容**,点了换下面
  // 面板的内容;右边是**能对这个节点做什么**。
  //
  // 分的是**节点的内容块**,不是表单字段 —— 按字段分会把一份表单切碎(「提示词」「模型」
  // 各自一段),而表单本来就该整份读。参数区里的字段一个不拆。
  //
  // 「预览」不在这儿:产出预览已经通栏长在节点卡片上,面板里再来一份就是同一张图上下叠两遍。
  const areas: string[] = [];
  if (specs.length > 0) areas.push("config");
  // 「高级」自成一档,而不是正文底下一个折叠块:折叠块把「有没有更多可调的」藏在一次点击后面,
  // 而条上摆着就一眼看得见。**有才出** —— 没有高级项的节点条上不会多这一档。
  if (specs.some(([, spec]) => spec?.advanced)) areas.push("advanced");
  if (meta && meta.outputs.length > 0) areas.push("outputs");
  if (step) areas.push("run");
  const [pickedArea, setPickedArea] = React.useState<string | null>(null);
  // 派生而不是同步:换节点时 areas 变了,上一个节点选中的那块可能根本不存在 —— 直接回落到
  // 第一块,不需要一个 effect 追着清空(那种 effect 总慢一帧,会先露出一个空面板)。
  const area = pickedArea && areas.includes(pickedArea) ? pickedArea : areas[0];
  const AREA_LABELS: Record<string, MessageKey> = { config: "wfaConfig", advanced: "wfAdvanced", outputs: "wfOutputs", run: "wfRunOutputs" };


  /** 一个配置字段的渲染。抽出来是因为要渲染两遍:基础项直接铺开,高级项收进折叠区。 */
  const renderField = ([key, spec]: [string, ConfigSpec]) => {
          // 循环体 / 子图都是内嵌子图(graph 类型):不铺原始 JSON 文本框,给个只读概览(子画布编辑见 L3)。
          if (spec?.type === "graph") {
            const bodyNodes = ((config[key] as { nodes?: unknown[] } | undefined)?.nodes ?? []).length;
            const isSubgraph = node.type === "subgraph";
            return (
              <div className={FIELD_BOX} key={key}>
                <label>{t(isSubgraph ? "wfSubgraphBody" : "wfLoopBody")}</label>
                <div className="rounded-md border border-dashed border-border bg-muted px-2.5 py-2 text-ui-xs leading-normal text-muted-foreground">{t(isSubgraph ? "wfSubgraphBodyNote" : "wfLoopBodyNote").replace("{n}", String(bodyNodes))}</div>
              </div>
            );
          }
          const value = config[key];
          const isObject = spec?.type === "object";
          const options = spec?.options
            ? spec.options.map((option) => ({ value: option, label: option }))
            : dynamicOptions(key, spec as { plugin_instances?: boolean } | undefined);
          // 标签**优先用声明里带来的那个**(后端 domain/workflows.config_label,插件节点也有);
          // FIELD_LABEL_KEYS 是本地那张老表,留作回落,最后才退到裸键名。
          const declaredLabel = String((spec as { label?: unknown } | undefined)?.label ?? "").trim();
          const labelKey = FIELD_LABEL_KEYS[key];
          // ComfyUI 式:非 object 字段都可切到"连接"(暴露输入接点,再从画布拖数据边或下拉选源)。
          const canConnect = !isObject;
          const connected = canConnect && connectedInputs.includes(key);
          const boundEdge = connected ? dataEdgeFor(key) : null;
          const boundValue = boundEdge ? `${boundEdge.source}.${boundEdge.source_output}` : "";
          return (
            <div className={FIELD_BOX} key={key}>
              <span>
                {declaredLabel || (labelKey ? t(labelKey) : key)}
                {spec?.required ? <em className="font-bold not-italic text-destructive">*</em> : null}
                {canConnect && (
                  <button
                    type="button"
                    className={cn(
                      "ml-auto inline-flex cursor-pointer items-center gap-[3px] rounded-full border border-border bg-transparent px-1.5 py-px text-ui-2xs font-medium text-muted-foreground transition-[border-color,color,background] duration-100 hover:border-border-strong hover:text-foreground",
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
                // 「名字 → 值」的映射给一行一对的编辑器,值那格能从上游输出里挑;
                // 真正自由结构的(json_schema)才留原始 JSON。哪种由声明说了算,见后端 config_editor。
                String((spec as { editor?: unknown } | undefined)?.editor ?? "") === "json" ? (
                  <JsonField value={value} onChange={(parsed) => setConfig(key, parsed)} />
                ) : (
                  <MapField
                    value={value}
                    variables={variables}
                    onChange={(next) => setConfig(key, next)}
                  />
                )
              ) : spec?.type === "code" ? (
                <CodeField value={String(value ?? "")} onChange={(next) => setConfig(key, next)} variables={variables} />
              ) : spec?.type === "template" ? (
                // 模板字段:多行,而且里面的 `{{上游.输出}}` 显示成**可整体删除的标签** ——
                // 纯文本时退格会把它咬成 `{{llm-1.tex`,而半截引用在运行前看不出错。
                <RefEditor
                  rows={2}
                  value={String(value ?? "")}
                  onChange={(next) => setConfig(key, next)}
                  variables={variables}
                  placeholder={spec?.description ? undefined : t("wfRefEditorHint")}
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
              {spec?.description && <small>{spec.description}</small>}
            </div>
          );
  };

  /**
   * **住在画布里,大小不跟着缩放变。**
   *
   * 此前它是 position:fixed 的屏幕层浮层,而节点在画布坐标系里 —— 两个坐标系,于是每次平移
   * 缩放都要把节点位置换算成屏幕位置、再夹进窗口。那套换算前后修了三轮:四条边一起越界
   * (摆放按 320 算而面板其实是 380)、拿"高度上限"当实际高度用、子图漏传参数整个走成另一种
   * 样式。三条都是同一个错配的不同发作点。
   *
   * NodeToolbar 正是这件事的原语:渲染在 react-flow 的 viewport portal 里(**和节点同层**),
   * 位置用 viewport.zoom 算所以跟着节点走,但元素本身不缩放 —— 缩到 40% 时面板还是这么大、
   * 还能填表单。换算、四边钳制、量高度那一整套因此全部删掉。
   */
  return (
    <>
    {/* 节点悬浮键,分两组、中间一道竖线(tapnow 那条也是这么断的):
          左边 = **这个节点有哪几块内容**(点了换下面面板的内容),右边 = **能对它做什么**。
        两组都按"有才出":没跑过就没有「本次产出」,不是子图就没有「进入子图」。
        和面板一样长在画布坐标系里,所以同样要挂 nodrag/nopan —— 不然按下去是在拖节点。 */}
    <NodeToolbar nodeId={node.id} isVisible position={Position.Top} align="center" offset={12}>
      <div className="nodrag nopan flex items-center gap-0.5 rounded-full border border-border-strong bg-panel px-1 py-1 shadow-[var(--shadow-panel)]">
        {areas.map((id) => (
          <button
            key={id}
            type="button"
            className={cn(
              "cursor-pointer rounded-full px-3 py-1.5 text-ui-xs font-medium transition-[background,color] duration-100",
              area === id
                ? "bg-secondary text-foreground"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
            onClick={() => setPickedArea(id)}
          >
            {t(AREA_LABELS[id])}
          </button>
        ))}
        {/* 竖线只在两边都有东西时才画 —— 否则它分隔的是"一组和空气"。 */}
        {areas.length > 0 && (onDrillIn || onDelete) && (
          <span aria-hidden className="mx-1 h-4 w-px bg-border" />
        )}
        {onDrillIn && (
          <button
            type="button"
            className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground transition-[background,color] duration-100 hover:bg-secondary hover:text-foreground"
            aria-label={t("wfaEnterSubgraph")}
            title={t("wfaEnterSubgraph")}
            onClick={onDrillIn}
          >
            <Boxes size={14} />
          </button>
        )}
        {onDelete && (
          <button
            type="button"
            className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground transition-[background,color] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive"
            aria-label={t("delete")}
            title={t("delete")}
            onClick={onDelete}
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </NodeToolbar>
    {/* 面板在节点**正下方**、分段条在正上方 —— 上下夹着节点,而不是挤在右边。
        居中对齐:节点是这两块的锚,偏在一侧看起来像是飘着的另一个东西。 */}
    <NodeToolbar nodeId={node.id} isVisible position={Position.Bottom} align="center" offset={12}>
    <aside
      className={cn(
        // 380 而不是 320:两列并排的参数(Temperature / Top P 这种)在 320 里各自只剩 130px,
        // 长一点的标签就换行。
        "grid max-h-[560px] min-h-0 w-[380px] grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-xl border border-border-strong bg-panel shadow-[var(--shadow-panel)]",
        // **搬进画布之后必须挂这三个。** 面板现在长在 React Flow 里面,而画布自己要监听
        // pointerdown 来平移、滚轮来缩放 —— 不声明的话这些事件在到达输入框之前就被画布截走:
        // 点输入框不聚焦、打字没反应、下拉点不开。此前面板是 fixed 在画布外面的,画布看不到
        // 这些事件,所以从来不需要声明,搬进来才暴露。
        //   nodrag  —— 在面板里按下不要拖动节点/框选
        //   nopan   —— 不要平移画布
        //   nowheel —— 面板内滚动是滚它自己,不是缩放画布
        // 另外 viewport-portal 整个 user-select:none,面板里要能选中文字得显式改回来。
        "nodrag nopan nowheel select-text",
        inert && "pointer-events-none",
      )}
      aria-label={node.name || meta?.label || node.type}
    >
      <div // 头部只有一行(类型进了图标的 tooltip),38px 是给两行留的高度。
        className="flex min-h-9 items-center justify-between gap-2 border-b border-border px-2.5 py-1.5">
        {/* 节点说明挂在图标上,不占正文一行 —— 那句话每个节点都有,而只在第一次看时有用,
            之后每次打开都要从它上面跨过去才能到真正要改的参数。 */}
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              className="grid h-6 w-6 flex-none cursor-help place-items-center rounded-md bg-[color-mix(in_srgb,var(--wf-node-color,var(--primary))_12%,transparent)] text-[color:var(--wf-node-color,var(--primary))]"
              style={{ "--wf-node-color": WF_NODE_COLORS[node.type] } as React.CSSProperties}
            >
              {NODE_ICONS[node.type] ?? <Type size={13} />}
            </span>
          </TooltipTrigger>
          {/* 类型和说明都在这里。类型此前是头部的第二行 —— 而**图标已经在表达类型**
              (每种节点各有颜色和图形),再写一遍只是让头部高了一倍。 */}
          <TooltipContent className="grid max-w-[260px] gap-1">
            <span className="font-semibold">{meta?.label ?? node.type}</span>
            {meta?.description && <span className="text-ui-xs opacity-80">{meta.description}</span>}
          </TooltipContent>
        </Tooltip>
        <div className="grid min-w-0 flex-1 gap-0 [&_small]:pl-0 [&_small]:text-ui-2xs [&_small]:text-muted-foreground">
          {/* 节点名在头部内联编辑(Dify 式),不再单列一个"节点名称"字段。
              **裸 input**:Input 基础款的 border-input / rounded-md / h-9 都要对抗,
              而 tokens.css 里那条 `* { border-color: var(--border) }` 和单个 border-* 类
              同优先级、靠顺序决胜 —— 想让边框透明是打不赢的(SubtitlePanel 早就踩过)。

              所以**零边框**,用背景说状态:静止就是标题,悬停浅底(这儿能改),
              聚焦垫底 + ring(正在改)。 */}
          <input
            className="-ml-1 h-7 min-w-0 rounded-md border-0 bg-transparent px-1.5 text-ui-md font-semibold text-foreground outline-none transition-colors duration-100 placeholder:font-normal placeholder:text-muted-foreground hover:bg-[color-mix(in_oklab,var(--foreground)_5%,transparent)] focus-visible:bg-field focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            value={node.name ?? ""}
            placeholder={meta?.label ?? node.type}
            aria-label={t("wfNodeName")}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </div>
        {/* 删除在上方悬浮键的操作组里 —— 一个动作只该有一个入口。 */}
        {onClose && (
          <button type="button" className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-secondary hover:text-foreground" aria-label={t("close")} title={`${t("close")} (Esc)`} onClick={onClose}>
            <X size={14} />
          </button>
        )}
      </div>
      <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] content-start gap-2 overflow-x-hidden overflow-y-auto p-2.5">
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
            <span className="flex items-center gap-[5px] text-ui-xs font-semibold text-destructive">
              <AlertTriangle size={12} /> {t("wfStaleRefsTitle")}
            </span>
            {staleRefs.map(({ key, ref }) => (
              <div className="flex items-center justify-between gap-2" key={`${key}-${ref}`}>
                <code className="rounded-md border border-[color-mix(in_srgb,var(--destructive)_45%,transparent)] bg-[color-mix(in_srgb,var(--destructive)_10%,transparent)] px-1.5 py-px font-mono text-ui-2xs text-destructive line-through">{ref}</code>
                <Popover>
                  <PopoverTrigger asChild>
                    <button type="button" className="flex-none cursor-pointer rounded-md border border-border bg-panel px-2 py-0.5 text-ui-xs text-foreground hover:border-border-strong">
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
        {area === "config" && node.type === "ai_generate" && (
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
                className="w-fit cursor-pointer border-0 bg-transparent p-0 text-ui-xs font-medium text-primary underline-offset-2 hover:underline"
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
                {genParamKeys.map(({ key, label, options, range, toggle }) => (
                  <div className={FIELD_BOX} key={key}>
                    <span>{label}</span>
                    {/* 区间给数字框(上下界来自描述符),枚举给下拉。写死成下拉的话,
                        4–15 秒的模型只剩两个档,而用户看不出少了什么。 */}
                    {toggle ? (
                      <Select
                        value={genParams[key] === undefined ? "" : String(Boolean(genParams[key]))}
                        onValueChange={(next) => setGenParam(key, next)}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={t("wfGenToggleDefault")} />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="true">{t("wfGenToggleOn")}</SelectItem>
                          <SelectItem value="false">{t("wfGenToggleOff")}</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : range ? (
                      <Input
                        type="number"
                        min={range.min}
                        max={range.max}
                        value={String(genParams[key] ?? "")}
                        placeholder={`${range.min}–${range.max}`}
                        onChange={(event) => setGenParam(key, event.target.value)}
                      />
                    ) : (
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
                    )}
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
            {/* 输入素材:**这个模型认哪几种角色就出哪几格**。每一格既能从素材库里选一份,
                也能填上游节点的输出(`{{ai-generate-1.asset_id}}`)—— 工作流里后者才是常态,
                所以用可手填的下拉,而不是纯选择器。 */}
            {genSourceRoles.map((role) => (
              <div className={FIELD_BOX} key={role}>
                <span>
                  {t(SOURCE_ROLE_LABELS[role])}
                  {sourceLimit(genModel, role) > 1 && (
                    <small className="ml-auto font-normal opacity-60">
                      {t("wfGenSourceMultiHint")}
                    </small>
                  )}
                </span>
                <Combobox
                  value={valueForRole(genSourceLines, role)}
                  options={(assets.data ?? []).map((asset) => ({
                    value: asset.id,
                    label: asset.name || asset.original_filename,
                  }))}
                  placeholder={t("wfGenSourcePlaceholder")}
                  emptyText={t("cmdkEmpty")}
                  // 手填是**常态**而不是逃生口:工作流里这一格多半填的是上游输出
                  // (`{{ai-generate-1.asset_id}}`),那种东西下拉里根本没有。
                  allowCustomValue
                  className="w-full"
                  onValueChange={(next: string) =>
                    setConfig("source_assets", serializeSourceAssets(withRole(genSourceLines, role, next)))
                  }
                />
              </div>
            ))}
            {genExtraSourceLines.length > 0 && (
              // 换了模型之后不再被支持的角色。**不能悄悄丢掉** —— 用户换个模型看看效果,
              // 回来发现之前挂的东西没了,比多显示一行难受得多。
              <div className={FIELD_BOX}>
                <span>{t("wfGenSourceExtra")}</span>
                <RefEditor
                  rows={Math.min(genExtraSourceLines.length + 1, 4)}
                  value={serializeSourceAssets(genExtraSourceLines)}
                  variables={variables}
                  onChange={(next: string) =>
                    setConfig(
                      "source_assets",
                      serializeSourceAssets([
                        ...genSourceLines.filter(
                          (line) => line.role && (genSourceRoles as readonly string[]).includes(line.role),
                        ),
                        ...parseSourceAssets(next),
                      ]),
                    )
                  }
                />
                <small>{t("wfGenSourceExtraHint")}</small>
              </div>
            )}
          </div>
        )}
        {area === "config" && node.type === "llm" && (
          <div // **不套框。** 检查器本身已经是一张卡片,里面再画一圈边框就是框中框,而那圈线不表示
            // 任何东西 —— 它只是让内容离两边更远、可读宽度更窄。
            className="grid gap-3">
            <div className={FIELD_BOX}>
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
          </div>
        )}
        {/* **专区此前完全绕过了 advanced 声明。** llm 的十一个旋钮在 NODE_TYPES 里一直标着
            advanced,而专区把它们和 preset 一股脑铺开 —— 于是那个声明在最需要它的节点上
            等于不存在,面板一打开就是满屏采样参数。这里按声明切开:preset 是"这个节点在做
            什么"的那一档,其余进高级。 */}
        {area === "advanced" && node.type === "llm" && (
          <div className="grid gap-3">
            <div className={FIELD_BOX}>
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
              <div className={FIELD_BOX}>
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
              <div className={FIELD_BOX}>
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
              <div className={FIELD_BOX}>
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
              <div className={FIELD_BOX}>
                <span>{t("wfLlmSeed")}</span>
                <Input
                  type="number"
                  step="1"
                  value={String(config.seed ?? "")}
                  placeholder={t("wfLlmBlankDefault")}
                  onChange={setTextConfig("seed")}
                />
              </div>
              <div className={FIELD_BOX}>
                <span>{t("wfLlmFrequencyPenalty")}</span>
                <Input
                  type="number"
                  min={-2}
                  max={2}
                  step="0.1"
                  value={String(config.frequency_penalty ?? "")}
                  placeholder={t("wfRangeMinus2To2")}
                  onChange={setTextConfig("frequency_penalty")}
                />
              </div>
              <div className={FIELD_BOX}>
                <span>{t("wfLlmPresencePenalty")}</span>
                <Input
                  type="number"
                  min={-2}
                  max={2}
                  step="0.1"
                  value={String(config.presence_penalty ?? "")}
                  placeholder={t("wfRangeMinus2To2")}
                  onChange={setTextConfig("presence_penalty")}
                />
              </div>
            </div>
            <div className={FIELD_BOX}>
              <span>{t("wfLlmStop")}</span>
              <RefEditor
                rows={2}
                value={String(config.stop ?? "")}
                onChange={(next) => setConfig("stop", next)}
                variables={variables}
              />
              <small>{t("wfLlmStopHint")}</small>
            </div>
            {responseFormat === "json_schema" && (
              <>
                <div className={FIELD_BOX}>
                  <span>{t("wfLlmJsonSchemaName")}</span>
                  <Input
                    value={String(config.json_schema_name ?? "")}
                    placeholder="workflow_output"
                    onChange={setTextConfig("json_schema_name")}
                  />
                </div>
                <div className={FIELD_BOX}>
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
                <div className={FIELD_BOX}>
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
        {/* 每一档里的表单**整份一起读**,不再切碎;分档只分到「参数 / 高级 / 输出变量 /
            本次产出」这一层。高级从正文底下的折叠块升成条上的一档 —— 折叠块把「还有没有
            更多可调的」藏在一次点击后面,而条上摆着一眼就看得见。 */}
        {area === "config" && basicSpecs.map(renderField)}
        {area === "advanced" && advancedSpecs.map(renderField)}
        {area === "outputs" && meta && (
          <div className="grid gap-[5px] pt-0.5 [&>span]:text-ui-xs [&>span]:font-semibold [&>span]:uppercase [&>span]:tracking-[0.05em] [&>span]:text-muted-foreground">
            <span>{t("wfOutputs")}</span>
            <div className="flex flex-wrap gap-1">
              {meta.outputs.map((output) => {
                const ref = `{{${node.id}.${output}}}`;
                return (
                  <button
                    key={output}
                    type="button"
                    className="cursor-copy rounded-md border border-border bg-secondary px-[7px] py-0.5 font-mono text-ui-2xs text-foreground transition-[border-color] duration-100 hover:border-primary"
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
        {/* 「输出变量」列的是**名字**,这里是**这次的值** —— 调工作流时真正要问的是后者。 */}
        {area === "run" && step && <RunOutputs nodeType={node.type} step={step} />}
      </div>
    </aside>
    </NodeToolbar>
    </>
  );
}
