import { api } from "@/api/transport";
import type { components } from "@/api/generated/schema";

/** 创意画板上的一项；表单与运行态归节点自己所有。 */
export interface BoardItem {
  id: string;
  /** `action` 工具格:跑一个工作流节点(插件工具、挑过的内置节点),产出新建成右边的几格。 */
  kind: "note" | "image" | "video" | "audio" | "frame" | "scene" | "document" | "action";
  /** 用户给这一格起的名字。**每种都有、只此一处**(分组框的名字也在这,不在 text)。
   *  没有 = 没起名,显示种类名(见 boardNodes.itemName)。和后端 canvas._normalize_title 同形。 */
  title?: string;
  x: number;
  y: number;
  width?: number;
  height?: number;
  text?: string;
  /** 正文格式。只有便签有;`json` 是工具格交回的结构化数据(按代码排版)。和后端 canvas.TEXT_FORMATS 同形。 */
  text_format?: "json";
  color?: string;
  asset_id?: string;
  scene_id?: string;
  note_id?: string;
  note_revision?: number;
  form?: {
    prompt?: string;
    provider?: string;
    provider_profile_id?: string;
    model?: string;
    mode?: string;
    voice_id?: string;
    /** 引擎音色那条路。和 voice_id **二选一** —— 与后端 producers.SpeakForm 同形。 */
    engine?: string;
    engine_voice?: string;
    parameters?: Record<string, unknown>;
    /** `from`:这一份是顺着哪一格连过来的线挂上的(手动挂的没有)。线断了、上游换了素材,
     *  服务端存的时候就把它摘掉(后端 canvas._drop_detached_bindings)。 */
    source_assets?: { asset_id: string; role: string; from?: string }[];
    mentioned_asset_ids?: string[];
    /** 这一格是**从哪份素材截的哪一段**(剪一段的产出)。和后端 canvas._normalize_trim 同形。 */
    trim?: { asset_id: string; start: number; end: number; mute: boolean };
    prompt_document?: { type?: string; content?: unknown[]; [key: string]: unknown };
    /** 工具格的节点配置(键就是节点声明的字段)。 */
    config?: Record<string, unknown>;
    /** 工具格上哪些字段接上游、接哪几格。值由服务端运行时从画布上取;线断了服务端就摘掉
     *  (后端 canvas._drop_detached_bindings)。 */
    bindings?: Record<string, { from: string }[]>;
    /** 这一格的产出者。排在表单最后(和后端摆占位时写的位置一致)。 */
    producer?: BoardProducer;
  };
  run?: {
    status: "idle" | "queued" | "running" | "succeeded" | "failed" | "cancelled";
    job_id?: string;
    error?: string;
  };
  move_children?: boolean;
}

export interface BoardEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

/** 位置书签。**和 items 平级,不是一种 item** —— 它不生成、不连线、没有素材;
 *  共用的形状与冲突规则在 features/markers 与 backend/app/domain/markers.py。 */
export interface BoardMarker {
  id: string;
  name: string;
  x: number;
  y: number;
  shortcut?: string;
}

export interface BoardCanvas {
  items: BoardItem[];
  edges: BoardEdge[];
  markers?: BoardMarker[];
}

export interface Board {
  id: string;
  workspace_id: string;
  name: string;
  canvas: BoardCanvas;
  revision: number;
  created_at: string;
  updated_at: string;
}

export function listBoards(workspaceId: string): Promise<Board[]> {
  return api<Board[]>(`/api/boards?workspace_id=${encodeURIComponent(workspaceId)}`);
}

export function getBoard(boardId: string, workspaceId: string): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}?workspace_id=${encodeURIComponent(workspaceId)}`);
}

export function createBoard(body: { workspace_id: string; name?: string }): Promise<Board> {
  return api<Board>("/api/boards", { method: "POST", body: JSON.stringify(body) });
}

/** 创建副本。在跑的那几格在副本里退回空槽(回执认的是原板),见后端 duplicate_board。 */
export function duplicateBoard(boardId: string, body: { workspace_id: string; name?: string }): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}/duplicate`, { method: "POST", body: JSON.stringify(body) });
}

export function updateBoard(
  boardId: string,
  body: { workspace_id: string; base_revision: number; name?: string; canvas?: BoardCanvas },
): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteBoard(boardId: string, workspaceId: string): Promise<void> {
  return api<void>(`/api/boards/${boardId}?workspace_id=${encodeURIComponent(workspaceId)}`, { method: "DELETE" });
}

/**
 * 画板上的产出者 —— 一格里「能产出东西」的那件事由谁来做(后端 boards/producers.py,ADR 0021)。
 * 写在那一格的 `form.producer` 上,面板照它挂(见 boardItemState.producerOf),不按种类猜。
 *
 * 四个内置的各有专门的面板;`node:<节点类型>` 是工具格跑的一个节点,表单由节点声明生成。
 */
