import React from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import { Image as ImageIcon, Square, StickyNote, Trash2 } from "lucide-react";

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { Button } from "@/components/ui/button";
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
  onPickImage: (place: (assetId: string) => void) => void;
}

function Inner({ boardId, canvas, onChange, onPickImage }: Props) {
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
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable className="!bg-panel" />
      </ReactFlow>

      {/* 工具条:加什么。**浮在左上而不是顶部通栏** —— 画板要尽量大,一条通栏会一直吃掉一行。 */}
      <div className="nodrag absolute left-3 top-3 z-10 flex items-center gap-1 rounded-lg border border-border-strong bg-panel p-1 shadow-[var(--shadow-panel)]">
        <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2" onClick={() => add("note")}>
          <StickyNote size={13} /> 便签
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 px-2"
          onClick={() => onPickImage((assetId) => add("image", { asset_id: assetId }))}
        >
          <ImageIcon size={13} /> 图片
        </Button>
        <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2" onClick={() => add("frame")}>
          <Square size={13} /> 分组
        </Button>
      </div>

      {/* 选中一张便签时才出色板 —— 没选中时它没有作用对象。 */}
      <NotePalette nodes={nodes} setNodes={setNodes} />
    </div>
  );
}

function NotePalette({
  nodes,
  setNodes,
}: {
  nodes: Node[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
}) {
  const selected = nodes.filter((node) => node.selected && node.type === "note");
  if (selected.length === 0) return null;
  return (
    <div className="nodrag absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border-strong bg-panel p-1 shadow-[var(--shadow-panel)]">
      {NOTE_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          aria-label={color}
          className={cn("h-5 w-5 cursor-pointer rounded-full border", noteColorClass(color))}
          onClick={() =>
            setNodes((current) =>
              current.map((node) =>
                node.selected && node.type === "note"
                  ? { ...node, data: { ...node.data, item: { ...(node.data as { item: BoardItem }).item, color } } }
                  : node,
              ),
            )
          }
        />
      ))}
      <span className="mx-1 h-4 w-px bg-border" />
      <button
        type="button"
        aria-label="删除"
        className="grid h-5 w-5 cursor-pointer place-items-center rounded-full text-muted-foreground hover:text-destructive"
        onClick={() => setNodes((current) => current.filter((node) => !node.selected))}
      >
        <Trash2 size={12} />
      </button>
    </div>
  );
}

export function BoardCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Inner {...props} />
    </ReactFlowProvider>
  );
}
