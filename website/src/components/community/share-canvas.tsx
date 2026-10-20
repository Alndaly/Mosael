"use client";

/**
 * 社区分享详情的**无限画布浏览**:只读,不能编辑。
 *
 * 打开方式是大弹窗(原生 `<dialog` + `showModal()`),而不是「把静态预览就地换成画布」:
 *
 * - 静态 SVG 预览留在首屏,快、也能被爬虫读到;`@xyflow/react` 的 JS 和 DOM 只在点开时才有;
 * - 画布需要一块尽量大的、可平移缩放的视口;塞回正文那一栏会被版心压扁;
 * - 原生 `<dialog>` 白送 Esc 关闭、焦点圈在框里、背景 inert、关掉后焦点回到触发元素。
 *
 * 几何一行都不在这里算:节点 / 边来自 `share-preview-model.ts` 的 `toFlowGraph()`,
 * 和静态 SVG 预览是同一份内容(同一份解析、同一个 200 上限)。
 *
 * **只读**:节点不可拖、不可连、不可删;没有新增 / 删除 / 编辑工具条。屏幕上的
 * 可交互部分只有平移、缩放和「适应画布」(xyflow 的 Controls)。
 */
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { Maximize2, X } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";

import "@xyflow/react/dist/style.css";

import type { Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { cn } from "@/lib/utils";

import type { ShareFlowGraph, ShareFlowNodeData } from "./share-preview-model";

/** 自定义节点:圆角框 + 名字。xyflow 的 `Node<data, type>`。 */
type ShareNode = Node<ShareFlowNodeData, "share">;

/**
 * 淡色,和 `share-preview.tsx` 的 SVG 淡色一一对应(序号来自模型的 `tint`)。
 * 全取现有 token,深 / 浅色由 CSS 变量自己翻,不引第二套颜色。
 */
const TINTS: readonly string[] = [
  "bg-secondary",
  "bg-brand-soft",
  "bg-muted",
  "bg-accent/10",
  "bg-foreground/10",
];

/**
 * 一个节点长什么样。**不用 xyflow 内置的 default 节点** —— 那是白色方块 + 默认边框,
 * 和站点的圆角、字体、颜色都对不上。
 */
function ShareNodeView({ data }: NodeProps<ShareNode>) {
  return (
    <div
      title={data.label}
      className={cn(
        "flex h-full w-full items-center overflow-hidden rounded-xl border border-border px-3 shadow-sm",
        TINTS[data.tint % TINTS.length],
      )}
    >
      {/* 进 / 出两个**看不见**的连接点:xyflow 靠它们算边的起止位置,没有它们边不画。
          只读浏览用,`isConnectable={false}` 再加 `pointer-events-none`,连不上也点不到。 */}
      <Handle
        type="target"
        position={Position.Left}
        isConnectable={false}
        className="pointer-events-none opacity-0"
      />
      <span className="truncate text-sm leading-5 font-medium text-foreground">{data.label}</span>
      <Handle
        type="source"
        position={Position.Right}
        isConnectable={false}
        className="pointer-events-none opacity-0"
      />
    </div>
  );
}

/**
 * 稳定引用,别在 render 里重建 —— xyflow 每次拿到新的 `nodeTypes` 都会重挂所有节点。
 */
const NODE_TYPES = { share: ShareNodeView };

/**
 * 只读画布本体。
 *
 * - `nodesDraggable` / `nodesConnectable` 关掉:能看、能选、不能改;
 * - `deleteKeyCode={null}`:Delete 键不会删掉任何东西;
 * - 平移 / 缩放都开,`fitView` 打开就居中铺满,缩放有上下限;
 * - 200 个上限由模型保证;超出的部分由调用方在角上写「还有 N 个没画」。
 */
export function ShareCanvas({
  graph,
  hiddenText,
  labels,
}: {
  graph: ShareFlowGraph;
  hiddenText: string | null;
  /** 缩放控件的读屏名(中英各一套,别让中文页面读出 "Zoom In")。 */
  labels: { zoomIn: string; zoomOut: string; fitView: string };
}) {
  const { resolvedTheme } = useTheme();

  // 坐标、尺寸全是模型算好的;这里只补 xyflow 的只读标记。
  const nodes = React.useMemo<ShareNode[]>(
    () =>
      graph.nodes.map((node) => ({
        id: node.id,
        type: "share",
        position: node.position,
        width: node.width,
        height: node.height,
        data: node.data,
        draggable: false,
        connectable: false,
      })),
    [graph.nodes],
  );

  const edges = React.useMemo<Edge[]>(
    () =>
      graph.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        // 边跟着主题走,不给每条边写死颜色。用 muted-foreground 而不是 border:
        // 后者在深浅两套里都太淡,29 个节点的工作流会看不见结构。
        style: { stroke: "var(--muted-foreground)", strokeWidth: 1.5 },
      })),
    [graph.edges],
  );

  return (
    <div className="relative h-full w-full bg-card">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        colorMode={resolvedTheme === "dark" ? "dark" : "light"}
        // ---- 只读 ----
        nodesDraggable={false}
        nodesConnectable={false}
        edgesReconnectable={false}
        deleteKeyCode={null}
        // 选一下看看可以;但不能改,也没有编辑工具条。
        elementsSelectable
        // ---- 无限浏览:平移 + 缩放 + 打开就铺满 ----
        panOnDrag
        panOnScroll
        zoomOnScroll
        zoomOnPinch
        minZoom={0.05}
        maxZoom={2}
        fitView
        fitViewOptions={{ padding: 0.16, minZoom: 0.05, maxZoom: 1.4 }}
        // 节点多时只渲染视口内的;29 个也照开,成本可以忽略。
        onlyRenderVisibleElements
        // 缩放控件的读屏名跟着语言走(xyflow 默认是英文)。
        ariaLabelConfig={{
          "controls.zoomIn.ariaLabel": labels.zoomIn,
          "controls.zoomOut.ariaLabel": labels.zoomOut,
          "controls.fitView.ariaLabel": labels.fitView,
        }}
        proOptions={{ hideAttribution: false }}
        // 控件只有「放大 / 缩小 / 适应」,没有交互锁 —— 那是编辑器的东西。
        className="[&_.react-flow__controls-button]:border-border [&_.react-flow__controls-button]:bg-card [&_.react-flow__controls-button]:fill-foreground [&_.react-flow__controls-button:hover]:bg-secondary"
      >
        <Background color="var(--border)" gap={24} size={1} />
        <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>
      {hiddenText && (
        // 超过 200 的点:角落一句说明。放右上角,避开左下角控件和右下角 xyflow 署名。
        <p className="pointer-events-none absolute top-3 right-3 z-10 m-0 rounded-full border border-border bg-card/90 px-3 py-1 text-xs text-muted-foreground backdrop-blur">
          {hiddenText}
        </p>
      )}
    </div>
  );
}

