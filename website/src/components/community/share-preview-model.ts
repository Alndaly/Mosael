/**
 * 分享内容预览的**纯几何计算**:payload → 一张 SVG 需要的东西(viewBox、矩形、连线、标签)。
 *
 * 为什么单独一个 `.ts` 而不是直接写进 `share-preview.tsx`:node 测试 import 不了 TSX
 * (见 `test/source-aliases.mjs` 的说明),而「29 个节点画成 29 个矩形」这种规则必须被
 * 真实 fixture 钉住。组件只负责把这份模型画成 `<svg>`,规则都在这里 —— 服务端和
 * `node --test` 跑的是同一份。
 *
 * 同一个文件也给**无限画布**提供 `toFlowGraph()`:它和 `buildSharePreview()` 都走
 * `drawContent()`(同一份解析、同一个 {@link PREVIEW_LIMIT}),只是前者要 xyflow 的
 * nodes / edges,后者要 SVG 的矩形 / 线段。静态预览和可浏览画布不会各画一套。
 *
 * **输入的两种形状**(和云端存的一致,见 cloud 的 seed / 前端 `api/domains/shares.ts`):
 *
 * - 工作流:`{ format, version, name, description, graph: { meta, nodes: [{ id, type, name,
 *   position: { x, y }, config }], edges: [{ id, source, target }] } }` —— 节点有坐标;
 * - 画布:上传的是画板工程文件 `{ format, version, name, canvas: { items: [{ id, kind, x, y,
 *   width?, height? }], edges: BoardEdge[], markers? } }`(见 `frontend/.../boardTransfer.ts`);
 *   裸的 `{ items, edges }` 也认。`BoardEdge` 是 `{ id, source, target, label? }`,字段读自
 *   `frontend/src/api/domains/boards.ts`(不是猜的)。
 *
 * 插件(`kind=plugin`)的 payload 是 manifest,**没有坐标**,所以这里直接返回 null。
 */

/** 一次最多画这么多节点 / 格子。 */
export const PREVIEW_LIMIT = 200;

/** 内容四周留白(viewBox 单位),免得边框贴着最外一圈矩形。 */
const PREVIEW_PADDING = 24;

/**
 * 工作流节点的默认框。
 *
 * 工作流的 payload **只存位置,不存宽高**(见真实的 `public/workflows/*.mosael-workflow.json`)。
 * 尺寸照工作流画布聚焦节点时用的 210×72(见 `frontend/src/features/workflows/WorkflowEditor.tsx`),
 * 这样 `position` 之间的正常间距不会把节点叠在一起。
 */
const WORKFLOW_NODE_WIDTH = 210;
const WORKFLOW_NODE_HEIGHT = 72;
const WORKFLOW_NODE_RADIUS = 8;

/**
 * 画布格子的默认宽高。**抄自** `frontend/src/features/boards/boardNodes.ts` 的 `DEFAULT_SIZE`
 * (那边按 `item.kind` 定),这里不能 import —— 官网和前端是两个 package。payload 里缺
 * `width` / `height` 的格子按这张表补,和后端 / 画布自己看到的尺寸一致。
 */
const BOARD_DEFAULT_SIZE: Record<string, { width: number; height: number }> = {
  note: { width: 220, height: 140 },
  image: { width: 260, height: 180 },
  video: { width: 320, height: 200 },
  audio: { width: 280, height: 72 },
  frame: { width: 420, height: 300 },
  scene: { width: 320, height: 220 },
  document: { width: 320, height: 300 },
  entity: { width: 220, height: 280 },
  sequence: { width: 560, height: 400 },
};

/** 未知 kind 的格子也得画出来,给一个中性的默认尺寸。 */
const BOARD_FALLBACK_SIZE = { width: 260, height: 180 };
const BOARD_ITEM_RADIUS = 6;

/** 节点名最多留几个字(含省略号)。再多就把矩形挤满了。 */
const LABEL_MAX_CHARS = 12;

/** 淡色只有这几种;组件按序号取现有 token 的 class(同类同色)。 */
const TINT_COUNT = 5;

/**
 * 常见的 kind → 淡色序号。
 *
 * 「同类同色」是要求,不是「所有 kind 各一种颜色」—— 调色板只有 5 档。表里没有的 kind
 * 走稳定 hash,同一种 kind 仍然拿到同一个颜色。
 */
const KIND_TINTS: Record<string, number> = {
  // 画布格子
  note: 0,
  image: 1,
  video: 2,
  audio: 3,
  frame: 4,
  scene: 1,
  document: 2,
  entity: 3,
  sequence: 0,
  // 工作流节点
  start: 0,
  condition: 1,
  llm: 2,
  plugin_tool: 3,
  output: 4,
  template: 1,
  notify: 3,
  browser_open: 2,
  browser_evaluate: 2,
  browser_close: 2,
  social_link: 1,
  social_metrics: 1,
  quote_check: 1,
  note_create: 0,
};

