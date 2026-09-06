import { api } from "@/api/transport";

export type NoteSource = {
  kind: "asset" | "message" | "board" | "note" | "url";
  id: string; label: string; quote: string;
  start?: number | null; end?: number | null; url?: string; revision?: number | null;
};
export type NoteContent = {
  title: string; markdown: string; project_id: string | null; tags: string[]; topics: string[];
  sources: NoteSource[]; favorite: boolean; trashed: boolean;
};
export type Note = NoteContent & {
  id: string; workspace_id: string; revision: number; created_at: string; updated_at: string;
};
export const emptyNote: NoteContent = { title: "", markdown: "", project_id: null, tags: [], topics: [], sources: [], favorite: false, trashed: false };
export function listNotes(workspaceId: string, q = "", trashed = false, offset = 0) {
  return api<Note[]>(`/api/notes?${new URLSearchParams({workspace_id: workspaceId, q, trashed: String(trashed), offset: String(offset), limit: "200"})}`);
}
export const getNote = (workspaceId: string, id: string) => api<Note>(`/api/notes/${id}?workspace_id=${encodeURIComponent(workspaceId)}`);
export const createNote = (workspaceId: string, body: Partial<NoteContent>) => api<Note>("/api/notes", { method: "POST", body: JSON.stringify({ ...emptyNote, ...body, workspace_id: workspaceId }) });
export const saveNote = (note: Note) => api<Note>(`/api/notes/${note.id}`, { method: "PATCH", body: JSON.stringify({ ...note, base_revision: note.revision }) });
export const appendNote = (note: Note, markdown: string, sources: NoteSource[]) => api<Note>(`/api/notes/${note.id}/append`, { method: "POST", body: JSON.stringify({ workspace_id: note.workspace_id, base_revision: note.revision, markdown, sources }) });
export const noteHref = (id: string, revision?: number | null) => `#/notes?note=${encodeURIComponent(id)}${revision ? `&revision=${revision}` : ""}`;
export function openNote(id: string) { window.location.hash = noteHref(id); }
