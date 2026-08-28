import React from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  NodeToolbar,
  Position,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import { Copy, Replace, Trash2 } from "lucide-react";

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { usePersistentViewport } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { BOARD_NODE_TYPES, DEFAULT_SIZE, NOTE_COLORS, noteColorClass } from "@/features/boards/boardNodes";

/**
 * 创意画板的画布。
 *
 * 复用 React Flow 而不是自己写一个无限画布:平移缩放、框选、连线、小地图这些都不是这个功能
 * 的创新点,而每一样自己写都要踩一遍别人踩过的坑(触控板惯性、缩放锚点、连线命中判定)。
 * 工作流那边已经证明这层能用。
 *
 * **画布状态住在 React Flow 里,画板数据住在上面。** 两者靠 `toCanvas` 单向汇出 ——
 * 双向同步会打架:拖动时 React Flow 每帧改一次位置,回写又会重建节点,拖到一半会跳。
 */

function toNodes(items: BoardItem[], onText: (id: string, text: string) => void): Node[] {
  return items.map((item) => ({
    id: item.id,
    type: item.kind,
    position: { x: item.x, y: item.y },
    width: item.width ?? DEFAULT_SIZE[item.kind].width,
    height: item.height ?? DEFAULT_SIZE[item.kind].height,
    data: { item, onText },
    // 分组框永远在最底 —— 它是背景,盖住上面的项就没法点了。
    zIndex: item.kind === "frame" ? 0 : 1,
  }));
}

/** 把 React Flow 的当前状态汇成要存的画布。**位置以 React Flow 为准** —— 它才是刚被拖过的那份。 */
export function toCanvas(nodes: Node[], edges: Edge[]): Canvas {
  return {
    items: nodes.map((node) => {
      const { item } = node.data as unknown as { item: BoardItem };
      return {
        ...item,
        x: Math.round(node.position.x),
        y: Math.round(node.position.y),
        width: Math.round(node.width ?? node.measured?.width ?? DEFAULT_SIZE[item.kind].width),
        height: Math.round(node.height ?? node.measured?.height ?? DEFAULT_SIZE[item.kind].height),
      };
    }),
    edges: edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
  };
}

interface Props {
  boardId: string;
  canvas: Canvas;
  onChange: (canvas: Canvas) => void;
  /** 让上层开素材选择器。kind 决定它列图片还是视频 —— 选得到的就该是贴上去能看的。 */
  onPickAsset: (kind: "image" | "video", place: (assetId: string) => void) => void;
  /** 把「加一项」交给上层 —— 顶栏那两组胶囊要摆在一起(和工作流详情页一致),
   *  而 add 依赖画布内部的 rf 实例和 setNodes,只能由画布提供。 */
  onReady?: (api: { add: (kind: BoardItem["kind"], extra?: Partial<BoardItem>) => void }) => void;
}

function Inner({ boardId, canvas, onChange, onPickAsset, onReady }: Props) {
  const rf = React.useRef<ReactFlowInstance | null>(null);
  const viewport = usePersistentViewport(`board:${boardId}`);
  const [ready, setReady] = React.useState(false);

  // 文字改动直接落进节点 data —— 走 setNodes 而不是回写上层,理由同上:
  // 上层一变就重建节点,正在打字的 textarea 会失焦。
  const setText = React.useCallback((id: string, text: string) => {
    setNodes((current) =>
      current.map((node) =>
        node.id === id
          ? { ...node, data: { ...node.data, item: { ...(node.data as { item: BoardItem }).item, text } } }
          : node,
      ),
    );
  }, []);

  const [nodes, setNodes, onNodesChange] = useNodesState(toNodes(canvas.items, setText));
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(
    canvas.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
  );

  // 每次画布变了就汇一份给上层去存。**用 JSON 比对而不是引用比对** —— React Flow 每次
  // 拖动都换新对象,引用比对等于每帧都报"变了"。
  const serialized = React.useMemo(() => JSON.stringify(toCanvas(nodes, edges)), [nodes, edges]);
  React.useEffect(() => {
    onChange(JSON.parse(serialized) as Canvas);
  }, [serialized, onChange]);

  const add = React.useCallback(
    (kind: BoardItem["kind"], extra: Partial<BoardItem> = {}) => {
      const instance = rf.current;
      // 放在**视野中心**,不是原点:画板可以拖得很远,放原点等于放到看不见的地方。
      const center = instance
        ? instance.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 })
        : { x: 0, y: 0 };
      const item: BoardItem = {
        id: `${kind}-${Date.now().toString(36)}`,
        kind,
        x: Math.round(center.x - DEFAULT_SIZE[kind].width / 2),
        y: Math.round(center.y - DEFAULT_SIZE[kind].height / 2),
        ...DEFAULT_SIZE[kind],
        ...(kind === "note" ? { color: "yellow" } : {}),
        ...extra,
      };
      setNodes((current) => [...current, ...toNodes([item], setText)]);
    },
    [setNodes, setText],
  );

  React.useEffect(() => {
    onReady?.({ add });
  }, [add, onReady]);

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={BOARD_NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={(connection: Connection) => setEdges((current) => addEdge(connection, current))}
        onInit={(instance) => {
          rf.current = instance as unknown as ReactFlowInstance;
          requestAnimationFrame(() => {
            if (viewport.saved) instance.setViewport(viewport.saved);
            else instance.fitView({ padding: 0.3, maxZoom: 1 });
            setReady(true);
          });
        }}
        onMoveEnd={(_event, next) => viewport.remember(next)}
        // 双击空白处直接加一张便签 —— 想法来的时候不该先去找按钮。
        onDoubleClick={(event) => {
          if ((event.target as HTMLElement).closest(".react-flow__node")) return;
          const instance = rf.current;
          if (!instance) return;
          const point = instance.screenToFlowPosition({ x: event.clientX, y: event.clientY });
          const item: BoardItem = {
            id: `note-${Date.now().toString(36)}`,
            kind: "note",
            x: Math.round(point.x - DEFAULT_SIZE.note.width / 2),
            y: Math.round(point.y - DEFAULT_SIZE.note.height / 2),
            ...DEFAULT_SIZE.note,
            color: "yellow",
          };
          setNodes((current) => [...current, ...toNodes([item], setText)]);
        }}
        className={cn(!ready && "opacity-0")}
        proOptions={{ hideAttribution: false }}
        minZoom={0.1}
        maxZoom={2.5}
        deleteKeyCode={["Backspace", "Delete"]}
        selectionOnDrag
        panOnDrag={[1, 2]}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} />
        {/* 缩放钮/预览图**不吃应用主题**(xyflow 默认一律白底)—— 深色下就是右下角一块白。
            把 --xy-* 映射到设计令牌,和工作流页用的是同一套(见 WorkflowsView 里那段说明)。 */}
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


      {/* 选中之后才出操作条 —— 没选中时它没有作用对象。 */}
      <ItemToolbar nodes={nodes} setNodes={setNodes} onPickAsset={onPickAsset} />
    </div>
  );
}

