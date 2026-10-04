import type { components } from "@/api/generated/schema";
import { noteKeys } from "@/api/queryKeys";
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
/** `revision` 是当前第几版(版本号);`save_seq` 是保存序号,每次写入都 +1,下一次保存 / 恢复 / 彻底删除都带着它。 */
export type Note = NoteContent & {
  id: string; workspace_id: string; revision: number; save_seq: number; created_at: string; updated_at: string;
};
export const emptyNote: NoteContent = { title: "", markdown: "", project_id: null, tags: [], topics: [], sources: [], favorite: false, trashed: false };
/** 列表的筛选。**在服务端筛**,和分页同一层 —— 在已加载的那一页里筛,翻不到的就筛不到。 */
export type NoteListFilter = { trashed?: boolean; favorite?: boolean; topic?: string };
export function listNotes(workspaceId: string, q = "", { trashed = false, favorite = false, topic = "" }: NoteListFilter = {}, offset = 0) {
  return api<Note[]>(`/api/notes?${new URLSearchParams({workspace_id: workspaceId, q, trashed: String(trashed), favorite: String(favorite), topic, offset: String(offset), limit: "200"})}`);
}
/** 用到过的主题(最近改过的在前),给主题下拉 —— 同样不从已加载的那一页里凑。 */
export function listNoteTopics(workspaceId: string, trashed = false) {
  return api<string[]>(`/api/notes/topics?${new URLSearchParams({workspace_id: workspaceId, trashed: String(trashed)})}`);
}
export const getNote = (workspaceId: string, id: string) => api<Note>(`/api/notes/${id}?workspace_id=${encodeURIComponent(workspaceId)}`);
export const createNote = (workspaceId: string, body: Partial<NoteContent>) => api<Note>("/api/notes", { method: "POST", body: JSON.stringify({ ...emptyNote, ...body, workspace_id: workspaceId }) });
/** 内嵌浏览器顶栏「存成笔记」:整页(渲染后的 HTML,正文由后端挑)或选中的文字,带着来源链接与标题。 */
export const createNoteFromPage = (body: { workspace_id: string; url: string; title: string; html?: string; selection?: string }) =>
  api<Note>("/api/notes/from-page", { method: "POST", body: JSON.stringify(body) });
export const saveNote = (note: Note) => api<Note>(`/api/notes/${note.id}`, { method: "PATCH", body: JSON.stringify({ ...note, base_save_seq: note.save_seq }) });
// **不带 base_save_seq。** 追加到末尾与文档别处的编辑可交换,服务端按它当前的那份落库
// (见 backend/app/domain/notes.append_note);带上手里这份常常是旧的保存序号,只会把
// 一次正常的追加判成冲突。
export const appendNote = (note: Note, markdown: string, sources: NoteSource[]) => api<Note>(`/api/notes/${note.id}/append`, { method: "POST", body: JSON.stringify({ workspace_id: note.workspace_id, markdown, sources }) });
/** 永久删除(只对已在回收站里的)。带保存序号:别人刚改过的那一份不会被这次删掉。 */
export const purgeNote = (workspaceId: string, noteId: string, baseSaveSeq: number) =>
  api<void>(`/api/notes/${noteId}?${new URLSearchParams({ workspace_id: workspaceId, base_save_seq: String(baseSaveSeq) })}`, { method: "DELETE" });

/** 版本记录里的一版:哪一版、什么时候、怎么来的(origin)、谁写的。 */
export type NoteRevisionSummary = components["schemas"]["NoteRevisionOut"];
export type NoteRevision = NoteContent & { revision: number };
/** 版本记录:连续的手动编辑合成一项(那一组最新的一版);给 `group`(那一组第一版的号)列那一组里的每一版。 */
export const listNoteRevisions = (workspaceId: string, noteId: string, group?: number) =>
  api<NoteRevisionSummary[]>(`/api/notes/${noteId}/revisions?${new URLSearchParams({ workspace_id: workspaceId, ...(group ? { group: String(group) } : {}) })}`);
export const getNoteRevision = (workspaceId: string, noteId: string, revision: number) =>
  api<NoteRevision>(`/api/notes/${noteId}/revisions/${revision}?workspace_id=${encodeURIComponent(workspaceId)}`);
/** 把某个旧版本恢复成新的一版。baseSaveSeq 是手里这份的保存序号,和保存同一条乐观并发。 */
export const restoreNoteRevision = (workspaceId: string, noteId: string, baseSaveSeq: number, revision: number) =>
  api<Note>(`/api/notes/${noteId}/restore`, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId, base_save_seq: baseSaveSeq, revision }) });

/** 笔记来源里的一条对话消息原文(来源卡展开时看)。 */
export const getNoteSourceMessage = (workspaceId: string, messageId: string) =>
  api<{ content: string }>(`/api/notes/sources/message/${messageId}?workspace_id=${encodeURIComponent(workspaceId)}`);

export type NoteReference = components["schemas"]["NoteReferenceOut"];
export const getNoteReference = (workspaceId: string, id: string, revision?: number) =>
  api<NoteReference>(`/api/notes/${encodeURIComponent(id)}/reference?${new URLSearchParams({workspace_id: workspaceId, ...(revision ? {revision: String(revision)} : {})})}`);
export const noteReferenceQuery = (workspaceId: string, id: string, revision?: number) => ({
  queryKey: noteKeys.reference(workspaceId, id, revision),
  queryFn: () => getNoteReference(workspaceId, id, revision), enabled: Boolean(workspaceId && id), retry: false as const,
});
