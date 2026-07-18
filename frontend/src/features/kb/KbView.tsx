import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  FileText,
  FileUp,
  Link2,
  Loader2,
  NotebookPen,
  Plus,
  RotateCw,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { ConfirmDialog, ModalShell, RenameDialog } from "@/components/ui/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { KbTiptap } from "@/features/kb/KbTiptap";

type KbDataset = components["schemas"]["KbDatasetOut"];
type KbDocument = components["schemas"]["KbDocumentOut"];
type KbChunk = components["schemas"]["KbChunkOut"];
type KbSearchResult = components["schemas"]["KbSearchResultOut"];
type KbGraph = components["schemas"]["KbGraphOut"];

/** 后端 detail 错误解析:api() 抛的是原始响应体,统一取出 {"detail": ...}。 */
function errText(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // 非 JSON,原样返回
  }
  return raw;
}

/**
 * 知识库(Dify 式 datasets):工作区内多个命名知识库,每个含文档 + 分块 + 检索/图谱设置。
 * 详情分四页:文档 / 召回测试 / 知识图谱 / 设置。检索基线 FTS5,向量/Neo4j 图谱为可选增强。
 */
export function KbView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [datasetId, setDatasetId] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [renaming, setRenaming] = React.useState<KbDataset | null>(null);
  const [deleting, setDeleting] = React.useState<KbDataset | null>(null);

  const datasets = useQuery({
    queryKey: ["kb-datasets", workspace.id],
    queryFn: () => api<KbDataset[]>(`/api/kb/datasets?workspace_id=${workspace.id}`),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["kb-datasets", workspace.id] });

  const createDataset = useMutation({
    mutationFn: (body: { name: string; description: string }) =>
      api<KbDataset>("/api/kb/datasets", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, ...body }),
      }),
    onSuccess: (ds) => {
      setCreating(false);
      setDatasetId(ds.id);
      void refresh();
    },
  });
  const renameDataset = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api<KbDataset>(`/api/kb/datasets/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
    onSuccess: () => {
      setRenaming(null);
      void refresh();
    },
  });
  const removeDataset = useMutation({
    mutationFn: (id: string) => api(`/api/kb/datasets/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      setDeleting(null);
      if (datasetId === id) setDatasetId(null);
      void refresh();
    },
  });

  const listed = datasets.data ?? [];
  const selected = listed.find((ds) => ds.id === datasetId) ?? listed[0] ?? null;

  if (datasets.isSuccess && listed.length === 0) {
    return (
      <div className="feature-view">
        <EmptyState
          icon={<BookOpen size={22} />}
          title={t("kbEmptyTitle")}
          body={t("kbEmptyBody")}
          action={
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus size={13} /> {t("kbNewDataset")}
            </Button>
          }
        />
        <CreateDatasetDialog
          open={creating}
          pending={createDataset.isPending}
          onCancel={() => setCreating(false)}
          onSubmit={(body) => createDataset.mutate(body)}
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
            <Button size="icon-sm" variant="ghost" title={t("kbNewDataset")} onClick={() => setCreating(true)}>
              <Plus size={14} />
            </Button>
          </div>
          <div className="plugins-list-body">
            {listed.map((ds) => (
              <ContextMenu key={ds.id}>
                <ContextMenuTrigger asChild>
                  <button
                    type="button"
                    className={selected?.id === ds.id ? "plugins-item active" : "plugins-item"}
                    onClick={() => setDatasetId(ds.id)}
                  >
                    <span className="kb-item-icon">
                      <BookOpen size={14} />
                    </span>
                    <span className="plugins-item-text">
                      <strong>{ds.name}</strong>
                      <small>{t("kbDocCount").replace("{n}", String(ds.document_count))}</small>
                    </span>
                  </button>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem onSelect={() => setRenaming(ds)}>{t("rename")}</ContextMenuItem>
                  <ContextMenuSeparator />
                  <ContextMenuItem destructive onSelect={() => setDeleting(ds)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
          </div>
        </aside>
        <div className="plugins-detail kb-detail">
          {selected ? (
            <DatasetDetail key={selected.id} dataset={selected} workspace={workspace} />
          ) : (
            <EmptyState icon={<BookOpen size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
        </div>
      </div>

      <CreateDatasetDialog
        open={creating}
        pending={createDataset.isPending}
        onCancel={() => setCreating(false)}
        onSubmit={(body) => createDataset.mutate(body)}
      />
      <RenameDialog
        open={renaming !== null}
        title={t("rename")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        onSubmit={(name) => renaming && renameDataset.mutate({ id: renaming.id, name })}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("kbDeleteDatasetBody")}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && removeDataset.mutate(deleting.id)}
      />
    </div>
  );
}

function DatasetDetail({ dataset, workspace }: { dataset: KbDataset; workspace: Workspace }) {
  const t = useI18n();
  return (
    <div className="kb-dataset">
      <div className="kb-dataset-head">
        <div className="kb-dataset-head-main">
          <span className="kb-dataset-avatar">
            <BookOpen size={16} />
          </span>
          <div>
            <h2>{dataset.name}</h2>
            {dataset.description && <p>{dataset.description}</p>}
          </div>
          <Badge variant="secondary">{t("kbDocCount").replace("{n}", String(dataset.document_count))}</Badge>
        </div>
      </div>
      <Tabs defaultValue="docs" className="kb-tabs">
        <TabsList>
          <TabsTrigger value="docs">
            <FileText size={13} /> {t("kbTabDocs")}
          </TabsTrigger>
          <TabsTrigger value="recall">
            <Search size={13} /> {t("kbTabRecall")}
          </TabsTrigger>
          <TabsTrigger value="graph">
            <Sparkles size={13} /> {t("kbTabGraph")}
          </TabsTrigger>
          <TabsTrigger value="settings">{t("kbTabSettings")}</TabsTrigger>
        </TabsList>
        <TabsContent value="docs">
          <DocumentsTab dataset={dataset} workspace={workspace} />
        </TabsContent>
        <TabsContent value="recall">
          <RecallTestTab dataset={dataset} />
        </TabsContent>
        <TabsContent value="graph">
          <GraphTab dataset={dataset} />
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab dataset={dataset} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

const STATUS_VARIANT: Record<string, "secondary" | "default" | "outline"> = {
  completed: "secondary",
  error: "outline",
  processing: "default",
  queued: "outline",
};

function DocumentsTab({ dataset, workspace }: { dataset: KbDataset; workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [openDocId, setOpenDocId] = React.useState<string | null>(null);
  const [urlOpen, setUrlOpen] = React.useState(false);

  const documents = useQuery({
    queryKey: ["kb-documents", dataset.id],
    queryFn: () => api<KbDocument[]>(`/api/kb/datasets/${dataset.id}/documents`),
    // 有文档在处理时轮询,直到全部落定(异步摄取)。
    refetchInterval: (query) =>
      (query.state.data ?? []).some((d) => d.status === "queued" || d.status === "processing") ? 1000 : false,
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["kb-documents", dataset.id] });
    void qc.invalidateQueries({ queryKey: ["kb-datasets", workspace.id] });
  };

  const createNote = useMutation({
    mutationFn: () =>
      api<KbDocument>(`/api/kb/datasets/${dataset.id}/documents`, {
        method: "POST",
        body: JSON.stringify({ title: t("kbUntitled"), content: "" }),
      }),
    onSuccess: (doc) => {
      setOpenDocId(doc.id);
      refresh();
    },
  });
  const importUrl = useMutation({
    mutationFn: (url: string) =>
      api<KbDocument>(`/api/kb/datasets/${dataset.id}/documents/import-url`, {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
    onSuccess: () => {
      setUrlOpen(false);
      refresh();
    },
  });
  const importFile = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.set("file", file);
      return api<KbDocument>(`/api/kb/datasets/${dataset.id}/documents/import-file`, { method: "POST", body: form });
    },
    onSuccess: () => refresh(),
  });
  const removeDoc = useMutation({
    mutationFn: (id: string) => api(`/api/kb/documents/${id}`, { method: "DELETE" }),
    onSuccess: (_d, id) => {
      if (openDocId === id) setOpenDocId(null);
      refresh();
    },
  });
  const reindexDoc = useMutation({
    mutationFn: (id: string) => api<KbDocument>(`/api/kb/documents/${id}/reindex`, { method: "POST" }),
    onSuccess: () => refresh(),
  });

  if (openDocId) {
    return <DocumentDetail documentId={openDocId} onBack={() => setOpenDocId(null)} onChanged={refresh} />;
  }

  const docs = documents.data ?? [];
  return (
    <div className="kb-docs">
      <div className="kb-docs-actions">
        <Button size="sm" variant="outline" onClick={() => createNote.mutate()} disabled={createNote.isPending}>
          <NotebookPen size={13} /> {t("kbNewNote")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setUrlOpen(true)}>
          <Link2 size={13} /> {t("kbImportUrl")}
        </Button>
        <Button asChild size="sm" variant="outline">
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
            {importFile.isPending ? <Loader2 size={13} className="spin" /> : <FileUp size={13} />} {t("kbImportFile")}
          </label>
        </Button>
      </div>
      {importFile.isError && <p className="kb-inline-error">{errText(importFile.error)}</p>}

      {docs.length === 0 ? (
        <EmptyState icon={<FileText size={20} />} title={t("kbNoDocsTitle")} body={t("kbNoDocsBody")} />
      ) : (
        <div className="kb-doc-rows">
          {docs.map((doc) => (
            <div key={doc.id} className="kb-doc-row">
              <button type="button" className="kb-doc-open" onClick={() => setOpenDocId(doc.id)}>
                <span className="kb-doc-title">{doc.title}</span>
                <span className="kb-doc-meta">
                  <Badge
                    variant={STATUS_VARIANT[doc.status] ?? "default"}
                    className={doc.status === "error" ? "kb-badge-error" : undefined}
                  >
                    {t(`kbStatus_${doc.status}` as never)}
                  </Badge>
                  <span className="kb-doc-chunks timecode">{t("kbChunksN").replace("{n}", String(doc.chunk_count))}</span>
                  {doc.status === "error" && doc.error && <span className="kb-doc-errhint">{doc.error}</span>}
                </span>
              </button>
              <div className="kb-doc-row-tools">
                {doc.status === "error" && (
                  <Button size="icon-sm" variant="ghost" title={t("kbReindex")} onClick={() => reindexDoc.mutate(doc.id)}>
                    <RotateCw size={13} />
                  </Button>
                )}
                <Button size="icon-sm" variant="ghost" title={t("delete")} onClick={() => removeDoc.mutate(doc.id)}>
                  <Trash2 size={13} />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <KbUrlDialog
        open={urlOpen}
        pending={importUrl.isPending}
        error={importUrl.isError ? errText(importUrl.error) : null}
        onCancel={() => setUrlOpen(false)}
        onSubmit={(url) => importUrl.mutate(url)}
      />
    </div>
  );
}

function DocumentDetail({
  documentId,
  onBack,
  onChanged,
}: {
  documentId: string;
  onBack: () => void;
  onChanged: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [title, setTitle] = React.useState("");
  const [content, setContent] = React.useState("");
  const [dirty, setDirty] = React.useState(false);

  const doc = useQuery({
    queryKey: ["kb-document", documentId],
    queryFn: () => api<KbDocument>(`/api/kb/documents/${documentId}`),
  });
  const chunks = useQuery({
    queryKey: ["kb-chunks", documentId, doc.data?.updated_at],
    enabled: Boolean(doc.data),
    queryFn: () => api<KbChunk[]>(`/api/kb/documents/${documentId}/chunks`),
  });

  React.useEffect(() => {
    if (doc.data) {
      setTitle(doc.data.title);
      setContent(doc.data.content ?? "");
      setDirty(false);
    }
  }, [doc.data?.id, doc.data?.updated_at]);

  const save = useMutation({
    mutationFn: (body: { title?: string; content?: string }) =>
      api<KbDocument>(`/api/kb/documents/${documentId}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      setDirty(false);
      void qc.invalidateQueries({ queryKey: ["kb-document", documentId] });
      onChanged();
    },
  });

  if (!doc.data) return null;

  return (
    <div className="kb-doc-detail">
      <div className="kb-doc-detail-head">
        <Button size="sm" variant="ghost" onClick={onBack}>
          ← {t("back")}
        </Button>
        {dirty ? (
          <Button size="sm" disabled={save.isPending} onClick={() => save.mutate({ title: title.trim() || doc.data!.title, content })}>
            {save.isPending ? <Loader2 size={13} className="spin" /> : null} {t("kbSave")}
          </Button>
        ) : (
          <span className="kb-saved-hint">{t("kbSaved")}</span>
        )}
      </div>
      <input
        className="kb-title-input"
        value={title}
        onChange={(event) => {
          setTitle(event.target.value);
          setDirty(true);
        }}
      />
      <KbTiptap
        key={doc.data.id}
        initialMarkdown={doc.data.content ?? ""}
        onChange={(markdown) => {
          setContent(markdown);
          setDirty(true);
        }}
      />
      <div className="kb-chunks">
        <h3>{t("kbChunksTitle").replace("{n}", String((chunks.data ?? []).length))}</h3>
        <div className="kb-chunk-list">
          {(chunks.data ?? []).map((chunk) => (
            <div key={chunk.id} className="kb-chunk">
              <span className="kb-chunk-idx timecode">#{chunk.chunk_index + 1}</span>
              <p>{chunk.text}</p>
              <span className="kb-chunk-len timecode">{chunk.char_count}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RecallTestTab({ dataset }: { dataset: KbDataset }) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const run = useMutation({
    mutationFn: (q: string) =>
      api<KbSearchResult[]>(`/api/kb/datasets/${dataset.id}/retrieval-test`, {
        method: "POST",
        body: JSON.stringify({ query: q }),
      }),
  });

  return (
    <div className="kb-recall">
      <form
        className="kb-recall-bar"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim()) run.mutate(query.trim());
        }}
      >
        <Input value={query} placeholder={t("kbRecallPlaceholder")} onChange={(event) => setQuery(event.target.value)} />
        <Button type="submit" size="sm" disabled={!query.trim() || run.isPending}>
          {run.isPending ? <Loader2 size={13} className="spin" /> : <Search size={13} />} {t("kbRecallRun")}
        </Button>
      </form>
      <p className="kb-recall-hint">{t("kbRecallHint")}</p>
      {run.isSuccess && (run.data ?? []).length === 0 && (
        <div className="empty-inline">
          <Search size={14} /> {t("kbNoResults")}
        </div>
      )}
      <div className="kb-recall-results">
        {(run.data ?? []).map((hit, i) => (
          <div key={`${hit.document_id}-${hit.chunk_index}-${i}`} className="kb-recall-hit">
            <div className="kb-recall-hit-head">
              <strong>{hit.title}</strong>
              <span className="kb-recall-score timecode">{hit.score.toFixed(4)}</span>
              {hit.from_graph && <Badge variant="secondary">{t("kbFromGraph")}</Badge>}
            </div>
            <p>{hit.snippet}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function GraphTab({ dataset }: { dataset: KbDataset }) {
  const t = useI18n();
  const graph = useQuery({
    queryKey: ["kb-graph", dataset.id],
    queryFn: () => api<KbGraph>(`/api/kb/datasets/${dataset.id}/graph`),
  });
  if (graph.isLoading) return <div className="kb-graph-state"><Loader2 size={16} className="spin" /></div>;
  if (!graph.data?.enabled) {
    return (
      <EmptyState
        icon={<Sparkles size={20} />}
        title={t("kbGraphOffTitle")}
        body={t("kbGraphOffBody")}
      />
    );
  }
  if ((graph.data.nodes ?? []).length === 0) {
    return <EmptyState icon={<Sparkles size={20} />} title={t("kbGraphEmptyTitle")} body={t("kbGraphEmptyBody")} />;
  }
  // 力导向可视化在下一片接入;先列出实体作为占位。
  const entities = (graph.data.nodes ?? []).filter((n) => n.kind === "entity");
  return (
    <div className="kb-graph-placeholder">
      <p>{t("kbGraphEntities").replace("{n}", String(entities.length))}</p>
      <div className="kb-graph-chips">
        {entities.map((node) => (
          <span key={node.id} className="tag-chip readonly">
            {node.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function SettingsTab({ dataset }: { dataset: KbDataset }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [form, setForm] = React.useState({
    name: dataset.name,
    description: dataset.description,
    retrieval_mode: dataset.retrieval_mode,
    top_k: dataset.top_k,
    chunk_size: dataset.chunk_size,
    chunk_overlap: dataset.chunk_overlap,
    graph_enabled: dataset.graph_enabled,
  });
  const save = useMutation({
    mutationFn: () => api<KbDataset>(`/api/kb/datasets/${dataset.id}`, { method: "PATCH", body: JSON.stringify(form) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["kb-datasets", dataset.workspace_id] }),
  });
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  return (
    <div className="kb-settings">
      <section className="kb-set-group">
        <div className="kb-set-group-title">{t("kbSetBasic")}</div>
        <label className="wf-field">
          <span>{t("kbDatasetName")}</span>
          <Input value={form.name} onChange={(event) => set("name", event.target.value)} />
        </label>
        <label className="wf-field">
          <span>{t("kbDatasetDesc")}</span>
          <Input value={form.description} placeholder={t("kbDatasetDescPh")} onChange={(event) => set("description", event.target.value)} />
        </label>
      </section>

      <section className="kb-set-group">
        <div className="kb-set-group-title">{t("kbSetRetrieval")}</div>
        <div className="kb-settings-row">
          <div className="wf-field">
            <span>{t("kbRetrievalMode")}</span>
            <Select value={form.retrieval_mode} onValueChange={(v) => set("retrieval_mode", v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fts">{t("kbModeFts")}</SelectItem>
                <SelectItem value="hybrid">{t("kbModeHybrid")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <label className="wf-field">
            <span>{t("kbTopK")}</span>
            <Input type="number" min={1} max={50} value={form.top_k} onChange={(event) => set("top_k", Number(event.target.value) || 5)} />
          </label>
        </div>
        {form.retrieval_mode === "hybrid" && <small className="kb-settings-note">{t("kbHybridNote")}</small>}
      </section>

      <section className="kb-set-group">
        <div className="kb-set-group-title">{t("kbSetChunk")}</div>
        <div className="kb-settings-row">
          <label className="wf-field">
            <span>{t("kbChunkSize")}</span>
            <Input type="number" min={100} max={4000} value={form.chunk_size} onChange={(event) => set("chunk_size", Number(event.target.value) || 500)} />
          </label>
          <label className="wf-field">
            <span>{t("kbChunkOverlap")}</span>
            <Input type="number" min={0} max={1000} value={form.chunk_overlap} onChange={(event) => set("chunk_overlap", Number(event.target.value) || 0)} />
          </label>
        </div>
        <small className="kb-settings-note">{t("kbChunkNote")}</small>
      </section>

      <section className="kb-set-group">
        <div className="kb-set-group-title">{t("kbSetEnhance")}</div>
        <label className="kb-switch-row">
          <span>
            <strong>{t("kbGraphEnabled")}</strong>
            <small>{t("kbGraphEnabledDesc")}</small>
          </span>
          <Switch checked={form.graph_enabled} onCheckedChange={(v) => set("graph_enabled", v)} />
        </label>
      </section>

      <div className="kb-settings-actions">
        <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? <Loader2 size={13} className="spin" /> : null} {t("kbSaveSettings")}
        </Button>
        {save.isSuccess && <span className="kb-saved-hint">{t("kbSaved")}</span>}
      </div>
    </div>
  );
}

function CreateDatasetDialog({
  open,
  pending,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (body: { name: string; description: string }) => void;
}) {
  const t = useI18n();
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  React.useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
    }
  }, [open]);
  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onCancel()} title={t("kbNewDataset")}>
      <div className="grid gap-3">
        <label className="wf-field">
          <span>{t("kbDatasetName")}</span>
          <Input autoFocus value={name} placeholder={t("kbDatasetNamePh")} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="wf-field">
          <span>{t("kbDatasetDesc")}</span>
          <Input value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={!name.trim() || pending} onClick={() => onSubmit({ name: name.trim(), description: description.trim() })}>
            {pending ? <Loader2 size={13} className="spin" /> : null} {t("create")}
          </Button>
        </div>
      </div>
    </ModalShell>
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