/**
 * 选中一项时浮在它上面的操作条。
 *
 * **按类型给动作,不给一套通用的**:便签要换颜色,图片/视频要换素材,分组框两者都不要。
 * 摆一排一半是灰的按钮,等于让用户每次都先分辨哪些能点。
 *
 * 位置跟着选中项走 —— 用 NodeToolbar,它渲染在 React Flow 的视口层里,平移缩放时自己跟着动
 * (工作流那边的检查器用的是同一个原语)。
 */
function ItemToolbar({
  nodes,
  setNodes,
  onPickAsset,
}: {
  nodes: Node[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
  onPickAsset: Props["onPickAsset"];
}) {
  const selected = nodes.filter((node) => node.selected);
  // 多选时只给共通的动作 —— 逐个类型的动作在混选下没有一致的含义。
  const single = selected.length === 1 ? selected[0] : null;
  if (selected.length === 0) return null;

  const item = single ? (single.data as unknown as { item: BoardItem }).item : null;

  const patch = (id: string, next: Partial<BoardItem>) =>
    setNodes((current) =>
      current.map((node) =>
        node.id === id
          ? { ...node, data: { ...node.data, item: { ...(node.data as { item: BoardItem }).item, ...next } } }
          : node,
      ),
    );

  const duplicate = () =>
    setNodes((current) => [
      ...current.map((node) => ({ ...node, selected: false })),
      ...current
        .filter((node) => node.selected)
        .map((node) => {
          const source = (node.data as unknown as { item: BoardItem }).item;
          const copy: BoardItem = { ...source, id: `${source.kind}-${Math.random().toString(36).slice(2, 9)}` };
          return {
            ...node,
            id: copy.id,
            // 错开一点放,不然复制出来的正好盖在原件上,看着像什么都没发生。
            position: { x: node.position.x + 24, y: node.position.y + 24 },
            selected: true,
            data: { ...node.data, item: copy },
          };
        }),
    ]);

  return (
    <NodeToolbar nodeId={selected.map((node) => node.id)} isVisible position={Position.Top} offset={10}>
      <div className="nodrag nopan flex items-center gap-0.5 rounded-full border border-border-strong bg-panel p-1 shadow-[var(--shadow-panel)]">
        {item?.kind === "note" &&
          NOTE_COLORS.map((color) => (
            <button
              key={color}
              type="button"
              aria-label={color}
              className={cn(
                "h-5 w-5 cursor-pointer rounded-full border transition-transform hover:scale-110",
                noteColorClass(color),
                item.color === color && "ring-2 ring-primary ring-offset-1 ring-offset-[var(--panel)]",
              )}
              onClick={() => patch(item.id, { color })}
            />
          ))}

        {(item?.kind === "image" || item?.kind === "video") && (
          <button
            type="button"
            className="flex cursor-pointer items-center gap-1 rounded-full px-2 py-1 text-ui-2xs text-muted-foreground hover:bg-secondary hover:text-foreground"
            onClick={() => onPickAsset(item.kind as "image" | "video", (assetId) => patch(item.id, { asset_id: assetId }))}
          >
            <Replace size={12} /> 换一份
          </button>
        )}

        {item && <span aria-hidden className="mx-0.5 h-4 w-px bg-border" />}

        <button
          type="button"
          aria-label="复制"
          title="复制"
          className="grid h-6 w-6 cursor-pointer place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground"
          onClick={duplicate}
        >
          <Copy size={12} />
        </button>
        <button
          type="button"
          aria-label="删除"
          title="删除"
          className="grid h-6 w-6 cursor-pointer place-items-center rounded-full text-muted-foreground hover:text-destructive"
          onClick={() => setNodes((current) => current.filter((node) => !node.selected))}
        >
          <Trash2 size={12} />
        </button>
      </div>
    </NodeToolbar>
  );
}

export function BoardCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Inner {...props} />
    </ReactFlowProvider>
  );
}
