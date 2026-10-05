import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  CircleAlert,
  Copy,
  Download,
  FileUp,
  FolderTree,
  Info,
  LayoutGrid,
  LayoutPanelLeft,
  MoreHorizontal,
  PencilLine,
  Plus,
  RefreshCcw,
  RotateCcw,
  Search,
  SearchX,
  Settings2,
  Sparkles,
  SquarePen,
  Trash2,
  TriangleAlert,
  Unplug,
  Upload,
  Workflow,
  X,
} from "lucide-react";

import {
  assetThumbnailUrl,
  copyWorkflow,
  getWorkflowContent,
  getWorkflowLibrary,
  rebootWorkflowServer,
  refreshPluginInstance,
  renameWorkflow,
  restoreWorkflow,
  startNodeInstall,
  trashWorkflow,
  type Job,
  type PluginInstance,
  type WorkflowFile,
  type WorkflowNodePack,
  type WorkflowTrashed,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n, usePreferences } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import {
  LIBRARY_DENSITIES,
  LibraryDensitySwitch,
  LibraryDetail,
  LibraryDialog,
  LibraryFilterChips,
  LibrarySection,
  type LibraryChip,
  type LibraryDensity,
  type LibraryNavItem,
} from "@/components/app/LibraryBrowser";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { MenuContent, MenuItem, MenuSeparator } from "@/components/ui/menu";
import { OptionPicker } from "@/components/ui/option-picker";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import type { Focused, ModelFocus, WorkflowFocus } from "@/features/plugins/libraryLinks";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { WorkflowAppEditor, WorkflowAppSection } from "@/features/plugins/WorkflowAppEditor";
import { WorkflowFacts, kindName } from "@/features/plugins/WorkflowFacts";
import { WorkflowGraphView } from "@/features/plugins/WorkflowGraph";
import { WorkflowImportDialog, importable } from "@/features/plugins/WorkflowImport";
import {
  NodeInstallNote,
  awaitingRestart,
  installActive,
  packsOf,
  useNodeInstalls,
} from "@/features/plugins/WorkflowNodeInstall";
import { WorkflowPathField, useWorkflowPath } from "@/features/plugins/WorkflowPathField";
import {
  NEW_NOTE_PATH,
  embeddedCreate,
  embeddedEditor,
  embeddedWorkbench,
  useWorkflowEditor,
  type EditorNote,
  type WorkflowEditor,
} from "@/features/plugins/workflowEditor";
import {
  ALL_WORKFLOWS,
  PROBLEMS_VIEW,
  TRASH_VIEW,
  WORKFLOW_KINDS,
  WORKFLOW_SORTS,
  filterWorkflows,
  freeWorkflowPath,
  inView,
  lacksSomething,
  sortWorkflows,
  workflowFolders,
  type WorkflowKindFilter,
  type WorkflowSort,
} from "@/features/plugins/workflowLibraryView";
import { gotoRecord } from "@/lib/deepLink";
import { saveJsonToDisk } from "@/lib/download";
import { handOffToGeneration } from "@/lib/generationHandoff";
import { useFileDrop } from "@/lib/useFileDrop";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

/**
 * 工作流库(ADR 0035):一个连接**那台服务器上存着的工作流**。任何认领了 `workflow_library` 的插件连接都走这里,不认识哪一家。
 *
 * 和模型库同一套骨架(LibraryBrowser):左边一列子目录(按数量排),「缺节点或模型」钉在这一列底部;右边顶上搜索、按种类筛、
 * 排序、三档显示方式;一张卡是节点图的缩略预览(照插件给的图摘要画)、名字、种类、节点数、缺什么。点开是详情:能填什么 /
 * 能调什么 / 交出什么、用到的模型、缺的节点和模型、最近的产出、Mosael 里谁在用它;「用它生成」交给 AI 工作台;「在编辑器里
 * 打开」开那台服务器自己的编辑器(见 workflowEditor),回来时刷新。和模型库互相跳(见 ConnectionLibraries):用到的模型
 * 点了停到模型库那一项,缺的点了去模型库下载;从模型库跳过来停到那一张。
 *
 * 工具条上的「新建」在 ComfyUI 自己的画布上开一张新的(内嵌视图里执行它的「新建」命令,见 workflowEditor;存盘是 ComfyUI
 * 自己的,回来时刷新,新存的那张就出现在列表里);「导入」(或者往库上拖一个文件)导入别处的工作流,见 WorkflowImport。
 *
 * 列表每次打开现问插件(不存库)。
 */

const keyOf = (flow: WorkflowFile) => flow.path;