export type PreviewRect = {
  x: number;
  y: number;
  width: number;
  height: number;
  /** 矩形圆角(viewBox 单位)。 */
  radius: number;
  /** 节点 / 格子种类。同类同色,组件按 tint 取淡色。 */
  kind: string;
  tint: number;
  /** 要画在矩形里的短标签;没有就是不画 `<text>`。 */
  label: string | null;
};

export type PreviewLine = { x1: number; y1: number; x2: number; y2: number };

export type SharePreviewModel = {
  kind: "workflow" | "board";
  /** 自动适应内容范围的 `viewBox`(四舍五入到两位小数)。 */
  viewBox: string;
  /** viewBox 的宽 / 高,组件用它算标签字号。 */
  width: number;
  height: number;
  rects: PreviewRect[];
  lines: PreviewLine[];
  /** 有效内容总数(含超过上限没画的)。 */
  total: number;
  /** 因为超过 {@link PREVIEW_LIMIT} 没画的节点 / 格子数;0 表示全画了。 */
  hidden: number;
  /** 标签字号(viewBox 单位),按 viewBox 宽度算,保证缩放后还能读。 */
  labelSize: number;
};

type Dict = Record<string, unknown>;

/** 一个带 id / 位置 / 尺寸 / 种类的矩形,还没决定淡色和截断后的标签。 */
type RawRect = Omit<PreviewRect, "tint" | "label"> & {
  id: string;
  /**
   * SVG 预览画在框里的短标签。**只有工作流有**(画布格子照旧不画 —— 老行为),
   * 无限画布用的是下面的 `name`。
   */
  label: string | null;
  /** 完整显示名(工作流的 `name` / 画布格子的 `title`);无限画布用它,不截断。 */
  name: string | null;
};

type ParsedEdge = { id: string; source: string; target: string };

type ParsedContent = { rects: RawRect[]; edges: ParsedEdge[] };

function dict(value: unknown): Dict | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Dict) : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function tintFor(kind: string): number {
  const known = KIND_TINTS[kind];
  if (known !== undefined) return known;
  let hash = 0;
  for (const char of kind) hash = (hash * 31 + (char.codePointAt(0) ?? 0)) >>> 0;
  return hash % TINT_COUNT;
}

/**
 * 边的两端只留下能找回矩形的那些;字段就是 `source` / `target`(BoardEdge 和 workflow edge 同形)。
 *
 * 顺手带上 id(缺了就用 `source->target` 合成):SVG 预览不用它,但 xyflow 用 id 做 React key
 * 和边的查表键。重名的边补后缀,别让两条边在画布上互相覆盖。
 */
function readEdges(value: unknown): ParsedEdge[] {
  if (!Array.isArray(value)) return [];
  const edges: ParsedEdge[] = [];
  const used = new Set<string>();
  for (const raw of value) {
    const edge = dict(raw);
    if (!edge) continue;
    const source = text(edge.source);
    const target = text(edge.target);
    if (!source || !target) continue;
    const base = text(edge.id) ?? `${source}->${target}`;
    let id = base;
    for (let suffix = 2; used.has(id); suffix += 1) id = `${base}#${suffix}`;
    used.add(id);
    edges.push({ id, source, target });
  }
  return edges;
}

/** 工作流:必须有 `graph.nodes` 数组;节点至少要有 id + 有限坐标。 */
function readWorkflow(payload: unknown): ParsedContent | null {
  const root = dict(payload);
  const graph = root ? dict(root.graph) : null;
  if (!graph || !Array.isArray(graph.nodes)) return null;

  const rects: RawRect[] = [];
  for (const raw of graph.nodes) {
    const node = dict(raw);
    if (!node) continue;
    const id = text(node.id);
    const position = dict(node.position);
    const x = position ? finite(position.x) : null;
    const y = position ? finite(position.y) : null;
    if (!id || x === null || y === null) continue;
    rects.push({
      id,
      x: round(x),
      y: round(y),
      width: WORKFLOW_NODE_WIDTH,
      height: WORKFLOW_NODE_HEIGHT,
      radius: WORKFLOW_NODE_RADIUS,
      kind: text(node.type) ?? "node",
      label: text(node.name),
      name: text(node.name),
    });
  }

  if (rects.length === 0) return null;
  return { rects, edges: readEdges(graph.edges) };
}

