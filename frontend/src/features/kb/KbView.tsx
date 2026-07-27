import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  ChevronRight,
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

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n, usePreferences } from "@/app/preferences";
import { relativeTime } from "@/lib/time";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { EmptyState } from "@/components/layout/EmptyState";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ConfirmDialog, ModalShell, RenameDialog } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { KbGraphCanvas } from "@/features/kb/KbGraphCanvas";
import { KbTiptap } from "@/features/kb/KbTiptap";
import { cn } from "@/lib/utils";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";

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
      setDatasetId(ds.id);
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setCreating(false);
    },
  });
  const renameDataset = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api<KbDataset>(`/api/kb/datasets/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
    onSuccess: () => {
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setRenaming(null);
    },
  });
  const removeDataset = useMutation({
    mutationFn: (id: string) => api(`/api/kb/datasets/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      if (datasetId === id) setDatasetId(null);
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setDeleting(null);
    },
  });

  const listed = datasets.data ?? [];
  const selected = listed.find((ds) => ds.id === datasetId) ?? listed[0] ?? null;

  if (datasets.isSuccess && listed.length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
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
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
      <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)] gap-2 max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]">
        <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] flex flex-col gap-1.5 max-[880px]:flex-row max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:px-1.5 max-[880px]:py-[5px] max-[880px]:[&>div:first-child]:contents">
          <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
            <h2>{t("kbTitle")}</h2>
            <Button variant="outline" size="icon" className="h-7 w-7" title={t("kbNewDataset")} aria-label={t("kbNewDataset")} onClick={() => setCreating(true)}>
              <Plus size={14} />
            </Button>
          </div>
          <div className="min-h-0 flex-1 grid content-start gap-1 overflow-y-auto p-1.5 [&:has(>.empty-inline:only-child)]:content-stretch max-[880px]:order-2 max-[880px]:flex max-[880px]:min-w-0 max-[880px]:flex-1 max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:overflow-x-auto max-[880px]:p-0">
            {listed.map((ds) => (
              <ContextMenu key={ds.id}>
                <ContextMenuTrigger asChild>
                  <button
                    type="button"
                    className={cn("flex cursor-pointer items-center gap-[9px] rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted max-[880px]:shrink-0 max-[880px]:py-1", selected?.id === ds.id && "bg-accent hover:bg-accent")}
                    onClick={() => setDatasetId(ds.id)}
                  >
                    <span className="grid h-[26px] w-[26px] shrink-0 place-items-center rounded-md border border-border bg-background text-muted-foreground">
                      <BookOpen size={14} />
                    </span>
                    <span className="min-w-0 [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-[12.5px] [&_strong]:font-semibold max-[880px]:[&_small]:hidden">
                      <strong>{ds.name}</strong>
                      <small>{t("kbDocCount").replace("{n}", String(ds.document_count))}</small>
                    </span>
                  </button>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem onSelect={() => setRenaming(ds)}>{t("rename")}</ContextMenuItem>
                  <ContextMenuSeparator />
                  <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setDeleting(ds)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
          </div>
        </aside>
        <div className="grid min-w-0 overflow-y-auto min-h-0">
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
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="[&_h2]:text-[15px] [&_h2]:font-[650] [&_p]:mt-px [&_p]:truncate [&_p]:text-xs [&_p]:text-muted-foreground">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-accent text-primary">
            <BookOpen size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <h2>{dataset.name}</h2>
            {dataset.description && <p>{dataset.description}</p>}
          </div>
          <Badge variant="secondary">{t("kbDocCount").replace("{n}", String(dataset.document_count))}</Badge>
        </div>
      </div>
      {/* Radix Tabs Root 默认 display:block:必须自己上 flex 列,TabsContent 的
          flex-1 才有意义 — 否则文档编辑器拿不到高度,塌成一小条。 */}
      <Tabs defaultValue="docs" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="self-start">
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
        {/* min-h-0 flex-1:文档编辑器要吃满剩余高度(内部滚动),不能让内容把页面撑开。 */}
        <TabsContent value="docs" className="min-h-0 flex-1">
          <DocumentsTab dataset={dataset} workspace={workspace} />
        </TabsContent>
        <TabsContent value="recall" className="min-h-0 flex-1">
          <RecallTestTab dataset={dataset} />
        </TabsContent>
        <TabsContent value="graph" className="min-h-0 flex-1">
          <GraphTab dataset={dataset} />
        </TabsContent>
        <TabsContent value="settings" className="min-h-0 flex-1">
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
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [openDocId, setOpenDocId] = React.useState<string | null>(null);

  // Cmd+K → KB result → open that document. The palette has dispatched this event all along
  // and nothing listened, so picking a search result navigated to the KB page and showed
  // whatever dataset happened to be selected — the chosen document never opened. The other four
  // mibu:open-* events all have listeners; this one was simply missed.
  React.useEffect(() => {
    const onOpenDoc = (event: Event) => setOpenDocId((event as CustomEvent<string>).detail);
    window.addEventListener("mibu:open-kb-doc", onOpenDoc);
    return () => window.removeEventListener("mibu:open-kb-doc", onOpenDoc);
  }, []);
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
  const [deletingDoc, setDeletingDoc] = React.useState<KbDocument | null>(null);
  const removeDoc = useMutation({
    mutationFn: (id: string) => api(`/api/kb/documents/${id}`, { method: "DELETE" }),
    onSuccess: (_d, id) => {
      if (openDocId === id) setOpenDocId(null);
      setDeletingDoc(null);
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
    <div className="flex h-full min-h-0 flex-col gap-2.5 overflow-y-auto">
      <div className="flex flex-wrap gap-1.5">
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
              className="hidden"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                if (file) importFile.mutate(file);
                event.currentTarget.value = "";
              }}
            />
            {importFile.isPending ? <Loader2 size={13} className="animate-mibu-spin" /> : <FileUp size={13} />} {t("kbImportFile")}
          </label>
        </Button>
      </div>
      {importFile.isError && <p className="text-xs text-destructive">{errText(importFile.error)}</p>}

      {documents.isLoading && docs.length === 0 ? (
        <div className="flex flex-col gap-1" aria-hidden>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-2.5 rounded-md border border-border bg-card py-1 pl-2.5 pr-1.5">
              <Skeleton className="h-4 flex-1 rounded" />
              <Skeleton className="h-4 w-12 rounded-full" />
            </div>
          ))}
        </div>
      ) : docs.length === 0 ? (
        <EmptyState icon={<FileText size={20} />} title={t("kbNoDocsTitle")} body={t("kbNoDocsBody")} />
      ) : (
        <div className="flex flex-col gap-1">
          {docs.map((doc) => (
            <div key={doc.id} className="flex items-center gap-1.5 rounded-md border border-border bg-card py-1 pl-2.5 pr-1.5 transition-[border-color] duration-100 hover:border-border-strong">
              <button type="button" className="flex min-w-0 flex-1 cursor-pointer items-center justify-between gap-2.5 border-0 bg-transparent px-0 py-1 text-left" onClick={() => setOpenDocId(doc.id)}>
                <span className="truncate text-[13px] font-semibold">{doc.title}</span>
                <span className="flex shrink-0 items-center gap-2 text-muted-foreground">
                  <Badge
                    variant={STATUS_VARIANT[doc.status] ?? "default"}
                    className={doc.status === "error" ? "border-destructive text-destructive" : undefined}
                  >
                    {t(`kbStatus_${doc.status}` as never)}
                  </Badge>
                  <span className="timecode text-[11px]">{t("kbChunksN").replace("{n}", String(doc.chunk_count))}</span>
                  <span className="timecode text-[11px]">{relativeTime(doc.updated_at, locale)}</span>
                  {doc.status === "error" && doc.error && <span className="max-w-[220px] truncate text-[11px] text-destructive">{doc.error}</span>}
                </span>
              </button>
              <div className="flex shrink-0 gap-0.5">
                {doc.status === "error" && (
                  <Button size="icon" variant="ghost" className="h-7 w-7" title={t("kbReindex")} onClick={() => reindexDoc.mutate(doc.id)}>
                    <RotateCw size={13} />
                  </Button>
                )}
                <Button size="icon" variant="ghost" className="h-7 w-7 hover:text-destructive" title={t("delete")} onClick={() => setDeletingDoc(doc)}>
                  <Trash2 size={13} />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 删除是不可逆的整篇内容销毁,必须确认 — 此前点垃圾桶直接删。 */}
      <ConfirmDialog
        open={deletingDoc !== null}
        title={t("kbDeleteDocTitle")}
        body={t("kbDeleteDocBody").replace("{title}", deletingDoc?.title ?? "")}
        onCancel={() => setDeletingDoc(null)}
        onConfirm={() => deletingDoc && removeDoc.mutate(deletingDoc.id)}
      />

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
  const [chunksOpen, setChunksOpen] = React.useState(false);

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

  const doSave = () => {
    if (dirty && !save.isPending) save.mutate({ title: title.trim() || doc.data!.title, content });
  };

  return (
    // 编辑器占满剩余高度(内部滚动),分块收成可折叠条 — 此前编辑区随内容塌缩成
    // 一小条,页面下方大片留白,长文还得整页滚。
    <div className="flex h-full min-h-0 flex-col gap-2" onKeyDown={(event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        doSave();
      }
    }}>
      <div className="flex shrink-0 items-center justify-between gap-2">
        <Button size="sm" variant="ghost" onClick={onBack}>
          ← {t("back")}
        </Button>
        {/* 保存钮常驻(干净时禁用),状态文字在旁边 — 不再让整块头部在两种形态间跳动。 */}
        <span className="flex items-center gap-2">
          <span className={cn("text-[11.5px]", dirty ? "text-[#f59e0b]" : "text-muted-foreground")}>
            {dirty ? t("kbUnsavedHint") : t("kbSaved")}
          </span>
          <Button size="sm" disabled={!dirty || save.isPending} title={t("kbSaveShortcut")} onClick={doSave}>
            {save.isPending ? <Loader2 size={13} className="animate-mibu-spin" /> : null} {t("kbSave")}
          </Button>
        </span>
      </div>
      <Input
        className="h-auto shrink-0 rounded-none border-0 bg-transparent p-0 text-lg font-[650] text-foreground shadow-none outline-none focus-visible:ring-0"
        value={title}
        placeholder={t("kbUntitled")}
        aria-label={t("kbUntitled")}
        onChange={(event) => {
          setTitle(event.target.value);
          setDirty(true);
        }}
      />
      <div className="min-h-0 flex-1">
        <KbTiptap
          key={doc.data.id}
          initialMarkdown={doc.data.content ?? ""}
          onChange={(markdown) => {
            setContent(markdown);
            setDirty(true);
          }}
        />
      </div>
      <div className="shrink-0 overflow-hidden rounded-lg border border-border bg-panel">
        <button
          type="button"
          className="flex w-full cursor-pointer items-center gap-1.5 border-0 bg-transparent px-2.5 py-2 text-left text-xs font-semibold text-muted-foreground transition-colors duration-100 hover:text-foreground"
          aria-expanded={chunksOpen}
          onClick={() => setChunksOpen((value) => !value)}
        >
          <ChevronRight size={13} className={cn("transition-transform duration-150", chunksOpen && "rotate-90")} />
          {t("kbChunksTitle").replace("{n}", String((chunks.data ?? []).length))}
          <span className="timecode ml-auto text-[10.5px] font-normal">
            {(chunks.data ?? []).reduce((sum, chunk) => sum + chunk.char_count, 0)}
          </span>
        </button>
        {chunksOpen && (
          <div className="grid max-h-[240px] gap-1.5 overflow-y-auto border-t border-border p-1.5">
            {(chunks.data ?? []).map((chunk) => (
              <div key={chunk.id} className="grid grid-cols-[32px_1fr_auto] gap-2 rounded-md border border-border bg-panel-inset px-2.5 py-2 [&_p]:m-0 [&_p]:whitespace-pre-wrap [&_p]:text-[12.5px] [&_p]:leading-[1.6] [&_p]:[word-break:break-word]">
                <span className="timecode text-[11px] text-muted-foreground">#{chunk.chunk_index + 1}</span>
                <p>{chunk.text}</p>
                <span className="timecode text-[10.5px] text-muted-foreground">{chunk.char_count}</span>
              </div>
            ))}
          </div>
        )}
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
    <div className="flex h-full min-h-0 flex-col gap-2.5 overflow-y-auto">
      <form
        className="flex gap-1.5 [&>:first-child]:flex-1"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim()) run.mutate(query.trim());
        }}
      >
        <Input value={query} placeholder={t("kbRecallPlaceholder")} onChange={(event) => setQuery(event.target.value)} />
        <Button type="submit" size="sm" disabled={!query.trim() || run.isPending}>
          {run.isPending ? <Loader2 size={13} className="animate-mibu-spin" /> : <Search size={13} />} {t("kbRecallRun")}
        </Button>
      </form>
      <p className="text-[11.5px] text-muted-foreground">{t("kbRecallHint")}</p>
      {run.isSuccess && (run.data ?? []).length === 0 && (
        <div className="empty-inline m-auto grid max-w-60 place-items-center px-3 py-5 text-center text-[13px] leading-[1.6] text-muted-foreground">
          <Search size={14} /> {t("kbNoResults")}
        </div>
      )}
      <div className="flex flex-col gap-2">
        {(run.data ?? []).map((hit, i) => (
          <div key={`${hit.document_id}-${hit.chunk_index}-${i}`} className="rounded-md border border-border bg-card px-2.5 py-2 [&_p]:text-xs [&_p]:leading-[1.55] [&_p]:text-muted-foreground">
            <div className="mb-1 flex items-center gap-2 [&_strong]:truncate [&_strong]:text-[12.5px]">
              <strong>{hit.title}</strong>
              <span className="timecode ml-auto text-[11px] text-primary">{hit.score.toFixed(4)}</span>
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
  if (graph.isLoading) return <div className="grid h-full place-items-center text-muted-foreground"><Loader2 size={16} className="animate-mibu-spin" /></div>;
  if (!graph.data?.enabled) {
    return (
      <div className="grid h-full place-items-center">
        <EmptyState icon={<Sparkles size={20} />} title={t("kbGraphOffTitle")} body={t("kbGraphOffBody")} />
      </div>
    );
  }
  if ((graph.data.nodes ?? []).length === 0) {
    return (
      <div className="grid h-full place-items-center">
        <EmptyState icon={<Sparkles size={20} />} title={t("kbGraphEmptyTitle")} body={t("kbGraphEmptyBody")} />
      </div>
    );
  }
  const entityCount = (graph.data.nodes ?? []).filter((n) => n.kind === "entity").length;
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex items-center gap-3.5 text-[11.5px] text-muted-foreground">
        <span className="inline-flex items-center gap-[5px] [&_i]:h-[9px] [&_i]:w-[9px] [&_i]:rounded-full [&_i]:bg-primary">
          <i /> {t("kbGraphDoc")}
        </span>
        <span className="inline-flex items-center gap-[5px] [&_i]:h-[9px] [&_i]:w-[9px] [&_i]:rounded-full [&_i]:bg-[#d97706]">
          <i /> {t("kbGraphEntity")}
        </span>
        <span className="ml-auto">{t("kbGraphEntities").replace("{n}", String(entityCount))}</span>
      </div>
      <KbGraphCanvas nodes={graph.data.nodes ?? []} edges={graph.data.edges ?? []} />
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
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kb-datasets", dataset.workspace_id] });
      // The graph toggle lives in these settings, and nothing anywhere invalidated its query —
      // so turning it on then opening the tab kept serving the cached "off" response.
      void qc.invalidateQueries({ queryKey: ["kb-graph", dataset.id] });
    },
  });
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  return (
    <div className="grid h-full min-h-0 content-start gap-5 overflow-y-auto px-0.5 pb-2.5 pt-1">
      <SettingsGroup title={t("kbSetBasic")}>
        <SettingsRow label={t("kbDatasetName")}>
          <Input className="w-60" value={form.name} onChange={(event) => set("name", event.target.value)} />
        </SettingsRow>
        <SettingsRow label={t("kbDatasetDesc")}>
          <Input
            className="w-80 max-[880px]:w-60"
            value={form.description}
            placeholder={t("kbDatasetDescPh")}
            onChange={(event) => set("description", event.target.value)}
          />
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title={t("kbSetRetrieval")}>
        <SettingsRow label={t("kbRetrievalMode")} description={form.retrieval_mode === "hybrid" ? t("kbHybridNote") : undefined}>
          <Select value={form.retrieval_mode} onValueChange={(v) => set("retrieval_mode", v)}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="fts">{t("kbModeFts")}</SelectItem>
              <SelectItem value="hybrid">{t("kbModeHybrid")}</SelectItem>
            </SelectContent>
          </Select>
        </SettingsRow>
        <SettingsRow label={t("kbTopK")}>
          <Input
            className="w-24"
            type="number"
            min={1}
            max={50}
            value={form.top_k}
            onChange={(event) => set("top_k", Number(event.target.value) || 5)}
          />
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title={t("kbSetChunk")} description={t("kbChunkNote")}>
        <SettingsRow label={t("kbChunkSize")}>
          <Input
            className="w-24"
            type="number"
            min={100}
            max={4000}
            value={form.chunk_size}
            onChange={(event) => set("chunk_size", Number(event.target.value) || 500)}
          />
        </SettingsRow>
        <SettingsRow label={t("kbChunkOverlap")}>
          <Input
            className="w-24"
            type="number"
            min={0}
            max={1000}
            value={form.chunk_overlap}
            onChange={(event) => set("chunk_overlap", Number(event.target.value) || 0)}
          />
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title={t("kbSetEnhance")}>
        <SettingsRow label={t("kbGraphEnabled")} description={t("kbGraphEnabledDesc")}>
          <Switch checked={form.graph_enabled} onCheckedChange={(v) => set("graph_enabled", v)} />
        </SettingsRow>
      </SettingsGroup>

      <div className="flex items-center gap-2.5">
        <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? <Loader2 size={13} className="animate-mibu-spin" /> : null} {t("kbSaveSettings")}
        </Button>
        {save.isSuccess && !save.isPending && <span className="text-[11.5px] text-success">{t("kbSaved")}</span>}
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
  const form = useForm<{ name: string; description: string }>({
    resolver: zodResolver(z.object({ name: z.string().trim().min(1, t("fieldRequired")), description: z.string() })),
    defaultValues: { name: "", description: "" },
  });
  React.useEffect(() => {
    if (open) form.reset({ name: "", description: "" });
  }, [open]);
  const submit = form.handleSubmit((values) =>
    onSubmit({ name: values.name.trim(), description: values.description.trim() }),
  );
  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onCancel()} title={t("kbNewDataset")}>
      <Form {...form}>
        <form className="grid gap-3" onSubmit={submit} noValidate>
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t("kbDatasetName")}</FormLabel>
                <FormControl>
                  <Input autoFocus placeholder={t("kbDatasetNamePh")} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="description"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t("kbDatasetDesc")}</FormLabel>
                <FormControl>
                  <Input {...field} />
                </FormControl>
              </FormItem>
            )}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
              {t("cancel")}
            </Button>
            <Button type="submit" size="sm" disabled={pending}>
              {pending ? <Loader2 size={13} className="animate-mibu-spin" /> : null} {t("create")}
            </Button>
          </div>
        </form>
      </Form>
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
  const form = useForm<{ url: string }>({
    resolver: zodResolver(z.object({ url: z.string().trim().regex(/^https?:\/\//, t("kbUrlInvalid")) })),
    defaultValues: { url: "" },
  });
  React.useEffect(() => {
    if (open) form.reset({ url: "" });
  }, [open]);
  const submit = form.handleSubmit((values) => onSubmit(values.url.trim()));
  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onCancel()} title={t("kbImportUrl")}>
      <Form {...form}>
        <form className="grid gap-3" onSubmit={submit} noValidate>
          <p className="text-[13px] text-muted-foreground">{t("kbImportUrlBody")}</p>
          <FormField
            control={form.control}
            name="url"
            render={({ field }) => (
              <FormItem>
                <FormControl>
                  <Input autoFocus placeholder="https://…" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
              {t("cancel")}
            </Button>
            <Button type="submit" size="sm" disabled={pending}>
              {pending ? <Loader2 size={13} className="animate-mibu-spin" /> : null} {t("kbImport")}
            </Button>
          </div>
        </form>
      </Form>
    </ModalShell>
  );
}
