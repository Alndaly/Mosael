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
    /** 引擎音色那条路。和 voice_id **二选一** —— 与后端 BoardSpeak 同形。 */
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

export function generateOnBoard(
  boardId: string,
  body: {
    workspace_id: string;
    base_revision?: number;
    item_id: string;
    kind: "image" | "video";
    prompt: string;
    x: number;
    y: number;
    provider?: string;
    provider_profile_id?: string;
    model?: string;
    parameters?: Record<string, unknown>;
    source_assets?: { asset_id: string; role: string }[];
    form?: BoardItem["form"];
  },
): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}/generate`, { method: "POST", body: JSON.stringify(body) });
}

export function writeOnBoard(
  boardId: string,
  body: {
    workspace_id: string;
    base_revision?: number;
    item_id: string;
    prompt: string;
    provider_profile_id?: string;
    model?: string;
    source_assets?: string[];
    context?: string[];
  },
): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}/write`, { method: "POST", body: JSON.stringify(body) });
}

export function speakOnBoard(
  boardId: string,
  body: {
    workspace_id: string;
    base_revision?: number;
    item_id: string;
    text: string;
    /** 克隆音色(配音库里那一行)。和下面的引擎音色**二选一** —— 后端 BoardSpeak 的注释同源。 */
    voice_id?: string;
    engine?: string;
    engine_voice?: string;
    x?: number;
    y?: number;
  },
): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}/speak`, { method: "POST", body: JSON.stringify(body) });
}

export function trimOnBoard(
  boardId: string,
  body: {
    workspace_id: string;
    base_revision?: number;
    item_id: string;
    asset_id: string;
    start: number;
    end: number;
    mute?: boolean;
    x?: number;
    y?: number;
  },
): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}/trim`, { method: "POST", body: JSON.stringify(body) });
}
