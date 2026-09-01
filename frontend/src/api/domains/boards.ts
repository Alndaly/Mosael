import { api } from "@/api/transport";

/** 创意画板上的一项；表单与运行态归节点自己所有。 */
export interface BoardItem {
  id: string;
  kind: "note" | "image" | "video" | "audio" | "frame";
  x: number;
  y: number;
  width?: number;
  height?: number;
  text?: string;
  color?: string;
  asset_id?: string;
  form?: {
    prompt?: string;
    provider?: string;
    provider_profile_id?: string;
    model?: string;
    mode?: string;
    voice_id?: string;
    parameters?: Record<string, unknown>;
    source_assets?: { asset_id: string; role: string }[];
    mentioned_asset_ids?: string[];
    prompt_document?: { type?: string; content?: unknown[]; [key: string]: unknown };
  };
  run?: {
    status: "idle" | "queued" | "running" | "succeeded" | "failed" | "cancelled";
    job_id?: string;
    error?: string;
  };
  /** @deprecated 仅用于读取升级前的画布。 */
  job_id?: string;
  /** @deprecated 仅用于读取升级前的画布。 */
  error?: string;
  move_children?: boolean;
}

export interface BoardEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

export interface BoardCanvas {
  items: BoardItem[];
  edges: BoardEdge[];
}

export interface Board {
  id: string;
  workspace_id: string;
  name: string;
  canvas: BoardCanvas;
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

export function updateBoard(
  boardId: string,
  body: { workspace_id: string; name?: string; canvas?: BoardCanvas },
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
    item_id: string;
    kind: "image" | "video";
    prompt: string;
    x: number;
    y: number;
    provider?: string;
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
  body: { workspace_id: string; item_id: string; text: string; voice_id?: string; x?: number; y?: number },
): Promise<Board> {
  return api<Board>(`/api/boards/${boardId}/speak`, { method: "POST", body: JSON.stringify(body) });
}

export function trimOnBoard(
  boardId: string,
  body: {
    workspace_id: string;
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