export function WorkflowLibraryDialog({
  open,
  onOpenChange,
  instance,
  workspaceId,
  focus,
  onShowModel,
  onCheckSettings,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: PluginInstance;
  workspaceId: string;
  /** 从模型库跳过来:停到这一张。 */
  focus?: Focused<WorkflowFocus> | null;
  /** 用到的模型点了跳到模型库(在的停到那一项,缺的打开下载框):连接也认领了模型库才给。 */
  onShowModel?: (focus: ModelFocus) => void;
  onCheckSettings?: () => void;
}) {
  const t = useI18n();
  const library = useQuery({
    queryKey: ["workflow-library", instance.id, workspaceId],
    queryFn: () => getWorkflowLibrary(instance.id, workspaceId),
    enabled: open,
    staleTime: 30_000,
  });
  const [view, setView] = React.useState(ALL_WORKFLOWS);
  const [query, setQuery] = React.useState("");
  const [kind, setKind] = React.useState<WorkflowKindFilter>("all");
  const [sort, setSort] = React.useState<WorkflowSort>("name");
  //: 显示方式记在本机,和模型库各记各的
  const [density, setDensity] = usePersistentTab<LibraryDensity>("workflow-library.density", "small", LIBRARY_DENSITIES);
  const [detailKey, setDetailKey] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (focus) setDetailKey(focus.path);
  }, [focus]);
  //: 正在确认的那一次改动(复制、改名、恢复要一个名字;删除只要一句确认)
  const [action, setAction] = React.useState<
    | { kind: "copy" | "rename"; path: string; initial: string }
    | { kind: "restore"; path: string; initial: string }
    | { kind: "delete"; flow: WorkflowFile }
    | null
  >(null);
  const [deleting, setDeleting] = React.useState(false);
  //: 正在编辑哪一张的应用表单(ADR 0038):详情里「编辑应用表单」打开
  const [editingApp, setEditingApp] = React.useState<WorkflowFile | null>(null);
  //: 正在导入(往库上拖进来的那个文件一并带上)
  const [importing, setImporting] = React.useState<{ file?: File } | null>(null);
  //: 装节点包:这次打开之后发起的任务、正在确认装哪个、正在确认重启
  const [installStarted, setInstallStarted] = React.useState<Job[]>([]);
  const installs = useNodeInstalls(library.data, installStarted);
  const [installAsk, setInstallAsk] = React.useState<WorkflowNodePack | null>(null);
  const [installPending, setInstallPending] = React.useState(false);
  const [restartAsk, setRestartAsk] = React.useState(false);
  const [restartedAt, setRestartedAt] = React.useState(0);
  //: 摆出来的:这次打开之后发起的(什么状态都摆),和别处发起、还在跑的
  const sessionInstalls = installs.filter(
    (job) => installActive(job) || installStarted.some((one) => one.id === job.id),
  );
  const restart = useMutation({
    mutationFn: () => rebootWorkflowServer(instance.id),
    //: 宿主已经让这个连接的目录重拉过:新装的节点包这时才加载,工作流库、模型库、生成选项重新问
    onSuccess: () => {
      setRestartedAt(Date.now());
      void qc.invalidateQueries({ queryKey: ["workflow-library", instance.id] });
      void qc.invalidateQueries({ queryKey: ["model-library", instance.id] });
      invalidatePluginDependents(qc);
    },
  });
  const qc = useQueryClient();
  //: 改完一张:工作流库重新问一遍;生成选项、工具清单里的那张也跟着变(宿主已经让这个连接的目录重拉过)
  const changed = () => {
    void qc.invalidateQueries({ queryKey: ["workflow-library", instance.id] });
    invalidatePluginDependents(qc);
  };
  //: 从编辑器回来:那边可能存了改动、换了模型 —— 先让这个连接的目录重拉,再让工作流库、模型库和生成选项重新问
  const editorReturned = React.useCallback(() => {
    void refreshPluginInstance(instance.id)
      .catch(() => undefined)
      .finally(() => {
        void qc.invalidateQueries({ queryKey: ["workflow-library", instance.id] });
        void qc.invalidateQueries({ queryKey: ["model-library", instance.id] });
        invalidatePluginDependents(qc);
      });
  }, [instance.id, qc]);
  const editor = useWorkflowEditor(instance, editorReturned, workspaceId);

  const workflows = React.useMemo(() => library.data?.workflows ?? [], [library.data]);
  const trash = library.data?.trash ?? [];
  const taken = React.useMemo(() => new Set(workflows.map(keyOf)), [workflows]);
  const folders = React.useMemo(() => workflowFolders(workflows), [workflows]);
  const problems = workflows.filter(lacksSomething).length;
  const navItems: LibraryNavItem[] = [
    { value: ALL_WORKFLOWS, label: t("workflowLibraryAll"), count: workflows.length, icon: <LayoutGrid /> },
    ...folders.map((one) => ({ value: one.name, label: one.name, count: one.count, icon: <FolderTree /> })),
  ];
  const pinned: LibraryNavItem[] = [
    ...(problems > 0
      ? [{ value: PROBLEMS_VIEW, label: t("workflowLibraryProblems"), count: problems, icon: <TriangleAlert />, tone: "warning" as const }]
      : []),
    ...(trash.length > 0 ? [{ value: TRASH_VIEW, label: t("workflowLibraryTrash"), count: trash.length, icon: <Trash2 /> }] : []),
  ];
  const current = [...navItems, ...pinned].some((one) => one.value === view) ? view : ALL_WORKFLOWS;
  const scope = inView(workflows, current);
  const shown = sortWorkflows(filterWorkflows(scope, { kind, query }), sort);
  const detail = detailKey ? workflows.find((flow) => keyOf(flow) === detailKey) ?? null : null;

  const clearFilters = () => {
    setQuery("");
    setKind("all");
  };
  const chips: LibraryChip[] = [
    ...(query.trim()
      ? [{ key: "query", label: t("modelLibraryChipSearch").replace("{query}", query.trim()),
           removeLabel: t("modelLibraryChipRemoveSearch").replace("{query}", query.trim()), onRemove: () => setQuery("") }]
      : []),
    ...(kind !== "all"
      ? [{ key: "kind", label: kind === "broken" ? t("workflowLibraryKindBroken") : kindName(t, kind),
           removeLabel: t("workflowLibraryChipRemoveKind"), onRemove: () => setKind("all") }]
      : []),
  ];

  const importButton = (
    <Hint label={t("workflowImportDesc")}>
      <Button variant="outline" onClick={() => setImporting({})}>
        <Upload size={13} />
        {t("workflowImport")}
      </Button>
    </Hint>
  );
  //: 「新建」:在这台 ComfyUI 自己的画布上开一张新的(插件报了编辑器才有)
  const editorTarget = library.data?.editor ?? null;
  const newButton = editorTarget ? (
    <Hint label={t(embeddedWorkbench(editorTarget) ? "workflowNewInWorkbenchHint"
      : embeddedCreate(editorTarget) ? "workflowNewHint" : "workflowNewHintTab")}>
      <Button disabled={editor.opening} onClick={() => void editor.create(editorTarget)}>
        <Plus size={13} />
        {t("workflowNew")}
      </Button>
    </Hint>
  ) : null;
  const newNote = editor.note?.path === NEW_NOTE_PATH ? <EditorNoteLine note={editor.note} onDismiss={editor.dismiss} /> : null;
  //: 往库上拖一个工作流文件:直接打开导入、认它(回收站那一页也一样 —— 拖进来的总是要导入的)
  const drop = useFileDrop((files) => setImporting({ file: files[0] }), importable);

  const refresh = (
    <IconButton
      variant="outline"
      size="default"
      className="px-3 text-muted-foreground"
      label={t("workflowLibraryRefresh")}
      loading={library.isFetching}
      onClick={() => void library.refetch()}
    >
      <RefreshCcw size={13} />
    </IconButton>
  );

  const toolbar = current === TRASH_VIEW ? (
    <>
      <div className="grid min-w-0 flex-1 basis-[240px] gap-0.5">
        <h3 className="m-0 text-ui-md font-semibold text-foreground">{t("workflowLibraryTrash")}</h3>
        <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowLibraryTrashDesc")}</p>
      </div>
      {refresh}
    </>
  ) : !library.data ? (
    <label className="relative min-w-[180px] flex-1 basis-[220px]">
      <Search size={14} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
      <Input className="pl-9" disabled placeholder={t("workflowLibrarySearchPending")} aria-label={t("workflowLibrarySearchPending")} />
    </label>
  ) : (
    <>
      <label className="relative min-w-[180px] flex-1 basis-[220px]">
        <Search size={14} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder={t("workflowLibrarySearch").replace("{n}", String(scope.length))}
          aria-label={t("workflowLibrarySearch").replace("{n}", String(scope.length))}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <OptionPicker
        className="w-[132px]"
        ariaLabel={t("workflowLibraryKind")}
        value={kind}
        onChange={(next) => setKind(WORKFLOW_KINDS.includes(next as WorkflowKindFilter) ? (next as WorkflowKindFilter) : "all")}
        options={WORKFLOW_KINDS.map((one) => ({
          value: one,
          label: one === "all" ? t("workflowLibraryKindAll") : one === "broken" ? t("workflowLibraryKindBroken") : kindName(t, one),
        }))}
      />
      <OptionPicker
        className="w-[140px]"
        ariaLabel={t("workflowLibrarySort")}
        value={sort}
        onChange={(next) => setSort(WORKFLOW_SORTS.includes(next as WorkflowSort) ? (next as WorkflowSort) : "name")}
        options={WORKFLOW_SORTS.map((one) => ({
          value: one,
          label: t(one === "name" ? "workflowLibrarySortName" : one === "modified" ? "workflowLibrarySortModified" : "workflowLibrarySortNodes"),
        }))}
      />
      <LibraryDensitySwitch value={density} onChange={setDensity} />
      {newButton}
      {importButton}
      {refresh}
    </>
  );

  const content = (openItem: (key: string) => void) => {
    if (library.isPending) return <LoadingState label={t("workflowLibraryLoading")} className="h-auto flex-1" />;
    if (library.isError) {
      return (
        <PageLoadError
          size="section"
          icon={<Unplug />}
          title={t("workflowLibraryErrorTitle")}
          error={library.error}
          onRetry={() => void library.refetch()}
          retrying={library.isFetching}
          actions={
            onCheckSettings ? (
              <Button variant="outline" onClick={onCheckSettings}>
                <Settings2 size={13} />
                {t("modelLibraryCheckSettings")}
              </Button>
            ) : undefined
          }
        />
      );
    }
    if (current === TRASH_VIEW) {
      return <TrashList items={trash} onRestore={(one) => setAction({ kind: "restore", path: one.path, initial: one.original })} />;
    }
    if (shown.length === 0) {
      return chips.length > 0 ? (
        <EmptyState
          size="section"
          icon={<SearchX />}
          title={t("workflowLibraryNoMatchTitle")}
          body={t("workflowLibraryNoMatchBody")}
          action={<Button variant="secondary" onClick={clearFilters}>{t("workflowLibraryClearFilters")}</Button>}
        />
      ) : (
        <EmptyState size="section" icon={<Workflow />} title={t("workflowLibraryEmpty")} action={newButton ?? undefined} />
      );
    }
    const listLabel = t("workflowLibraryTitle").replace("{name}", instance.name);
    if (density === "list") {
      return <WorkflowTable label={listLabel} workflows={shown} onOpen={(flow) => openItem(keyOf(flow))} />;
    }
    return (
      <ul
        role="list"
        aria-label={listLabel}
        data-density={density}
        className={cn(
          "m-0 grid list-none gap-3 p-0",
          density === "large"
            ? "grid-cols-[repeat(auto-fill,minmax(min(100%,260px),1fr))]"
            : "grid-cols-[repeat(auto-fill,minmax(min(100%,180px),1fr))] gap-2.5",
        )}
      >
        {shown.map((flow) => (
          <li key={keyOf(flow)} className="grid min-w-0">
            <WorkflowCard flow={flow} large={density === "large"} onOpen={() => openItem(keyOf(flow))} />
          </li>
        ))}
      </ul>
    );
  };

  return (
    <LibraryDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("workflowLibraryTitle").replace("{name}", instance.name)}
      nav={library.data ? { label: t("workflowLibraryFolders"), value: current, onChange: setView, items: navItems, pinned } : undefined}
      toolbar={toolbar}
      dropzone={
        library.data
          ? {
              handlers: drop.handlers,
              overlay: drop.active ? (
                <div className="pointer-events-none absolute inset-0 z-20 grid place-items-center rounded-[inherit] bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
                  <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
                    <FileUp size={20} />
                    {t("workflowImportDropOverlay")}
                  </span>
                </div>
              ) : null,
            }
          : undefined
      }
      chips={
        library.data ? (
          <>
            {newNote}
            <LibraryFilterChips
              label={t("modelLibraryActiveFilters")}
              summary={t("workflowLibraryResultCount").replace("{n}", String(shown.length))}
              chips={chips}
              onClearAll={clearFilters}
            />
          </>
        ) : undefined
      }
      detailKey={detail ? detailKey : null}
      onOpenItem={setDetailKey}
      onBack={() => setDetailKey(null)}
      detail={
        detail && (
          <WorkflowDetail
            flow={detail}
            editor={library.data?.editor ?? null}
            opening={editor.opening}
            note={editor.note?.path === detail.path ? editor.note : null}
            onOpenEditor={(where) => void editor.open(where, detail)}
            onOpenWorkbench={(where) => void editor.workbench(where, detail)}
            onShowModel={onShowModel}
            manager={library.data?.manager?.version ?? ""}
            installs={sessionInstalls.filter((job) => packsOf(job).some((id) =>
              (detail.missing_nodes ?? []).some((node) => (node.packs ?? []).some((pack) => pack.id === id))))}
            onInstall={setInstallAsk}
            restartedAt={restartedAt}
            restarting={restart.isPending}
            restartError={restart.error ? errorText(restart.error) : ""}
            onRestart={() => setRestartAsk(true)}
            onDismissNote={editor.dismiss}
            app={<WorkflowAppSection instance={instance} flow={detail} onEdit={() => setEditingApp(detail)} onSaved={changed} />}
            onBack={() => setDetailKey(null)}
            onCopy={() => setAction({ kind: "copy", path: detail.path, initial: freeWorkflowPath(detail.path, taken) })}
            onRename={() => setAction({ kind: "rename", path: detail.path, initial: detail.path })}
            onDelete={() => setAction({ kind: "delete", flow: detail })}
            onExport={async () => {
              const found = await getWorkflowContent(instance.id, detail.path);
              saveJsonToDisk(`${detail.label}.json`, found.content);
            }}
          />
        )
      }
      dialogs={
        <>
          {installAsk && (
            <ConfirmDialog
              open
              title={t("workflowInstallTitle").replace("{server}", instance.name).replace("{name}", installAsk.title)}
              body={t("workflowInstallBody")}
              confirmLabel={t("workflowInstallConfirm")}
              pending={installPending}
              onCancel={() => setInstallAsk(null)}
              onConfirm={async () => {
                setInstallPending(true);
                try {
                  const job = await startNodeInstall(instance.id, { workspace_id: workspaceId, packs: [installAsk.id] });
                  setInstallStarted((list) => [job, ...list]);
                  setInstallAsk(null);
                } finally {
                  setInstallPending(false);
                }
              }}
            />
          )}
          {restartAsk && (
            <ConfirmDialog
              open
              title={t("workflowRestartTitle").replace("{server}", instance.name)}
              body={t("workflowRestartBody")}
              confirmLabel={t("workflowRestartConfirm")}
              pending={false}
              onCancel={() => setRestartAsk(false)}
              onConfirm={() => {
                setRestartAsk(false);
                restart.mutate();
              }}
            />
          )}
          {editingApp && (
            <WorkflowAppEditor
              instance={instance}
              flow={editingApp}
              onClose={() => setEditingApp(null)}
              onSaved={changed}
            />
          )}
          {importing && (
            <WorkflowImportDialog
              instance={instance}
              taken={taken}
              initialFile={importing.file}
              onClose={() => setImporting(null)}
              onSaved={(path) => {
                changed();
                setDetailKey(path);
              }}
            />
          )}
          {action && action.kind !== "delete" && (
            <WorkflowPathDialog
              title={t(action.kind === "copy" ? "workflowCopyTitle" : action.kind === "rename" ? "workflowRenameTitle" : "workflowRestoreTitle")
                .replace("{name}", action.kind === "restore" ? action.initial : action.path)}
              confirmLabel={t(action.kind === "copy" ? "workflowCopyConfirm" : action.kind === "rename" ? "workflowRenameConfirm"
                : "workflowRestoreConfirm")}
              where={t("workflowWriteWhere").replace("{server}", instance.name)}
              initial={action.initial}
              onClose={() => setAction(null)}
              onSubmit={async (path) => {
                const done =
                  action.kind === "copy" ? await copyWorkflow(instance.id, action.path, path)
                    : action.kind === "rename" ? await renameWorkflow(instance.id, action.path, path)
                      : await restoreWorkflow(instance.id, action.path, path);
                changed();
                if (action.kind !== "restore") setDetailKey(done.path);
              }}
            />
          )}
          {action?.kind === "delete" && (
            <ConfirmDialog
              open
              title={t("workflowDeleteTitle").replace("{name}", action.flow.label)}
              body={[
                t("workflowDeleteBody").replace("{server}", instance.name),
                (action.flow.used_by?.length ?? 0) > 0
                  ? `${t("workflowDeleteUsedBy")}${(action.flow.used_by ?? []).map((one) => one.name).join(t("listSeparator"))}`
                  : "",
              ].filter(Boolean).join(" ")}
              confirmLabel={t("workflowDeleteConfirm")}
              pending={deleting}
              onCancel={() => setAction(null)}
              onConfirm={async () => {
                setDeleting(true);
                try {
                  await trashWorkflow(instance.id, action.flow.path);
                  changed();
                  setAction(null);
                  setDetailKey(null);
                } finally {
                  setDeleting(false);
                }
              }}
            />
          )}
        </>
      }
    >
      {content}
    </LibraryDialog>
  );
}