/**
 * 画布:格子至少要有有限坐标,宽高缺省按 kind 补。
 *
 * 用户传到社区的是一份画板工程文件(`{ format: "mosael.board", version, name, canvas }`,
 * 见 `frontend/src/features/boards/boardTransfer.ts`),`items` / `edges` 在 `canvas` 里面;
 * 也接受裸的 `BoardCanvas`(任务里说的 `{ items, edges, markers? }`)。两种都认,是因为
 * 社区只校验「payload 是 JSON」,两种形状都已经有人传。
 */
function readBoard(payload: unknown): ParsedContent | null {
  const root = dict(payload);
  const canvas = root && Array.isArray(root.items) ? root : root ? dict(root.canvas) : null;
  if (!canvas || !Array.isArray(canvas.items)) return null;

  const rects: RawRect[] = [];
  for (const raw of canvas.items) {
    const item = dict(raw);
    if (!item) continue;
    const id = text(item.id);
    const x = finite(item.x);
    const y = finite(item.y);
    if (!id || x === null || y === null) continue;
    const kind = text(item.kind) ?? "item";
    const preset = BOARD_DEFAULT_SIZE[kind] ?? BOARD_FALLBACK_SIZE;
    const width = finite(item.width);
    const height = finite(item.height);
    rects.push({
      id,
      x: round(x),
      y: round(y),
      width: width !== null && width > 0 ? round(width) : preset.width,
      height: height !== null && height > 0 ? round(height) : preset.height,
      radius: BOARD_ITEM_RADIUS,
      kind,
      // SVG 预览一直没给画布格子画字;这里保持 null,名字给无限画布用(见 `name`)。
      label: null,
      name: text(item.title),
    });
  }

  if (rects.length === 0) return null;
  return { rects, edges: readEdges(canvas.edges) };
}

/**
 * 一份「准备画」的内容:已经套过 {@link PREVIEW_LIMIT}、边已经丢掉指向没画节点的。
 *
 * 静态 SVG 预览和无限画布都从这份内容出发 —— 一份 29 个节点的工作流不会在画布里变成
 * 另一组坐标,也不会一个画 29 个、一个画 28 个。
 */
type DrawnContent = {
  kind: "workflow" | "board";
  /** 前 {@link PREVIEW_LIMIT} 个节点 / 格子。 */
  nodes: RawRect[];
  /** 两端都画了的边(顺序与 payload 一致)。 */
  edges: ParsedEdge[];
  /** 有效内容总数(含超过上限没画的)。 */
  total: number;
  /** 因为超过上限没画的节点 / 格子数;0 表示全画了。 */
  hidden: number;
};

/** 解析 + 套上限 + 丢掉悬空边;没有可画的东西时返回 null。 */
function drawContent(kind: string, payload: unknown): DrawnContent | null {
  if (kind !== "workflow" && kind !== "board") return null;
  const parsed = kind === "workflow" ? readWorkflow(payload) : readBoard(payload);
  if (!parsed) return null;

  const total = parsed.rects.length;
  if (total === 0) return null;

  const nodes = parsed.rects.slice(0, PREVIEW_LIMIT);
  const drawn = new Set(nodes.map((node) => node.id));
  return {
    kind,
    nodes,
    edges: parsed.edges.filter((edge) => drawn.has(edge.source) && drawn.has(edge.target)),
    total,
    hidden: total - nodes.length,
  };
}

/**
 * 把 payload 变成一张 SVG 的模型。
 *
 * @param kind 分享类型(云端的 `workflow` / `board` / `plugin`)
 * @param payload `GET /shares/{id}/payload` 返回的 `payload` 原文
 * @returns 没有可画的东西(空内容 / 形状不对 / plugin / 未知 kind)时返回 `null`
 */
export function buildSharePreview(kind: string, payload: unknown): SharePreviewModel | null {
  const content = drawContent(kind, payload);
  return content ? buildModel(content) : null;
}

/**
 * 套上限、丢掉指向没画节点的边、算 viewBox、截标签。
 */
