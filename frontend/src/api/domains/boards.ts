import { api } from "@/api/transport";

/** 创意画板上的一项；表单与运行态归节点自己所有。 */
export interface BoardItem {
  id: string;
  kind: "note" | "image" | "video" | "audio" | "frame" | "scene" | "document";
  /** 用户给这一格起的名字。**每种都有、只此一处**(分组框的名字也在这,不在 text)。
   *  没有 = 没起名,显示种类名(见 boardNodes.itemName)。和后端 canvas._normalize_title 同形。 */
  title?: string;
  x: number;
  y: number;
  width?: number;
  height?: number;
  text?: string;
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
     *  服务端存的时候就把它摘掉(后端 canvas._drop_detached_sources)。 */
    source_assets?: { asset_id: string; role: string; from?: string }[];
    mentioned_asset_ids?: string[];
    /** 这一格是**从哪份素材截的哪一段**(剪一段的产出)。和后端 canvas._normalize_trim 同形。 */
    trim?: { asset_id: string; start: number; end: number; mute: boolean };
    prompt_document?: { type?: string; content?: unknown[]; [key: string]: unknown };
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
 */
export type BoardProducer = "generate" | "speak" | "trim" | "write";

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
}

/** 在画板上跑一次产出者:产出落在哪一格(`item_id`,新的一格就是新 id)、谁来做、表单是什么。 */
export type BoardRunRequest = {
  [P in BoardProducer]: {
    producer: P;
    item_id: string;
    /** 宿主那一格的种类 —— 必须是这个产出者能挂的。 */
    kind: BoardItem["kind"];
    x: number;
    y: number;
    form: BoardRunForms[P];
  };
}[BoardProducer];

/** 画板上的一切产出(生成、写字、念出来、截一段)都走这一条。返回摆好占位(写字是写完)的画板。 */
export function runOnBoard(
  boardId: string,
  body: BoardRunRequest & { workspace_id: string; base_revision: number },
): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}/run`, { method: "POST", body: JSON.stringify(body) });
}
