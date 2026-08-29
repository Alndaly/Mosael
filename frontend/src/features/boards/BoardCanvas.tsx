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
import { Copy, FileUp, Loader2, Replace, Sparkles, Trash2 } from "lucide-react";

import type { BoardCanvas as Canvas, BoardItem, GenerationModel } from "@/api/client";
import { NodeComposer } from "@/features/boards/NodeComposer";
import { isMediaFile, useFileDrop } from "@/lib/useFileDrop";
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

/** 只放**数据**。回调在渲染时注入(见 displayNodes)—— 存进节点里的话,它们会闭包住
 *  还没声明的 setNodes,而这个顺序绕不开:节点的初值本身就要用到它们。 */
function toNodes(items: BoardItem[]): Node[] {
  return items.map((item) => ({
    id: item.id,
    type: item.kind,
    position: { x: item.x, y: item.y },
    width: item.width ?? DEFAULT_SIZE[item.kind].width,
    height: item.height ?? DEFAULT_SIZE[item.kind].height,
    data: { item },
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
  /** 从某一项生成。上层拿得到 workspaceId 和接口,画布只提供"放哪儿"和"填回来"。 */
  onGenerate?: (input: {
    kind: "image" | "video";
    prompt: string;
    /** 填进**这一格**(节点即生成单元)。不给就是另开一格放在源节点右边。 */
    itemId?: string;
    x?: number;
    y?: number;
    provider?: string;
    model?: string;
    parameters?: Record<string, unknown>;
    sourceAssets?: { asset_id: string; role: string }[];
  }) => Promise<unknown>;
  /** 可用的生成模型 —— 提示词面板要让人选。 */
  models?: GenerationModel[];
  /** 全览开着没有。占右下角一块不小的地方,图小的时候纯属挡视线。 */
  showMinimap?: boolean;
  /** 系统里拖进来的文件:上层负责传进素材库,回来的每一份就地摆到落点上。 */
  onDropFiles?: (files: File[]) => Promise<{ id: string; name: string; kind: "image" | "video" }[]>;
  uploading?: boolean;
  /** 把「加一项」交给上层 —— 顶栏那两组胶囊要摆在一起(和工作流详情页一致),
   *  而 add 依赖画布内部的 rf 实例和 setNodes,只能由画布提供。 */
  onReady?: (api: {
    add: (kind: BoardItem["kind"], extra?: Partial<BoardItem>) => void;
    fill: (itemId: string, assetId: string) => void;
    fitView: () => void;
  }) => void;
}

function Inner({ boardId, canvas, onChange, onPickAsset, onGenerate, models, showMinimap = true, onDropFiles, uploading, onReady }: Props) {
  const rf = React.useRef<ReactFlowInstance | null>(null);
  const viewport = usePersistentViewport(`board:${boardId}`);
  const [ready, setReady] = React.useState(false);

  const [nodes, setNodes, onNodesChange] = useNodesState(toNodes(canvas.items));
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(
    canvas.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
  );

  // 文字改动直接落进节点 data —— 走 setNodes 而不是回写上层,理由同上:
  // 上层一变就重建节点,正在打字的 textarea 会失焦。
  const setText = React.useCallback((id: string, text: string): void => {
    setNodes((current: Node[]) =>
      current.map((node: Node) =>
        node.id === id
          ? { ...node, data: { ...node.data, item: { ...(node.data as { item: BoardItem }).item, text } } }
          : node,
      ),
    );
  }, []);

  /**
   * 媒体加载出来之后,把节点高度校正成它的**自然宽高比**。
   *
   * 不校正的话:一段 16:9 的视频摆在 320×200(1.6:1)的框里,上下各留一条黑边 —— 而画板上
   * 一眼扫过去看的就是画面本身,黑边等于把每个节点都缩小了一圈。图片同理。
   *
   * **只在还没被用户拉过时才校正**:他手动调过尺寸就是他的决定,不该被媒体加载覆盖回去。
   * 判据是宽高恰好等于默认值 —— 拉过的话至少有一边不是。
   */
  // 参数显式标类型:它在 useNodesState 之前定义(初值要用它),不标的话 TS 会绕回自己身上推。
  const setAspect = React.useCallback((id: string, ratio: number): void => {
    if (!Number.isFinite(ratio) || ratio <= 0) return;
    setNodes((current: Node[]) =>
      current.map((node: Node) => {
        if (node.id !== id) return node;
        const item = (node.data as unknown as { item: BoardItem }).item;
        const preset = DEFAULT_SIZE[item.kind];
        const width = node.width ?? preset.width;
        const height = node.height ?? preset.height;
        if (width !== preset.width || height !== preset.height) return node;
        const next = Math.round(width / ratio);
        return next === height ? node : { ...node, height: next };
      }),
    );
  }, [setNodes]);


  // 每次画布变了就汇一份给上层去存。**用 JSON 比对而不是引用比对** —— React Flow 每次
  // 拖动都换新对象,引用比对等于每帧都报"变了"。
  //: 选中的那个空槽/生成中的槽 —— 只有一个被选中时才挂面板,多选没有单一的作用对象。
  const composerItem = React.useMemo(() => {
    const picked = nodes.filter((node) => node.selected);
    if (picked.length !== 1) return null;
    const item = (picked[0].data as unknown as { item: BoardItem }).item;
    return (item.kind === "image" || item.kind === "video") && !item.asset_id ? item : null;
  }, [nodes]);

  //: 渲染用的节点 = 数据 + 这一轮的回调。**每轮重新贴** —— 回调闭包着最新的 setNodes,
  //: 而把它们存进节点数据会让节点的初值反过来依赖 setNodes,那个循环绕不开。
  const displayNodes = React.useMemo(
    () => nodes.map((node) => ({ ...node, data: { ...node.data, onText: setText, onAspect: setAspect } })),
    [nodes, setText, setAspect],
  );

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
      // **加完就选中它**:放一个空槽的下一步一定是写提示词,而面板只在选中时才挂。
      // 不选中的话用户要再点一次才知道这儿能写字。
      setNodes((current) => [
        ...current.map((node) => ({ ...node, selected: false })),
        ...toNodes([item]).map((node) => ({ ...node, selected: true })),
      ]);
    },
    [setNodes, setText, setAspect],
  );

  /** 把某一项就地换成已完成的产出。轮询拿到结果后由上层调。 */
  const fill = React.useCallback(
    (itemId: string, assetId: string) => {
      setNodes((current) =>
        current.map((node) => {
          if (node.id !== itemId) return node;
          const item = (node.data as unknown as { item: BoardItem }).item;
          const { job_id: _dropped, ...rest } = item;
          return { ...node, data: { ...node.data, item: { ...rest, asset_id: assetId } } };
        }),
      );
    },
    [setNodes],
  );

  /**
   * 从系统里拖文件进来 —— 传进素材库,再就地摆到落点上。
   *
   * 用仓库现成的 useFileDrop:整块区域拖放的三个坑(子元素边界上的 dragleave 抖动、
   * 浏览器默认打开文件、拖文字也亮提示)它已经处理过了,自己写要再踩一遍。
   *
   * **落点要在 drop 那一刻算**(那时才有鼠标位置),而 useFileDrop 的回调拿不到事件 ——
   * 和工作流那边一样,用一个 ref 把坐标从事件里带出来。
   */
  const dropAt = React.useRef<{ x: number; y: number } | null>(null);
  const drop = useFileDrop((files) => {
    const at = dropAt.current ?? { x: 0, y: 0 };
    void onDropFiles?.(files).then((assets) => {
      if (!assets?.length) return;
      setNodes((current) => [
        ...current.map((node) => ({ ...node, selected: false })),
        ...assets.flatMap((asset, index) =>
          toNodes(
            [
              {
                id: `${asset.kind}-${Math.random().toString(36).slice(2, 9)}`,
                kind: asset.kind,
                // 多个文件斜着摞开,不然它们会精确重叠成一个。
                x: Math.round(at.x + index * 24),
                y: Math.round(at.y + index * 24),
                ...DEFAULT_SIZE[asset.kind],
                asset_id: asset.id,
                text: asset.name,
              },
            ],
          ),
        ),
      ]);
    });
  }, isMediaFile);

  React.useEffect(() => {
    onReady?.({ add, fill, fitView: () => rf.current?.fitView({ padding: 0.3, duration: 250 }) });
  }, [add, fill, onReady]);

  return (
    // 画布放在**带边框的圆角卡片**里(和工作流详情页同一个形态)—— 通栏铺到窗口边的话,
    // 它和外面的应用外壳之间没有界,画布看起来是"漏出来的"而不是一块内容区。
    <div
      className="relative h-full w-full overflow-hidden rounded-lg border border-border bg-background"
      {...drop.handlers}
      // 坐标换算要在 drop 那一刻做 —— 这里把鼠标位置存下来给上面的回调用。
      onDragOver={(event) => {
        drop.handlers.onDragOver(event);
        const instance = rf.current;
        if (instance) dropAt.current = instance.screenToFlowPosition({ x: event.clientX, y: event.clientY });
      }}
    >
      <ReactFlow
        nodes={displayNodes}
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
          setNodes((current) => [...current, ...toNodes([item])]);
        }}
        className={cn(!ready && "opacity-0")}
        proOptions={{ hideAttribution: false }}
        /* 触控板约定(Figma / Miro 那套):双指滑动 = 平移,捏合 = 缩放。**和工作流画布同一套** ——
           React Flow 默认 zoomOnScroll:true,而 macOS 触控板双指滑动发出的正是 wheel 事件,
           于是「想拖画布」变成了「缩放」。捏合发的是 ctrlKey 的 wheel,归 zoomOnPinch 管,
           所以关掉 zoomOnScroll 不影响捏合;鼠标用户按住 ctrl/⌘ 滚轮同样落进这条,仍可缩放。 */
        panOnScroll
        zoomOnScroll={false}
        zoomOnPinch
        minZoom={0.1}
        maxZoom={2.5}
        deleteKeyCode={["Backspace", "Delete"]}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} />
        {/* 缩放钮/预览图**不吃应用主题**(xyflow 默认一律白底)—— 深色下就是右下角一块白。
            把 --xy-* 映射到设计令牌,和工作流页用的是同一套(见 WorkflowsView 里那段说明)。 */}
        <Controls
          showInteractive={false}
          position="bottom-left"
          className="overflow-hidden rounded-md border border-border [--xy-controls-box-shadow:none] [--xy-controls-button-background-color:var(--panel)] [--xy-controls-button-background-color-hover:var(--secondary)] [--xy-controls-button-border-color:var(--border)] [--xy-controls-button-color:var(--muted-foreground)] [--xy-controls-button-color-hover:var(--foreground)]"
        />
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
      </ReactFlow>


      {/* 拖着文件悬在上面时的提示。**盖住整块**,虚线收在中间那段字上而不是描边 ——
          描边会和画布自己的圆角错开(工作流那边写过同一段理由)。 */}
      {(drop.active || uploading) && (
        <div className="pointer-events-none absolute inset-0 z-40 grid place-items-center rounded-lg bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
          <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
            {uploading ? <Loader2 size={20} className="animate-spin" /> : <FileUp size={20} />}
            {uploading ? "正在上传…" : "松手就放到画板上"}
          </span>
        </div>
      )}

      {/* 选中之后才出操作条 —— 没选中时它没有作用对象。 */}
      <ItemToolbar nodes={nodes} setNodes={setNodes} onPickAsset={onPickAsset} onGenerate={onGenerate} />

      {/* 选中一个**还没有产出**的图片/视频槽时,底下挂提示词面板 —— 节点本身就是生成单元。 */}
      {composerItem && onGenerate && (
        <NodeComposer
          key={composerItem.id}
          item={composerItem}
          models={models ?? []}
          busy={Boolean(composerItem.job_id)}
          onPickAsset={onPickAsset}
          onSubmit={({ prompt, provider, model, parameters, sourceAssets }) =>
            void onGenerate({
              kind: composerItem.kind as "image" | "video",
              prompt,
              provider,
              model,
              parameters,
              sourceAssets,
              itemId: composerItem.id,
            })
          }
        />
      )}
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
  onGenerate,
}: {
  nodes: Node[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
  onPickAsset: Props["onPickAsset"];
  onGenerate: Props["onGenerate"];
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

        {/* 生成:**从这一项长出下一项**。便签的文字就是提示词,图片当首帧生视频 ——
            这正是画板比便签墙多出来的那一步。已经在生成的那一项不再给(它还没有产出)。 */}
        {onGenerate && item && item.kind !== "frame" && item.asset_id !== undefined === (item.kind !== "note") && (
          <>
            {item.kind === "note" && (
              <button
                type="button"
                className="flex cursor-pointer items-center gap-1 rounded-full px-2 py-1 text-ui-2xs text-muted-foreground hover:bg-secondary hover:text-foreground"
                title="用这段文字生成图片"
                onClick={() =>
                  void onGenerate({
                    kind: "image",
                    prompt: item.text ?? "",
                    x: (single?.position.x ?? 0) + (single?.width ?? 220) + 40,
                    y: single?.position.y ?? 0,
                  })
                }
              >
                <Sparkles size={12} /> 生成图片
              </button>
            )}
            {item.kind === "image" && item.asset_id && (
              <button
                type="button"
                className="flex cursor-pointer items-center gap-1 rounded-full px-2 py-1 text-ui-2xs text-muted-foreground hover:bg-secondary hover:text-foreground"
                title="用这张图当首帧生成视频"
                onClick={() =>
                  void onGenerate({
                    kind: "video",
                    prompt: item.text ?? "",
                    x: (single?.position.x ?? 0) + (single?.width ?? 260) + 40,
                    y: single?.position.y ?? 0,
                    sourceAssets: item.asset_id ? [{ asset_id: item.asset_id, role: "first_frame" }] : [],
                  })
                }
              >
                <Sparkles size={12} /> 生成视频
              </button>
            )}
          </>
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
