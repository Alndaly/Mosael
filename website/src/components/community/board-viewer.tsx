"use client";

/**
 * 分享画板的只读画布(ADR 0026 §5「查看页」):平移、缩放、适应画面、缩略图;点图片看大图,
 * 视频音频直接播,文档格读全文。
 *
 * 用 React Flow(@xyflow/react)—— 和桌面应用的画板同一个引擎,平移缩放的手感一致。格子的外形
 * 照应用里的来(便签的六种颜色、分组框垫底),但一律只读:不能拖、不能连、不能选。
 *
 * 文档格的 markdown 在服务端渲染好(SafeMarkdown,不进 MDX)经 `documents` 交进来 ——
 * markdown 渲染器就不必进浏览器的包。
 */
import { Background, Controls, Handle, MiniMap, Position, ReactFlow, useReactFlow, useStore, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useTheme } from "next-themes";
import { Box, FileText, Music } from "lucide-react";
import * as React from "react";

import { Modal } from "@/components/community/ui";
import type { Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { noteColor, type BoardFlowEdge, type BoardFlowNode, type BoardNodeData } from "@/lib/community/board";
import { useMounted } from "@/lib/use-mounted";
import { cn } from "@/lib/utils";

type ViewerContext = {
  locale: Locale;
  documents: Record<string, React.ReactNode>;
  openDocument: (id: string, title: string) => void;
};

const Viewer = React.createContext<ViewerContext | null>(null);

function useViewer(): ViewerContext {
  const context = React.useContext(Viewer);
  if (!context) throw new Error("board node outside BoardViewer");
  return context;
}

type FlowNode = Node<BoardNodeData>;

/** 连线要有端点:左进右出,和应用里一样。只读画布上它们不可见、不可连。 */
function Ports() {
  return (
    <>
      <Handle type="target" position={Position.Left} isConnectable={false} className="!pointer-events-none !opacity-0" />
      <Handle type="source" position={Position.Right} isConnectable={false} className="!pointer-events-none !opacity-0" />
    </>
  );
}

/** 格子上方那一行名字(没起名就是种类名)。 */
function Label({ data, icon: Icon }: { data: BoardNodeData; icon?: typeof FileText }) {
  const { locale } = useViewer();
  const kinds = getMessages(locale).boards.kinds as Record<string, string>;
  const text = data.item.title || kinds[data.item.kind] || data.item.kind;
  return (
    <div className="absolute -top-6 left-0 flex max-w-full items-center gap-1 truncate text-xs text-muted-foreground">
      {Icon && <Icon className="size-3.5 shrink-0" aria-hidden />}
      <span className="truncate">{text}</span>
    </div>
  );
}

const SHELL = "relative size-full rounded-xl border border-border bg-card shadow-sm";

const NOTE_CLASS: Record<ReturnType<typeof noteColor>, string> = {
  yellow: "bg-[color-mix(in_srgb,#f5c518_18%,var(--card))] border-[color-mix(in_srgb,#f5c518_30%,var(--border))]",
  blue: "bg-[color-mix(in_srgb,#3b82f6_16%,var(--card))] border-[color-mix(in_srgb,#3b82f6_28%,var(--border))]",
  green: "bg-[color-mix(in_srgb,#22c55e_16%,var(--card))] border-[color-mix(in_srgb,#22c55e_28%,var(--border))]",
  pink: "bg-[color-mix(in_srgb,#ec4899_15%,var(--card))] border-[color-mix(in_srgb,#ec4899_28%,var(--border))]",
  purple: "bg-[color-mix(in_srgb,#8b5cf6_16%,var(--card))] border-[color-mix(in_srgb,#8b5cf6_28%,var(--border))]",
  gray: "bg-[color-mix(in_srgb,var(--foreground)_7%,var(--card))] border-border",
};

function NoteNode({ data }: NodeProps<FlowNode>) {
  return (
    <div className={cn(SHELL, "overflow-hidden", NOTE_CLASS[noteColor(data.item.color)])}>
      {data.item.title && <Label data={data} />}
      {/* nowheel:便签里的长文字滚动时不要顺带缩放画布。 */}
      <div className="nowheel size-full overflow-auto px-3.5 py-3 text-sm leading-6 whitespace-pre-wrap text-foreground">{data.item.text}</div>
      <Ports />
    </div>
  );
}

function ImageNode({ data }: NodeProps<FlowNode>) {
  const { locale } = useViewer();
  return (
    <div className={cn(SHELL, "cursor-zoom-in overflow-visible")}>
      <Label data={data} />
      {data.media ? (
        // 用户的媒体来自社区服务的存储,不走 next/image(分享页的 CSP 只放行同源和配置过的存储)。
        // oxlint-disable-next-line nextjs/no-img-element
        <img src={data.media.thumb} alt={data.item.title ?? ""} loading="lazy" draggable={false} className="size-full rounded-xl object-cover" />
      ) : (
        <Missing locale={locale} />
      )}
      <Ports />
    </div>
  );
}

function VideoNode({ data }: NodeProps<FlowNode>) {
  const { locale } = useViewer();
  return (
    <div className={cn(SHELL, "overflow-visible bg-black")}>
      <Label data={data} />
      {data.media ? (
        // 画板里的视频是作者上传的成片或素材,没有字幕文件可挂;有字幕的话已经烧在画面里。
        // oxlint-disable-next-line jsx-a11y/media-has-caption
        <video
          src={data.media.src}
          poster={data.media.thumb !== data.media.src ? data.media.thumb : undefined}
          controls
          preload="metadata"
          playsInline
          className="nodrag nowheel size-full rounded-xl object-contain"
        />
      ) : (
        <Missing locale={locale} />
      )}
      <Ports />
    </div>
  );
}

function AudioNode({ data }: NodeProps<FlowNode>) {
  const { locale } = useViewer();
  return (
    <div className={cn(SHELL, "flex items-center gap-2 px-3")}>
      <Label data={data} icon={Music} />
      {data.media ? (
        // 同上:作者上传的音频没有字幕轨。
        // oxlint-disable-next-line jsx-a11y/media-has-caption
        <audio src={data.media.src} controls preload="metadata" className="nodrag nowheel h-10 w-full min-w-0" />
      ) : (
        <Missing locale={locale} />
      )}
      <Ports />
    </div>
  );
}

function SceneNode({ data }: NodeProps<FlowNode>) {
  const { locale } = useViewer();
  return (
    <div className={cn(SHELL, "overflow-visible")}>
      <Label data={data} icon={Box} />
      {data.media ? (
        // oxlint-disable-next-line nextjs/no-img-element
        <img src={data.media.thumb} alt={data.item.title ?? ""} loading="lazy" draggable={false} className="size-full rounded-xl object-cover" />
      ) : (
        <Missing locale={locale} />
      )}
      <Ports />
    </div>
  );
}

function DocumentNode({ data }: NodeProps<FlowNode>) {
  const { locale, documents, openDocument } = useViewer();
  const t = getMessages(locale).boards;
  const title = data.item.title || t.kinds.document;
  return (
    <div className={cn(SHELL, "flex flex-col overflow-visible")}>
      <Label data={data} icon={FileText} />
      <div className="nowheel min-h-0 flex-1 overflow-auto px-4 py-3 text-[13px] [&_.docs-body_h2]:mt-4 [&_.docs-body_h2]:text-base">{documents[data.item.id]}</div>
      <button
        type="button"
        onClick={() => openDocument(data.item.id, title)}
        className="nodrag shrink-0 border-t border-border px-4 py-2 text-left text-xs font-semibold text-primary hover:bg-secondary/60"
      >
        {t.readMore}
      </button>
      <Ports />
    </div>
  );
}

function FrameNode({ data }: NodeProps<FlowNode>) {
  return (
    <div className="relative size-full rounded-2xl border-2 border-dashed border-primary/30 bg-primary/[0.03]">
      <div className="absolute -top-6 left-1 max-w-full truncate text-xs font-semibold text-primary">{data.item.title}</div>
      <Ports />
    </div>
  );
}

function UnknownNode({ data }: NodeProps<FlowNode>) {
  const { locale } = useViewer();
  return (
    <div className={cn(SHELL, "grid place-items-center border-dashed p-3 text-center text-xs text-muted-foreground")}>
      <Label data={data} />
      {getMessages(locale).boards.unsupported}
      <Ports />
    </div>
  );
}

function Missing({ locale }: { locale: Locale }) {
  return <div className="grid size-full place-items-center p-3 text-center text-xs text-muted-foreground">{getMessages(locale).boards.unsupported}</div>;
}

/**
 * 画布的尺寸定下来之前(样式还在加载、站头还在排版)React Flow 就做了第一次 fitView,于是整张画板缩在
 * 左上角一小块。尺寸每变一次就再适应一次,直到看的人自己动了平移或缩放 —— 之后不再替他改视角。
 */
function AutoFit({ touched }: { touched: React.RefObject<boolean> }) {
  const { fitView } = useReactFlow();
  const width = useStore((state) => state.width);
  const height = useStore((state) => state.height);
  React.useEffect(() => {
    if (touched.current || width === 0 || height === 0) return;
    void fitView({ padding: 0.12 });
  }, [width, height, fitView, touched]);
  return null;
}

const NODE_TYPES = {
  note: NoteNode,
  image: ImageNode,
  video: VideoNode,
  audio: AudioNode,
  scene: SceneNode,
  document: DocumentNode,
  frame: FrameNode,
  unknown: UnknownNode,
};

export function BoardViewer({
  locale,
  nodes,
  edges,
  documents,
}: {
  locale: Locale;
  nodes: BoardFlowNode[];
  edges: BoardFlowEdge[];
  documents: Record<string, React.ReactNode>;
}) {
  const t = getMessages(locale);
  const mounted = useMounted();
  const { resolvedTheme } = useTheme();
  const [image, setImage] = React.useState<BoardNodeData | null>(null);
  const [reading, setReading] = React.useState<{ id: string; title: string } | null>(null);
  const touched = React.useRef(false);

  const context = React.useMemo<ViewerContext>(
    () => ({ locale, documents, openDocument: (id, title) => setReading({ id, title }) }),
    [locale, documents],
  );
  const flowNodes = React.useMemo(() => nodes as FlowNode[], [nodes]);
  const flowEdges = React.useMemo<Edge[]>(
    () => edges.map((edge) => ({ ...edge, type: "default", focusable: false, style: { stroke: "var(--muted-foreground)", strokeOpacity: 0.55, strokeWidth: 1.5 } })),
    [edges],
  );

  return (
    <Viewer.Provider value={context}>
      <div className="size-full" aria-label={t.boards.openHint}>
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={NODE_TYPES}
          colorMode={mounted && resolvedTheme === "dark" ? "dark" : "light"}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          edgesFocusable={false}
          nodesFocusable={false}
          panOnDrag
          panOnScroll={false}
          zoomOnScroll
          zoomOnPinch
          zoomOnDoubleClick
          minZoom={0.05}
          maxZoom={4}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          onMoveStart={(event) => {
            // 程序里的 fitView 没有事件;有事件就是人动的。
            if (event) touched.current = true;
          }}
          onNodeClick={(_, node) => {
            if (node.type === "image" && node.data.media) setImage(node.data);
          }}
          ariaLabelConfig={{
            "controls.ariaLabel": t.boards.controls,
            "controls.zoomIn.ariaLabel": t.boards.zoomIn,
            "controls.zoomOut.ariaLabel": t.boards.zoomOut,
            "controls.fitView.ariaLabel": t.boards.fit,
            "minimap.ariaLabel": t.boards.minimap,
          }}
          proOptions={{ hideAttribution: false }}
          className="!bg-paper"
        >
          <AutoFit touched={touched} />
          <Background gap={24} size={1.2} color="var(--rule)" />
          <Controls showInteractive={false} position="bottom-left" />
          {/* 窄屏上缩略图会盖住一半画面:只在宽屏显示。 */}
          <MiniMap
            pannable
            zoomable
            position="bottom-right"
            className="!hidden sm:!block"
            nodeColor={(node) => (node.type === "frame" ? "transparent" : "var(--muted-foreground)")}
            nodeStrokeColor={(node) => (node.type === "frame" ? "var(--primary)" : "transparent")}
            maskColor="color-mix(in oklab, var(--paper) 70%, transparent)"
          />
        </ReactFlow>
      </div>

      <Modal open={Boolean(image)} onOpenChange={(open) => !open && setImage(null)} title={image?.item.title || t.boards.kinds.image} closeLabel={t.community.close} wide>
        {image?.media && (
          // oxlint-disable-next-line nextjs/no-img-element
          <img src={image.media.src} alt={image.item.title ?? ""} className="mx-auto max-h-[78dvh] w-auto max-w-full rounded-lg object-contain" />
        )}
      </Modal>

      <Modal open={Boolean(reading)} onOpenChange={(open) => !open && setReading(null)} title={reading?.title ?? ""} closeLabel={t.community.close} wide>
        {reading && <div className="max-w-none">{documents[reading.id]}</div>}
      </Modal>
    </Viewer.Provider>
  );
}