export type BuiltinProducer = "generate" | "speak" | "trim" | "write";
export type NodeProducer = `node:${string}`;
export type BoardProducer = BuiltinProducer | NodeProducer;

export const NODE_PRODUCER_PREFIX = "node:";

export function isNodeProducer(producer: string | undefined | null): producer is NodeProducer {
  return Boolean(producer?.startsWith(NODE_PRODUCER_PREFIX));
}

/**
 * 一种格子还没有产出时挂哪个产出者(新放下的一格的缺省)。和后端 boards/producer_ids.SLOT_PRODUCERS 同一张表 ——
 * 放在这一层而不是画板功能里,因为画板之外也在新建格子(3D 场景页「拿去生成」建的画板)。
 */
const SLOT_PRODUCER: Partial<Record<BoardItem["kind"], BuiltinProducer>> = {
  note: "write",
  image: "generate",
  video: "generate",
  audio: "speak",
};

/**
 * 能产出、还没产出的一格补上它的产出者 —— **前端新建一格都过这一处**(画布的「添加」、拖进来 / 粘贴进来的
 * 素材、3D 场景页建的画板)。规则和后端 canvas.normalize_canvas 那一条相同(缺了按上面的表补,已经写明的
 * 不动,有了产出的媒体格不补;便签的产出是自己的正文,有字照样补):服务端存的时候也会补,但本地这一格
 * 要**当场**就挂得上面板,不能等下一次从服务端拉。自带的草稿(提示词、参考)原样留着,产出者排在最后
 * (和后端摆占位时写的位置一致,前端按 JSON 比对表单)。
 */
export function withSlotProducer<T extends Pick<BoardItem, "kind" | "asset_id" | "form">>(item: T): T {
  const producer = SLOT_PRODUCER[item.kind];
  if (!producer || item.form?.producer || (item.kind !== "note" && item.asset_id)) return item;
  const { producer: _none, ...draft } = item.form ?? {};
  return { ...item, form: { ...draft, producer } };
}

/** 这个人在画板上能用的一个产出者(后端 producers.describe):节点描述 + 挂在哪、能不能填空槽。 */
export type BoardProducerInfo = components["schemas"]["BoardProducerOut"];

/** 这个人在画板上能用的产出者:四个内置的,加上工具格能跑的节点(插件工具只列他自己接的)。 */
export function listBoardProducers(workspaceId: string): Promise<BoardProducerInfo[]> {
  return api<BoardProducerInfo[]>(`/api/boards/producers?workspace_id=${encodeURIComponent(workspaceId)}`);
}

/** 每个产出者收的表单。和后端 producers.*Form 同形 —— 表单在后端领域里校验。 */
export interface BoardRunForms {
  generate: {
    /** 发给模型的那句(可带运行时追加的图例)。 */
    prompt: string;
    provider?: string;
    provider_profile_id?: string;
    model?: string;
    parameters?: Record<string, unknown>;
    /** 发出去的输入素材:槽位挂的 + 正文里 @ 到的。 */
    source_assets?: { asset_id: string; role: string }[];
    /** 落在这一格上、用户可再次编辑的表单(不含运行时追加的图例)。 */
    item_form?: BoardItem["form"];
  };
  write: {
    prompt: string;
    provider_profile_id?: string;
    model?: string;
    /** 让模型看着写的素材(上游连过来的 + 正文里 @ 到的)。 */
    source_assets?: string[];
    /** 上游便签给的材料。 */
    context?: string[];
  };
  speak: {
    text: string;
    /** 克隆音色(配音库里那一行)。和下面的引擎音色**二选一**。 */
    voice_id?: string;
    engine?: string;
    engine_voice?: string;
  };
  trim: { asset_id: string; start: number; end: number; mute?: boolean };
  /** 工具格:节点配置 + 哪些字段接上游(值由服务端运行时从画布上取)。和后端 producers.NodeForm 同形。 */
  node: { config: Record<string, unknown>; bindings: Record<string, { from: string }[]> };
}

type RunTarget = {
  item_id: string;
  /** 宿主那一格的种类 —— 必须是这个产出者能挂的。 */
  kind: BoardItem["kind"];
  x: number;
  y: number;
};

/** 在画板上跑一次产出者:产出落在哪一格(`item_id`,新的一格就是新 id)、谁来做、表单是什么。 */
export type BoardRunRequest =
  | { [P in BuiltinProducer]: RunTarget & { producer: P; form: BoardRunForms[P] } }[BuiltinProducer]
  | (RunTarget & { producer: NodeProducer; form: BoardRunForms["node"] });

/** 画板上的一切产出(生成、写字、念出来、截一段)都走这一条。返回摆好占位(写字是写完)的画板。 */
export function runOnBoard(
  boardId: string,
  body: BoardRunRequest & { workspace_id: string; base_revision: number },
): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}/run`, { method: "POST", body: JSON.stringify(body) });
}