/**
 * 详情页的入口 + 大弹窗。
 *
 * 键盘 / 读屏这条路:按钮打开模态 `<dialog>`,Esc 走原生 `cancel`;关闭时把焦点显式还给
 * 触发按钮(原生 `<dialog>` 已经会还,这里再收一次是因为 React 重新渲染 / 条件挂载的时序
 * 不一定跟着浏览器走 —— 键盘用户不该被扔回文档开头)。
 */
export function ShareCanvasDialog({ locale, graph }: { locale: Locale; graph: ShareFlowGraph }) {
  const t = getMessages(locale).community;
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const dialogRef = React.useRef<HTMLDialogElement>(null);

  /**
   * 先 `showModal()` 再挂载画布。
   *
   * 顺序不能反:内容若在 `<dialog>` 还是 `display:none` 时就挂上,xyflow 量到的容器是
   * 0×0,`fitView` 会把整张图缩成一个点。点按钮时同步把对话框显示出来,再让 React 渲染
   * 里面的画布 —— 挂载那一刻容器已经有真实尺寸。
   */
  const openDialog = () => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    setOpen(true);
  };

  // 开着的时候锁住页面滚动(和搜索弹窗同一套:这个站的滚动容器是 <html>)。
  React.useEffect(() => {
    if (!open) return;
    const root = document.documentElement;
    const gap = window.innerWidth - root.clientWidth;
    const overflow = root.style.overflow;
    const padding = root.style.paddingRight;
    root.style.overflow = "hidden";
    if (gap > 0) root.style.paddingRight = `${gap}px`;
    return () => {
      root.style.overflow = overflow;
      root.style.paddingRight = padding;
    };
  }, [open]);

  const close = () => {
    const dialog = dialogRef.current;
    if (dialog?.open) dialog.close();
    setOpen(false);
    // 焦点回到触发按钮;调用 close() 之后浏览器也会做一次,这里显式再来一次。
    triggerRef.current?.focus();
  };

  const hiddenText = graph.hidden > 0 ? t.previewHidden.replace("{n}", String(graph.hidden)) : null;
  const nodeCount = graph.kind === "workflow" ? t.previewNodesUnit : t.previewItemsUnit;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={openDialog}
        className="inline-flex min-h-10 w-fit items-center gap-2 rounded-full border border-border bg-card px-4 text-sm font-semibold transition-colors hover:border-primary/50 hover:text-primary"
      >
        <Maximize2 className="size-4" aria-hidden />
        {t.canvasOpen}
      </button>

      {/* 点遮罩关闭:落在 <dialog> 本体上的点击 target 就是 currentTarget。键盘那条路是 Esc。 */}
      {/* oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions */}
      <dialog
        ref={dialogRef}
        aria-label={t.canvasTitle}
        onCancel={(event) => {
          // Esc:走和关闭按钮同一条路径(状态、焦点、滚动锁一处收口)。
          event.preventDefault();
          close();
        }}
        onClose={() => setOpen(false)}
        onClick={(event) => {
          if (event.target === event.currentTarget) close();
        }}
        className="m-auto h-[min(88svh,56rem)] w-[min(94vw,80rem)] overflow-hidden rounded-2xl border border-border bg-paper p-0 text-foreground backdrop:bg-ink/60"
      >
        {open && (
          <div className="flex h-full w-full flex-col">
            <header className="flex items-center gap-3 border-b border-border px-4 py-3">
              <div className="min-w-0 flex-1">
                <h2 className="m-0 truncate font-display text-base font-bold tracking-tight">{t.canvasTitle}</h2>
                <p className="m-0 mt-0.5 truncate text-xs text-muted-foreground">
                  {t.canvasHint}
                  <span aria-hidden> · </span>
                  <span className="font-mono tabular-nums">
                    {graph.total} {nodeCount}
                  </span>
                </p>
              </div>
              <button
                type="button"
                onClick={close}
                autoFocus
                className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-sm font-semibold transition-colors hover:border-primary/50 hover:text-primary"
              >
                <X className="size-4" aria-hidden />
                {t.canvasClose}
              </button>
            </header>
            <div className="min-h-0 flex-1">
              <ShareCanvas
                graph={graph}
                hiddenText={hiddenText}
                labels={{ zoomIn: t.canvasZoomIn, zoomOut: t.canvasZoomOut, fitView: t.canvasFitView }}
              />
            </div>
          </div>
        )}
      </dialog>
    </>
  );
}
