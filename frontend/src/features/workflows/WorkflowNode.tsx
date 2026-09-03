import React from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  AlertTriangle,
  AlignLeft,
  AppWindow,
  AudioLines,
  Bell,
  Boxes,
  Braces,
  CaseSensitive,
  CheckCircle2,
  Code2,
  Download,
  FileOutput,
  FileUp,
  Film,
  Filter,
  Flag,
  FolderInput,
  FolderPlus,
  GitBranch,
  Globe,
  Hourglass,
  Image as ImageIcon,
  Keyboard,
  Languages,
  Loader2,
  Mic,
  MousePointer2,
  MousePointerClick,
  PanelTopClose,
  RefreshCw,
  Repeat,
  Rocket,
  ScanText,
  Scissors,
  SkipForward,
  Sparkles,
  Tags,
  Timer,
  Type,
  Wand2,
  Workflow as WorkflowIcon,
  Wrench,
  XCircle,
} from "lucide-react";

import { api, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { AssetInlinePreview } from "@/components/app/asset-preview";
import { cn } from "@/lib/utils";

/** 节点类型语义色(与轨道颜色同属内容色,不算点缀):
    开始=绿 / LLM=紫 / 插件=琥珀 / 转写=青 / 导出=玫红 / 生成=品红;
    其余类型走 --wf-node-color 的 primary 兜底。 */
const WF_NODE_COLORS: Record<string, string> = {
  start: "#16a34a",
  llm: "#7c3aed",
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
  project_sequence_create: <FolderPlus size={13} />,
  timeline_cut_ranges: <Scissors size={13} />,
};

/** Shared semantic presentation for canvas nodes and their inspector header. */
export function workflowNodeVisual(nodeType: string): { color: string | undefined; icon: React.ReactNode | undefined } {
  return { color: WF_NODE_COLORS[nodeType], icon: NODE_ICONS[nodeType] };
}

export interface WorkflowNodeData extends Record<string, unknown> {
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
  /** 输入接点在人机界面上的名字，由节点声明提供。 */
  inputLabels?: Record<string, string>;
  /** 每个输出接点承载什么类型，由节点声明提供。 */
  outputTypes?: Record<string, string>;
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
    // 圆角**从卡片的令牌推**(卡片圆角 − 1px 边框),不写死一个数:这里原本是 7px,那是卡片还用
    // rounded-md(8px)时算的;卡片后来升到 rounded-lg(10px)而这个数没跟,于是底部两角各缺 2px。
    <div className="grid grid-flow-col justify-stretch gap-px overflow-hidden border-t border-border bg-border [&:last-child]:rounded-b-[calc(var(--radius-lg)-1px)]">
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

function WorkflowNode({ data, selected }: NodeProps) {
  const t = useI18n();
  const d = data as WorkflowNodeData;
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
  const visual = workflowNodeVisual(d.nodeType);
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
        <span className="grid h-7 w-7 flex-none place-items-center rounded-md bg-[color-mix(in_srgb,var(--wf-node-color,var(--primary))_12%,transparent)] text-[color:var(--wf-node-color,var(--primary))]" style={{ "--wf-node-color": visual.color } as React.CSSProperties}>{kindIcon ?? visual.icon ?? <Type size={13} />}</span>
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
        // 圆角同上:卡片圆角 − 1px 边框。差 1px 就会在底部两角露出一线卡片底色。
        <div className="flex justify-between gap-4 rounded-b-[calc(var(--radius-lg)-1px)] border-t border-border bg-panel-subtle px-3 py-[6px]">
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
                {/* 有声明标签走正文字体;裸标识符(如 items)与输出侧同用 mono。 */}
                <span className={cn("whitespace-nowrap text-ui-2xs text-muted-foreground", !(d.inputLabels ?? {})[key] && "font-mono")}>
                  {(d.inputLabels ?? {})[key] || key}
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
                  data-dtype={(d.outputTypes ?? {})[output] ?? "any"}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** React Flow node registry; kept beside the component so presentation details stay private. */
export const WORKFLOW_NODE_TYPES = { wf: WorkflowNode };