function buildModel(content: DrawnContent): SharePreviewModel {
  const { kind, nodes: drawn, edges, total, hidden } = content;

  // 超过上限的节点不画,也就不该留下指向它们的悬空线(drawContent 已经筛过一遍;
  // 这里按 id 查表,是为了取线段两端的矩形中心)。
  const indexById = new Map<string, number>();
  for (let index = 0; index < drawn.length; index += 1) indexById.set(drawn[index].id, index);

  const lines: PreviewLine[] = [];
  for (const edge of edges) {
    const sourceIndex = indexById.get(edge.source);
    const targetIndex = indexById.get(edge.target);
    if (sourceIndex === undefined || targetIndex === undefined) continue;
    const source = drawn[sourceIndex];
    const target = drawn[targetIndex];
    lines.push({
      x1: round(source.x + source.width / 2),
      y1: round(source.y + source.height / 2),
      x2: round(target.x + target.width / 2),
      y2: round(target.y + target.height / 2),
    });
  }

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const rect of drawn) {
    minX = Math.min(minX, rect.x);
    minY = Math.min(minY, rect.y);
    maxX = Math.max(maxX, rect.x + rect.width);
    maxY = Math.max(maxY, rect.y + rect.height);
  }

  // 内容范围 + 留白 = viewBox。不写死画布尺寸:一份 29 节点的工作流和一块两格画布
  // 各自铺满自己的内容。
  const width = round(maxX - minX + PREVIEW_PADDING * 2);
  const height = round(maxY - minY + PREVIEW_PADDING * 2);

  // 标签字号跟着 viewBox 宽度走:大图缩得狠,字就得大一点,不然一个像素都看不见。
  // 上下限只是别让一块两格画布的字大得离谱。
  const labelSize = Math.max(10, Math.min(48, Math.round(width / 70)));

  return {
    kind,
    viewBox: `${round(minX - PREVIEW_PADDING)} ${round(minY - PREVIEW_PADDING)} ${width} ${height}`,
    width,
    height,
    rects: drawn.map((rect) => ({
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      radius: rect.radius,
      kind: rect.kind,
      tint: tintFor(rect.kind),
      label: rect.label ? truncateLabel(rect.label, rect.width, labelSize) : null,
    })),
    lines,
    total,
    hidden,
    labelSize,
  };
}

/**
 * 无限画布要的一份图:xyflow 的节点 / 边。
 *
 * 和 {@link buildSharePreview} **同源**:都走 `drawContent`(同一份解析、同一个
 * {@link PREVIEW_LIMIT}),这里只是把矩形 / 线段换成 xyflow 能吃的 nodes / edges。
 * 组件(`share-canvas.tsx`)只负责画,不重新解释 payload。
 */
export type ShareFlowNodeData = {
  /** 圆角框里的名字(工作流的 `name` / 画布格子的 `title`;都没有就退回 kind)。 */
  label: string;
  /** 节点 / 格子种类。同类同色,和 SVG 预览同一套 {@link tintFor}。 */
  kind: string;
  /** 淡色序号(0..{@link TINT_COUNT}-1)。 */
  tint: number;
};

export type ShareFlowNode = {
  id: string;
  /** 自定义节点类型;组件里按它注册圆角框,不用默认方块。 */
  type: "share";
  position: { x: number; y: number };
  width: number;
  height: number;
  data: ShareFlowNodeData;
};

export type ShareFlowEdge = { id: string; source: string; target: string };

export type ShareFlowGraph = {
  kind: "workflow" | "board";
  nodes: ShareFlowNode[];
  edges: ShareFlowEdge[];
  /** 有效内容总数(含超过上限没画的)。 */
  total: number;
  /** 因为超过 {@link PREVIEW_LIMIT} 没画的节点 / 格子数;0 表示全画了。 */
  hidden: number;
};

/**
 * payload → 只读无限画布的 nodes / edges。
 *
 * @param kind 分享类型(云端的 `workflow` / `board` / `plugin`)
 * @param payload `GET /shares/{id}/payload` 返回的 `payload` 原文
 * @returns 没有几何可画(空内容 / 形状不对 / plugin / 未知 kind)时返回 `null`
 */
export function toFlowGraph(kind: string, payload: unknown): ShareFlowGraph | null {
  const content = drawContent(kind, payload);
  if (!content) return null;

  return {
    kind: content.kind,
    nodes: content.nodes.map((node) => ({
      id: node.id,
      type: "share",
      position: { x: node.x, y: node.y },
      width: node.width,
      height: node.height,
      data: {
        label: node.name ?? node.label ?? node.kind,
        kind: node.kind,
        tint: tintFor(node.kind),
      },
    })),
    edges: content.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
    total: content.total,
    hidden: content.hidden,
  };
}

/** 只留前几个字。`maxChars` 是按矩形宽度和字号算的,再封顶 {@link LABEL_MAX_CHARS}。 */
function truncateLabel(label: string, rectWidth: number, labelSize: number): string | null {
  const chars = Array.from(label);
  if (chars.length === 0) return null;
  const maxChars = Math.max(2, Math.min(LABEL_MAX_CHARS, Math.floor((rectWidth - 16) / (labelSize * 0.6))));
  if (chars.length <= maxChars) return chars.join("");
  return `${chars.slice(0, maxChars - 1).join("")}…`;
}