/** 卡片上那一行「缺什么」:缺几种节点、缺几个模型。都不缺就没有。 */
function LackBadges({ flow }: { flow: WorkflowFile }) {
  const t = useI18n();
  const nodes = flow.missing_nodes?.length ?? 0;
  const models = flow.missing_models?.length ?? 0;
  if (!nodes && !models) return null;
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1">
      {nodes > 0 && (
        <CatalogBadge tone="warning" icon={<CircleAlert />}>{t("workflowLibraryMissingNodes").replace("{n}", String(nodes))}</CatalogBadge>
      )}
      {models > 0 && (
        <CatalogBadge tone="warning" icon={<Boxes />}>{t("workflowLibraryMissingModels").replace("{n}", String(models))}</CatalogBadge>
      )}
    </span>
  );
}

/**
 * 一张卡:节点图缩略预览(4:3,整张图塞进去不裁)、名字(一行截断,悬停看全路径)、种类在左、节点数在右;缺东西的再一行。
 * 大卡片多一行:最近一次的产出、Mosael 里几处在用。**整张可点**:名字那颗按钮用 `after:` 盖满整张卡。
 */
function WorkflowCard({ flow, large, onOpen }: { flow: WorkflowFile; large: boolean; onOpen: () => void }) {
  const t = useI18n();
  const used = flow.used_by?.length ?? 0;
  return (
    <article
      data-library-item={keyOf(flow)}
      className={cn(
        "relative grid min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_1fr] overflow-hidden rounded-xl border border-border bg-panel transition-colors",
        "hover:border-border-strong hover:bg-panel-subtle",
        "has-[[data-library-open]:focus-visible]:border-primary has-[[data-library-open]:focus-visible]:ring-2 has-[[data-library-open]:focus-visible]:ring-ring",
      )}
    >
      <WorkflowGraphView graph={flow.graph} label={t("workflowGraphLabel").replace("{name}", flow.label)} className="aspect-[4/3] w-full" />
      <div className={cn("grid min-w-0 content-start", large ? "gap-1.5 p-2.5" : "gap-1 p-2")}>
        <h3 className={cn("m-0 min-w-0 font-semibold leading-snug text-foreground", large ? "text-ui-sm" : "text-ui-xs")}>
          <button
            type="button"
            data-library-open
            className="block max-w-full cursor-pointer text-left after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none"
            onClick={onOpen}
          >
            <Truncate hint={flow.path !== `${flow.label}.json` ? flow.path : undefined}>{flow.label}</Truncate>
          </button>
        </h3>
        <div className="flex h-6 min-w-0 items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1">
            <CatalogBadge tone={flow.problem ? "warning" : flow.kind ? "primary" : "muted"}>{kindName(t, flow.kind)}</CatalogBadge>
            {flow.app?.status === "ok" && flow.app.app && (
              <CatalogBadge tone={(flow.app.invalid ?? 0) > 0 ? "warning" : "muted"}>{t("workflowAppBadge")}</CatalogBadge>
            )}
          </span>
          <span className="shrink-0 text-ui-xs tabular-nums text-muted-foreground">
            {t("workflowLibraryNodes").replace("{n}", String(flow.node_count))}
          </span>
        </div>
        <LackBadges flow={flow} />
        {large && (flow.last_output || used > 0) && (
          <div className="flex min-w-0 items-center justify-between gap-2 text-ui-xs text-muted-foreground">
            {flow.last_output ? (
              <img
                src={assetThumbnailUrl(flow.last_output.asset_id)}
                alt=""
                loading="lazy"
                className="size-8 shrink-0 rounded-md bg-secondary object-cover"
              />
            ) : (
              <span />
            )}
            {used > 0 && (
              <span className="inline-flex shrink-0 items-center gap-1 text-success">
                <Workflow size={12} aria-hidden />
                {t("workflowLibraryUsedCount").replace("{n}", String(used))}
              </span>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

/** 列表:一行一张,扫一大批工作流时比卡片快。名字是行里那颗按钮;整行也点得开。 */
function WorkflowTable({ label, workflows, onOpen }: { label: string; workflows: WorkflowFile[]; onOpen: (flow: WorkflowFile) => void }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const head = "sticky top-0 z-[1] border-b border-divider bg-[var(--modal-surface)] px-2 pb-2 pt-1 text-left text-ui-xs font-medium text-muted-foreground";
  const cell = "border-b border-divider px-2 py-1.5 align-middle";
  return (
    <table aria-label={label} className="w-full min-w-[720px] table-fixed border-separate border-spacing-0 text-ui-sm">
      <colgroup>
        <col className="w-[76px]" />
        <col />
        <col className="w-[120px]" />
        <col className="w-[80px]" />
        <col className="w-[64px]" />
        <col className="w-[108px]" />
        <col className="w-[120px]" />
        <col className="w-[56px]" />
      </colgroup>
      <thead>
        <tr>
          <th scope="col" className={head}>
            <span className="sr-only">{t("workflowLibraryColPreview")}</span>
          </th>
          <th scope="col" className={head}>{t("workflowLibraryColName")}</th>
          <th scope="col" className={head}>{t("workflowLibraryColFolder")}</th>
          <th scope="col" className={head}>{t("workflowLibraryKind")}</th>
          <th scope="col" className={cn(head, "text-right")}>{t("workflowLibraryColNodes")}</th>
          <th scope="col" className={head}>{t("modelModified")}</th>
          <th scope="col" className={head}>{t("workflowLibraryColMissing")}</th>
          <th scope="col" className={cn(head, "text-right")}>{t("modelLibraryColUsed")}</th>
        </tr>
      </thead>
      <tbody>
        {workflows.map((flow) => {
          const used = flow.used_by?.length ?? 0;
          return (
            <tr
              key={keyOf(flow)}
              data-library-item={keyOf(flow)}
              onClick={() => onOpen(flow)}
              className="cursor-pointer transition-colors hover:bg-panel-subtle has-[[data-library-open]:focus-visible]:bg-panel-subtle"
            >
              <td className={cell}>
                <WorkflowGraphView graph={flow.graph} label={t("workflowGraphLabel").replace("{name}", flow.label)}
                                   className="h-10 w-[60px] rounded-md" />
              </td>
              <td className={cell}>
                <button
                  type="button"
                  data-library-open
                  className="block max-w-full cursor-pointer rounded-sm text-left font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={(event) => {
                    event.stopPropagation();
                    onOpen(flow);
                  }}
                >
                  <Truncate>{flow.label}</Truncate>
                </button>
              </td>
              <td className={cn(cell, "text-ui-xs text-muted-foreground")}>
                <Truncate>{flow.folder}</Truncate>
              </td>
              <td className={cn(cell, "text-ui-xs", flow.problem ? "text-warning" : "text-muted-foreground")}>{kindName(t, flow.kind)}</td>
              <td className={cn(cell, "text-right text-ui-xs tabular-nums text-muted-foreground")}>{flow.node_count}</td>
              <td className={cn(cell, "text-ui-xs tabular-nums text-muted-foreground")}>
                {flow.modified != null ? new Date(flow.modified * 1000).toLocaleDateString(locale) : ""}
              </td>
              <td className={cell}>
                <LackBadges flow={flow} />
              </td>
              <td className={cn(cell, "text-right text-ui-xs tabular-nums", used > 0 ? "text-success" : "text-muted-foreground")}>
                {used > 0 ? used : ""}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** 「在编辑器里打开」/「新建」之后留下的那句话:没打开成那一张、开了新标签页要自己点开、这版前端不能新建、或者出了错。 */
function EditorNoteLine({ note, onDismiss }: { note: EditorNote; onDismiss: () => void }) {
  const t = useI18n();
  const created = note.path === NEW_NOTE_PATH;
  const keys: Record<Exclude<EditorNote["kind"], "error">, Parameters<typeof t>[0]> = {
    missing: "workflowEditorMissing",
    tab: "workflowEditorTab",
    notReady: created ? "workflowNewNotReady" : "workflowEditorNotReady",
    unsupported: "workflowNewUnsupported",
    newTab: "workflowNewTab",
  };
  const text =
    note.kind === "error"
      ? note.message || t(created ? "workflowNewFailed" : "workflowEditorFailed")
      : t(keys[note.kind]).replace("{name}", note.path);
  return (
    <div
      role={note.kind === "error" ? "alert" : "status"}
      className={cn(
        "flex min-w-0 items-start gap-2 rounded-lg border bg-panel p-3 text-ui-sm text-foreground",
        note.kind === "error" ? "border-destructive/40" : "border-border",
      )}
    >
      {note.kind === "error" ? (
        <CircleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-destructive" />
      ) : (
        <Info size={14} aria-hidden className="mt-0.5 shrink-0 text-muted-foreground" />
      )}
      <span className="min-w-0 flex-1 break-words">{text}</span>
      <IconButton size="sm" className="-my-1 shrink-0 text-muted-foreground" label={t("close")} onClick={onDismiss}>
        <X size={13} />
      </IconButton>
    </div>
  );
}

/**
 * 一张工作流的详情(LibraryDetail 的骨架):头上是名字、目录 · 种类 · 节点数 · 改动时间,右边「用它生成」;左栏大一号的节点图
 * (带节点标题和分组名);右栏转不过来的原因、能填什么 / 能调什么 / 交出什么、用到的模型、缺的节点和模型、最近的产出、
 * Mosael 里谁在用它。
 */
function WorkflowDetail({
  flow,
  editor,
  opening,
  note,
  onOpenEditor,
  onOpenWorkbench,
  onShowModel,
  manager,
  installs,
  onInstall,
  restartedAt,
  restarting,
  restartError,
  onRestart,
  onDismissNote,
  app,
  onBack,
  onCopy,
  onRename,
  onDelete,
  onExport,
}: {
  flow: WorkflowFile;
  editor: WorkflowEditor | null;
  opening: boolean;
  note: EditorNote | null;
  onOpenEditor: (editor: WorkflowEditor) => void;
  /** 在工作台里打开(ADR 0038):桌面版、编辑器是 ComfyUI 时才有 */
  onOpenWorkbench: (editor: WorkflowEditor) => void;
  onShowModel?: (focus: ModelFocus) => void;
  manager: string;
  installs: Job[];
  onInstall: (pack: WorkflowNodePack) => void;
  restartedAt: number;
  restarting: boolean;
  restartError: string;
  onRestart: () => void;
  onDismissNote: () => void;
  /** 「应用」那一节(应用表单,ADR 0038),见 WorkflowAppSection */
  app: React.ReactNode;
  onBack: () => void;
  onCopy: () => void;
  onRename: () => void;
  onDelete: () => void;
  onExport: () => Promise<void>;
}) {
  const t = useI18n();
  const [menu, setMenu] = React.useState(false);
  const [exportError, setExportError] = React.useState("");
  const { locale } = usePreferences();
  const generation = flow.generation;

  const media = (
    <div className="grid gap-2">
      <WorkflowGraphView
        graph={flow.graph}
        detailed
        label={t("workflowGraphLabel").replace("{name}", flow.label)}
        className="aspect-[4/3] w-full rounded-xl"
      />
      {flow.graph?.auto_layout && <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowGraphAuto")}</p>}
      {flow.graph?.truncated && <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowGraphTruncated")}</p>}
    </div>
  );

  return (
    <LibraryDetail
      backLabel={t("workflowLibraryBack")}
      onBack={onBack}
      title={flow.label}
      meta={
        <>
          {flow.folder && <span>{flow.folder}</span>}
          {flow.folder && <span aria-hidden>·</span>}
          <CatalogBadge tone={flow.problem ? "warning" : flow.kind ? "primary" : "muted"}>{kindName(t, flow.kind)}</CatalogBadge>
          <span className="tabular-nums">{t("workflowLibraryNodes").replace("{n}", String(flow.node_count))}</span>
          {flow.modified != null && <span aria-hidden>·</span>}
          {flow.modified != null && <span className="tabular-nums">{new Date(flow.modified * 1000).toLocaleString(locale)}</span>}
        </>
      }
      actions={
        <>
        <Hint label={t("workflowUseToGenerateHint")} disabledReason={generation ? undefined : t("workflowNotGeneration")}>
          <Button
            disabled={!generation}
            onClick={() =>
              generation &&
              handOffToGeneration({
                providerProfileId: generation.provider_profile_id,
                kind: generation.kind,
                model: generation.model,
                declared: {},
                promptWords: [],
              })
            }
          >
            <Sparkles size={13} />
            {t("modelUseToGenerate")}
          </Button>
        </Hint>
        {editor && embeddedWorkbench(editor) && (
          <Hint label={t("workflowOpenInWorkbenchHint")}>
            <Button variant="outline" disabled={opening} onClick={() => onOpenWorkbench(editor)}>
              <LayoutPanelLeft size={13} />
              {t("workflowOpenInWorkbench")}
            </Button>
          </Hint>
        )}
        {editor && (
          <Hint label={t(embeddedEditor(editor) ? "workflowOpenInEditorHint" : "workflowOpenInEditorHintTab")}>
            <Button variant="outline" disabled={opening} onClick={() => onOpenEditor(editor)}>
              <SquarePen size={13} />
              {t("workflowOpenInEditor")}
            </Button>
          </Hint>
        )}
        {/* 改那台机器上的文件:每一样都先弹确认(见 WorkflowPathDialog / ConfirmDialog);导出只是下载到本机 */}
        <Popover open={menu} onOpenChange={setMenu}>
          <PopoverTrigger asChild>
            <IconButton variant="outline" size="default" className="px-3 text-muted-foreground" label={t("workflowMore")}>
              <MoreHorizontal size={14} />
            </IconButton>
          </PopoverTrigger>
          <MenuContent label={t("workflowMore")} align="end">
            <MenuItem icon={<Copy />} label={t("workflowCopy")} onClick={() => { setMenu(false); onCopy(); }} />
            <MenuItem icon={<PencilLine />} label={t("workflowRename")} onClick={() => { setMenu(false); onRename(); }} />
            <MenuItem
              icon={<Download />}
              label={t("workflowExport")}
              description={t("workflowExportDesc")}
              onClick={() => {
                setMenu(false);
                setExportError("");
                onExport().catch((error) => setExportError(errorText(error)));
              }}
            />
            <MenuSeparator />
            <MenuItem icon={<Trash2 />} label={t("workflowDelete")} destructive onClick={() => { setMenu(false); onDelete(); }} />
          </MenuContent>
        </Popover>
        </>
      }
      media={media}
    >
      {note && <EditorNoteLine note={note} onDismiss={onDismissNote} />}
      {exportError && <p role="alert" className="m-0 text-ui-sm text-destructive">{exportError}</p>}
      {flow.problem && (
        <div role="alert" className="flex min-w-0 items-start gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
          <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
          <span className="min-w-0 break-words">{flow.problem}</span>
        </div>
      )}
      {app}
      <WorkflowFacts
        facts={flow}
        onShowModel={onShowModel}
        packAction={(pack) =>
          manager && !pack.installed && !installs.some((job) =>
            (installActive(job) || awaitingRestart(job, restartedAt)) && packsOf(job).includes(pack.id)) ? (
            <Button variant="outline" size="xs" className="ml-auto shrink-0"
                    aria-label={t("workflowInstallPackLabel").replace("{name}", pack.title)} onClick={() => onInstall(pack)}>
              {t("workflowInstallPack")}
            </Button>
          ) : null
        }
        missingNodesNote={
          <NodeInstallNote
            manager={manager}
            jobs={installs}
            restartedAt={restartedAt}
            packs={(flow.missing_nodes ?? []).flatMap((node) => node.packs ?? [])}
            restarting={restarting}
            restartError={restartError}
            onRestart={onRestart}
          />
        }
      />
      {flow.last_output && (
        <LibrarySection title={t("workflowLastOutput")}>
          <div className="flex min-w-0 items-center gap-3">
            <img
              src={assetThumbnailUrl(flow.last_output.asset_id)}
              alt={t("workflowLastOutputAlt").replace("{name}", flow.label)}
              loading="lazy"
              className="size-24 shrink-0 rounded-lg bg-secondary object-cover"
            />
            <span className="text-ui-xs tabular-nums text-muted-foreground">
              {new Date(flow.last_output.created_at).toLocaleString(locale)}
            </span>
          </div>
        </LibrarySection>
      )}
      <LibrarySection title={t("workflowUsedBy")} count={flow.used_by?.length ?? 0}>
        {(flow.used_by?.length ?? 0) > 0 ? (
          <ul className="m-0 grid list-none gap-1 p-0">
            {(flow.used_by ?? []).map((one) => (
              <li key={`${one.kind}-${one.id}`} className="flex min-w-0">
                <button
                  type="button"
                  className="-mx-2 flex h-8 min-w-0 max-w-full cursor-pointer items-center gap-2 rounded-md px-2 text-left text-ui-sm text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() =>
                    one.kind === "board"
                      ? gotoRecord(`#/boards?board=${encodeURIComponent(one.id)}`, "mosael:open-board", one.id)
                      : gotoRecord(`#/workflows?workflow=${encodeURIComponent(one.id)}`, "mosael:open-workflow", one.id)
                  }
                >
                  {one.kind === "board" ? <LayoutGrid size={13} aria-hidden className="shrink-0 text-muted-foreground" />
                    : <Workflow size={13} aria-hidden className="shrink-0 text-muted-foreground" />}
                  <Truncate>{one.name}</Truncate>
                  <span aria-hidden className="shrink-0 text-ui-xs text-muted-foreground">
                    {one.kind === "board" ? t("workflowUseBoard") : t("workflowUseWorkflow")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowUsedByNone")}</p>
        )}
      </LibrarySection>
    </LibraryDetail>
  );
}

/**
 * 回收站:Mosael 删除的工作流(挪进那台机器的 `.mosael-trash/workflows/` 了)。能恢复;Mosael 不提供清空 ——
 * 真要删掉,在那台机器上删那个目录(ADR 0035 §3)。
 */
function TrashList({ items, onRestore }: { items: WorkflowTrashed[]; onRestore: (one: WorkflowTrashed) => void }) {
  const t = useI18n();
  const { locale } = usePreferences();
  return (
    <ul aria-label={t("workflowLibraryTrash")} className="m-0 grid list-none gap-2 p-0">
      {items.map((one) => (
        <li key={one.path} className="flex min-w-0 items-center gap-3 rounded-xl border border-border bg-panel p-3">
          <Trash2 size={14} aria-hidden className="shrink-0 text-muted-foreground" />
          <span className="grid min-w-0 flex-1 gap-0.5">
            <Truncate className="text-ui-sm font-medium text-foreground">{one.label}</Truncate>
            <span className="flex min-w-0 items-baseline gap-2 text-ui-xs text-muted-foreground">
              <Truncate>{one.original}</Truncate>
              {one.deleted_at != null && (
                <span className="shrink-0 tabular-nums">
                  {t("workflowDeletedAt").replace("{time}", new Date(one.deleted_at * 1000).toLocaleString(locale))}
                </span>
              )}
            </span>
          </span>
          <Button variant="outline" size="sm" aria-label={t("workflowRestore")} onClick={() => onRestore(one)}>
            <RotateCcw size={13} />
            {t("workflowRestore")}
          </Button>
        </li>
      ))}
    </ul>
  );
}

/**
 * 复制、改名、恢复都要一个名字:先确认,写明改的是哪台机器上的文件。`.json` 不用自己写;不合格的当场说、点不了;
 * 撞名(409)不覆盖 —— 说清楚,给一个建议名。
 */
function WorkflowPathDialog({
  title,
  confirmLabel,
  where,
  initial,
  onSubmit,
  onClose,
}: {
  title: string;
  confirmLabel: string;
  where: string;
  initial: string;
  onSubmit: (path: string) => Promise<void>;
  onClose: () => void;
}) {
  const t = useI18n();
  const state = useWorkflowPath(initial, onSubmit, onClose);
  const pending = state.pending;
  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !pending && onClose()}
      title={title}
      className="w-[min(520px,calc(100vw-32px))]"
      footer={
        <>
          <Button variant="ghost" disabled={pending} onClick={onClose}>{t("cancel")}</Button>
          <Button loading={pending} disabled={state.bad} onClick={() => void state.submit()}>{confirmLabel}</Button>
        </>
      }
    >
      <div className="grid gap-3">
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{where}</p>
        <WorkflowPathField state={state} />
      </div>
    </ModalShell>
  );
}
