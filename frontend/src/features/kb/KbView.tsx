import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FileText, FileUp, Link2, Loader2, NotebookPen, Search, Tag, Trash2 } from "lucide-react";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, ModalShell } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { TagsDialog } from "@/features/media/TagsDialog";

type KbDocument = components["schemas"]["KbDocumentOut"];
type KbSearchResult = components["schemas"]["KbSearchResultOut"];

/**
 * 知识库(计划 §6.9 / Phase 13):创作资料的第二大脑 —— 脚本、文案、
 * 风格指南、网页资料统一 markdown 入库,FTS 检索,智能体可通过
 * search_kb / read_kb_document 使用同一份数据。
 */
export function KbView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");
  const [urlDialogOpen, setUrlDialogOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<KbDocument | null>(null);

  const documents = useQuery({
    queryKey: ["kb-documents", workspace.id],
    queryFn: () => api<KbDocument[]>(`/api/kb/documents?workspace_id=${workspace.id}`),
  });
  const search = useQuery({
    queryKey: ["kb-search", workspace.id, query],
    enabled: query.trim().length > 0,
    queryFn: () => api<KbSearchResult[]>(`/api/kb/search?workspace_id=${workspace.id}&q=${encodeURIComponent(query)}`),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["kb-documents", workspace.id] });

  const createNote = useMutation({
    mutationFn: () =>
      api<KbDocument>("/api/kb/documents", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, title: t("kbUntitled"), content: "" }),
      }),
    onSuccess: (doc) => {
      setSelectedId(doc.id);
      setQuery("");
      void refresh();
    },
  });
  const importUrl = useMutation({
    mutationFn: (url: string) =>
      api<KbDocument>("/api/kb/documents/import-url", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, url }),
      }),
    onSuccess: (doc) => {
      setUrlDialogOpen(false);
      setSelectedId(doc.id);
      void refresh();
    },
  });
  // 文件统一交给后端转换引擎(MinerU/markitdown):PDF/Word/PPT/Excel 都能进。
  const importFile = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.set("workspace_id", workspace.id);
      form.set("file", file);
      return api<KbDocument>("/api/kb/documents/import-file", { method: "POST", body: form });
    },
    onSuccess: (doc) => {
      setSelectedId(doc.id);
      void refresh();
    },
  });
  const removeDoc = useMutation({
    mutationFn: (id: string) => api(`/api/kb/documents/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      setDeleting(null);
      if (selectedId === id) setSelectedId(null);
      void refresh();
    },
  });

  const listed = documents.data ?? [];
  const selected = listed.find((doc) => doc.id === selectedId) ?? listed[0] ?? null;
  const searching = query.trim().length > 0;

  if (documents.isSuccess && listed.length === 0) {
    return (
      <div className="feature-view">
        <EmptyState
          icon={<BookOpen size={22} />}
          title={t("kbEmptyTitle")}
          body={t("kbEmptyBody")}
          action={
            <div className="kb-empty-actions">
              <Button size="sm" onClick={() => createNote.mutate()}>
                <NotebookPen size={13} /> {t("kbNewNote")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => setUrlDialogOpen(true)}>
                <Link2 size={13} /> {t("kbImportUrl")}
              </Button>
            </div>
          }
        />
        <KbUrlDialog
          open={urlDialogOpen}
          pending={importUrl.isPending}
          error={importUrl.isError ? String((importUrl.error as Error).message) : null}
          onCancel={() => setUrlDialogOpen(false)}
          onSubmit={(url) => importUrl.mutate(url)}
        />
      </div>
    );
  }

  return (
    <div className="feature-view">
      <div className="plugins-shell">
        <aside className="plugins-list kb-list panel">
          <div className="panel-head">
            <h2>{t("kbTitle")}</h2>
            <div className="kb-list-actions">
              <Button size="icon-sm" variant="ghost" title={t("kbNewNote")} onClick={() => createNote.mutate()}>
                <NotebookPen size={14} />
              </Button>
              <Button size="icon-sm" variant="ghost" title={t("kbImportUrl")} onClick={() => setUrlDialogOpen(true)}>
                <Link2 size={14} />
              </Button>
              <Button asChild size="icon-sm" variant="ghost" title={t("kbImportFile")}>
                <label>
                  <input
                    type="file"
                    accept=".md,.txt,.markdown,.pdf,.docx,.doc,.pptx,.xlsx,.xls,.html,.htm,.csv,.epub"
                    className="hidden-input"
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0];
                      if (file) importFile.mutate(file);
                      event.currentTarget.value = "";
                    }}
                  />
                  {importFile.isPending ? <Loader2 size={14} className="spin" /> : <FileUp size={14} />}
                </label>
              </Button>
            </div>
          </div>
          <div className="kb-search">
            <Search size={13} />
            <input
              value={query}
              placeholder={t("kbSearchPlaceholder")}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          {(importFile.isError || importFile.isPending) && (
            <p className={importFile.isPending ? "kb-import-status" : "kb-import-status error"}>
              {importFile.isPending ? t("kbConverting") : String((importFile.error as Error).message)}
            </p>
          )}
          <div className="plugins-list-body">
            {searching
              ? (search.data ?? []).map((hit) => (
                  <button
                    key={`${hit.document_id}-${hit.chunk_index}`}
                    type="button"
                    className={selected?.id === hit.document_id ? "kb-hit active" : "kb-hit"}
                    onClick={() => setSelectedId(hit.document_id)}
                  >
                    <strong>{hit.title}</strong>
                    <span>{hit.snippet.slice(0, 90)}</span>
                  </button>
                ))
              : listed.map((doc) => (
                  <button
                    key={doc.id}
                    type="button"
                    className={selected?.id === doc.id ? "plugins-item active" : "plugins-item"}
                    onClick={() => setSelectedId(doc.id)}
                  >
                    <span className="kb-item-icon">{sourceIcon(doc.source_type)}</span>
                    <span className="plugins-item-text">
                      <strong>{doc.title}</strong>
                      <small>
                        {sourceLabel(doc.source_type, t)}
                        {(doc.tags ?? []).length > 0 ? ` · ${(doc.tags ?? []).join(" / ")}` : ""}
                      </small>
                    </span>
                  </button>
                ))}
            {searching && search.isSuccess && (search.data ?? []).length === 0 && (
              <div className="empty-inline">
                <Search size={14} /> {t("kbNoResults")}
              </div>
            )}
          </div>
        </aside>
        <div className="plugins-detail">
          {selected ? (
            <KbDocumentEditor key={selected.id} documentId={selected.id} onDelete={() => setDeleting(selected)} />
          ) : (
            <EmptyState icon={<BookOpen size={22} />} title={t("kbEmptyTitle")} body={t("kbEmptyBody")} />
          )}
        </div>
      </div>

      <KbUrlDialog
        open={urlDialogOpen}
        pending={importUrl.isPending}
        error={importUrl.isError ? String((importUrl.error as Error).message) : null}
        onCancel={() => setUrlDialogOpen(false)}
        onSubmit={(url) => importUrl.mutate(url)}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("kbDeleteBody")}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && removeDoc.mutate(deleting.id)}
      />
    </div>
  );
}

function KbDocumentEditor({ documentId, onDelete }: { documentId: string; onDelete: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [editingTags, setEditingTags] = React.useState(false);
  const [dirty, setDirty] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [content, setContent] = React.useState("");

  const doc = useQuery({
    queryKey: ["kb-document", documentId],
    queryFn: () => api<KbDocument>(`/api/kb/documents/${documentId}`),
  });

  React.useEffect(() => {
    if (doc.data) {
      setTitle(doc.data.title);
      setContent(doc.data.content ?? "");
      setDirty(false);
    }
  }, [doc.data?.id, doc.data?.updated_at]);

  const save = useMutation({
    mutationFn: (body: { title?: string; content?: string; tags?: string[] }) =>
      api<KbDocument>(`/api/kb/documents/${documentId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      setDirty(false);
      setEditingTags(false);
      void qc.invalidateQueries({ queryKey: ["kb-document", documentId] });
      void qc.invalidateQueries({ queryKey: ["kb-documents"] });
    },
  });

  if (!doc.data) return null;
  const data = doc.data;

  return (
    <div className="plugins-detail-body kb-editor">
      <div className="kb-editor-head">
        <input
          className="kb-title-input"
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            setDirty(true);
          }}
        />
        <div className="kb-editor-tools">
          {dirty ? (
            <Button size="sm" disabled={save.isPending} onClick={() => save.mutate({ title: title.trim() || data.title, content })}>
              {save.isPending ? <Loader2 size={13} className="spin" /> : null} {t("kbSave")}
            </Button>
          ) : (
            <span className="kb-saved-hint">{t("kbSaved")}</span>
          )}
          <Button size="icon-sm" variant="ghost" title={t("editTags")} onClick={() => setEditingTags(true)}>
            <Tag size={14} />
          </Button>
          <Button size="icon-sm" variant="ghost" className="sched-delete" title={t("delete")} onClick={onDelete}>
            <Trash2 size={14} />
          </Button>
        </div>
      </div>
      <div className="kb-editor-meta">
        <span>{sourceLabel(data.source_type, t)}</span>
        {data.source_ref && data.source_type === "url" && (
          <a href={data.source_ref} target="_blank" rel="noreferrer">
            {data.source_ref}
          </a>
        )}
        {(data.tags ?? []).map((tag) => (
          <span className="tag-chip readonly" key={tag}>
            {tag}
          </span>
        ))}
      </div>
      <textarea
        className="kb-content-input"
        value={content}
        placeholder={t("kbContentPlaceholder")}
        onChange={(event) => {
          setContent(event.target.value);
          setDirty(true);
        }}
      />
      <TagsDialog
        open={editingTags}
        title={t("editTags")}
        initialTags={data.tags ?? []}
        onCancel={() => setEditingTags(false)}
        onSubmit={(tags) => save.mutate({ tags })}
      />
    </div>
  );
}

function KbUrlDialog({
  open,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (url: string) => void;
}) {
  const t = useI18n();
  const [url, setUrl] = React.useState("");
  React.useEffect(() => {
    if (open) setUrl("");
  }, [open]);
  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onCancel()} title={t("kbImportUrl")}>
      <div className="grid gap-3">
        <p className="text-[13px] text-muted-foreground">{t("kbImportUrlBody")}</p>
        <Input autoFocus value={url} placeholder="https://…" onChange={(event) => setUrl(event.target.value)} />
        {error && <p className="login-error">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={!/^https?:\/\//.test(url.trim()) || pending} onClick={() => onSubmit(url.trim())}>
            {pending ? <Loader2 size={13} className="spin" /> : null} {t("kbImport")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

function sourceIcon(sourceType: string) {
  if (sourceType === "url") return <Link2 size={14} />;
  if (sourceType === "file") return <FileText size={14} />;
  return <NotebookPen size={14} />;
}

function sourceLabel(sourceType: string, t: (key: MessageKey) => string): string {
  if (sourceType === "url") return t("kbSourceUrl");
  if (sourceType === "file") return t("kbSourceFile");
  return t("kbSourceNote");
}
