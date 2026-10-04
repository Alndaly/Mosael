import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  CircleAlert,
  Copy,
  Download,
  FolderTree,
  LayoutGrid,
  MoreHorizontal,
  PencilLine,
  RefreshCcw,
  RotateCcw,
  Search,
  SearchX,
  Settings2,
  Sparkles,
  Trash2,
  TriangleAlert,
  Unplug,
  Workflow,
} from "lucide-react";

import {
  assetThumbnailUrl,
  copyWorkflow,
  getWorkflowContent,
  getWorkflowLibrary,
  renameWorkflow,
  restoreWorkflow,
  trashWorkflow,
  type PluginInstance,
  type WorkflowFile,
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
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { WorkflowGraphView } from "@/features/plugins/WorkflowGraph";
import {
  ALL_WORKFLOWS,
  PROBLEMS_VIEW,
  TRASH_VIEW,
  WORKFLOW_KINDS,
  WORKFLOW_SORTS,
  conflictOf,
  filterWorkflows,
  freeWorkflowPath,
  inView,
  lacksSomething,
  sortWorkflows,
  validWorkflowPath,
  workflowFolders,
  workflowPathFrom,
  type WorkflowKindFilter,
  type WorkflowSort,
} from "@/features/plugins/workflowLibraryView";
import { gotoRecord } from "@/lib/deepLink";
import { saveJsonToDisk } from "@/lib/download";
import { handOffToGeneration } from "@/lib/generationHandoff";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

/**
 * 工作流库(ADR 0035):一个连接**那台服务器上存着的工作流**。任何认领了 `workflow_library` 的插件连接都走这里,不认识哪一家。
 *
 * 和模型库同一套骨架(LibraryBrowser):左边一列子目录(按数量排),「缺节点或模型」钉在这一列底部;右边顶上搜索、按种类筛、
 * 排序、三档显示方式;一张卡是节点图的缩略预览(照插件给的图摘要画)、名字、种类、节点数、缺什么。点开是详情:能填什么 /
 * 能调什么 / 交出什么、用到的模型、缺的节点和模型、最近的产出、Mosael 里谁在用它;「用它生成」交给 AI 工作台。
 *
 * 列表每次打开现问插件(不存库)。
 */

type Translate = ReturnType<typeof useI18n>;

const keyOf = (flow: WorkflowFile) => flow.path;

export function WorkflowLibraryButton({
  instance,
  workspaceId,
  onCheckSettings,
}: {
  instance: PluginInstance;
  workspaceId: string;
  /** 读不出来时「去检查连接设置」:插件页给的。不给就不摆那颗按钮。 */
  onCheckSettings?: () => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <IconButton
        variant="outline"
        size="default"
        className="px-3 text-muted-foreground"
        label={t("workflowLibraryOpen")}
        hint={t("workflowLibraryDesc")}
        disabled={Boolean(instance.blocked_reason)}
        disabledReason={instance.blocked_reason}
        onClick={() => setOpen(true)}
      >
        <FolderTree size={13} />
      </IconButton>
      {open && (
        <WorkflowLibraryDialog
          open={open}
          onOpenChange={setOpen}
          instance={instance}
          workspaceId={workspaceId}
          onCheckSettings={
            onCheckSettings
              ? () => {
                  setOpen(false);
                  onCheckSettings();
                }
              : undefined
          }
        />
      )}
    </>
  );
}

const kindName = (t: Translate, kind: string) =>
  kind === "image" || kind === "video" || kind === "audio" ? t(`workflowKind_${kind}`) : t("workflowKind_unknown");

export function WorkflowLibraryDialog({
  open,
  onOpenChange,
  instance,
  workspaceId,
  onCheckSettings,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: PluginInstance;
  workspaceId: string;
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
  //: 正在确认的那一次改动(复制、改名、恢复要一个名字;删除只要一句确认)
  const [action, setAction] = React.useState<
    | { kind: "copy" | "rename"; path: string; initial: string }
    | { kind: "restore"; path: string; initial: string }
    | { kind: "delete"; flow: WorkflowFile }
    | null
  >(null);
  const [deleting, setDeleting] = React.useState(false);
  const qc = useQueryClient();
  //: 改完一张:工作流库重新问一遍;生成选项、工具清单里的那张也跟着变(宿主已经让这个连接的目录重拉过)
  const changed = () => {
    void qc.invalidateQueries({ queryKey: ["workflow-library", instance.id] });
    invalidatePluginDependents(qc);
  };

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
        <EmptyState size="section" icon={<Workflow />} title={t("workflowLibraryEmpty")} />
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
      chips={
        library.data ? (
          <LibraryFilterChips
            label={t("modelLibraryActiveFilters")}
            summary={t("workflowLibraryResultCount").replace("{n}", String(shown.length))}
            chips={chips}
            onClearAll={clearFilters}
          />
        ) : undefined
      }
      detailKey={detail ? detailKey : null}
      onOpenItem={setDetailKey}
      onBack={() => setDetailKey(null)}
      detail={
        detail && (
          <WorkflowDetail
            flow={detail}
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
          <CatalogBadge tone={flow.problem ? "warning" : flow.kind ? "primary" : "muted"}>{kindName(t, flow.kind)}</CatalogBadge>
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

const mediaName = (t: Translate, media: string) =>
  media === "image" || media === "video" || media === "audio" || media === "text" ? t(`workflowMedia_${media}`) : media;

/**
 * 一张工作流的详情(LibraryDetail 的骨架):头上是名字、目录 · 种类 · 节点数 · 改动时间,右边「用它生成」;左栏大一号的节点图
 * (带节点标题和分组名);右栏转不过来的原因、能填什么 / 能调什么 / 交出什么、用到的模型、缺的节点和模型、最近的产出、
 * Mosael 里谁在用它。
 */
function WorkflowDetail({
  flow,
  onBack,
  onCopy,
  onRename,
  onDelete,
  onExport,
}: {
  flow: WorkflowFile;
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
  const parameters = flow.parameters ?? [];
  const [allParameters, setAllParameters] = React.useState(false);

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
      {exportError && <p role="alert" className="m-0 text-ui-sm text-destructive">{exportError}</p>}
      {flow.problem && (
        <div role="alert" className="flex min-w-0 items-start gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
          <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
          <span className="min-w-0 break-words">{flow.problem}</span>
        </div>
      )}
      {(flow.inputs?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowInputs")} count={flow.inputs?.length}>
          <ul className="m-0 grid list-none gap-1 p-0">
            {(flow.inputs ?? []).map((one) => (
              <li key={`${one.node}-${one.role}`} className="flex min-w-0 items-baseline gap-2 text-ui-sm text-foreground">
                <Truncate className="min-w-0 flex-1">{one.title}</Truncate>
                <span className="shrink-0 text-ui-xs text-muted-foreground">{mediaName(t, one.media)}</span>
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
      {parameters.length > 0 && (
        <LibrarySection
          title={t("workflowParameters")}
          count={parameters.length}
          action={
            parameters.length > 12 ? (
              <Button variant="ghost" size="sm" className="text-muted-foreground" aria-expanded={allParameters}
                      onClick={() => setAllParameters(!allParameters)}>
                {allParameters ? t("modelMetaCollapse") : t("modelTagsAll").replace("{n}", String(parameters.length))}
              </Button>
            ) : undefined
          }
        >
          <ul className="m-0 flex min-w-0 list-none flex-wrap gap-1.5 p-0">
            {(allParameters ? parameters : parameters.slice(0, 12)).map((one) => (
              <li key={one.key} className="min-w-0 max-w-full">
                <Hint label={one.key}>
                  <span className="inline-flex h-7 max-w-full items-center rounded-full bg-secondary px-2.5 text-ui-xs text-foreground">
                    <Truncate>{one.title}</Truncate>
                  </span>
                </Hint>
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
      {(flow.outputs?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowOutputs")} count={flow.outputs?.length}>
          <ul className="m-0 grid list-none gap-1 p-0">
            {(flow.outputs ?? []).map((one) => (
              <li key={one.node} className="flex min-w-0 items-baseline gap-2 text-ui-sm text-foreground">
                <Truncate className="min-w-0 flex-1">{one.title}</Truncate>
                <span className="shrink-0 text-ui-xs text-muted-foreground">{mediaName(t, one.media)}</span>
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
      <LibrarySection title={t("workflowModels")} count={flow.models?.length ?? 0}>
        {(flow.models?.length ?? 0) > 0 ? (
          <ul className="m-0 grid list-none gap-1 p-0">
            {(flow.models ?? []).map((one) => (
              <li key={`${one.folder}/${one.name}`} className="flex min-w-0 items-center gap-2 text-ui-sm text-foreground">
                <Truncate className="min-w-0 flex-1">{one.name}</Truncate>
                <span className="shrink-0 text-ui-xs text-muted-foreground">{one.folder}</span>
                <CatalogBadge tone={one.present ? "success" : "warning"}>
                  {one.present ? t("workflowModelPresent") : t("workflowModelMissing")}
                </CatalogBadge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowModelsNone")}</p>
        )}
      </LibrarySection>
      {(flow.missing_nodes?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowMissingNodes")} count={flow.missing_nodes?.length}>
          <ul className="m-0 grid list-none gap-2 p-0">
            {(flow.missing_nodes ?? []).map((one) => (
              <li key={one.type} className="grid min-w-0 gap-0.5">
                <span className="flex min-w-0 items-baseline gap-2 text-ui-sm text-foreground">
                  <Truncate className="min-w-0">{one.type}</Truncate>
                  <span className="shrink-0 text-ui-xs tabular-nums text-muted-foreground">×{one.count}</span>
                </span>
                {(one.packs?.length ?? 0) > 0 ? (
                  (one.packs ?? []).map((pack) => (
                    <span key={pack.id} className="flex min-w-0 items-baseline gap-2 text-ui-xs text-muted-foreground">
                      <Truncate hint={pack.id !== pack.title ? pack.id : undefined}>{pack.title}</Truncate>
                      <span className={cn("shrink-0", pack.installed && "text-warning")}>
                        {pack.installed ? t("workflowPackInstalledNotLoaded") : t("workflowPackNotInstalled")}
                      </span>
                    </span>
                  ))
                ) : (
                  <span className="text-ui-xs text-muted-foreground">{t("workflowPackUnknown")}</span>
                )}
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
      {(flow.missing_models?.length ?? 0) > 0 && (
        <LibrarySection title={t("workflowMissingModels")} count={flow.missing_models?.length}>
          <ul className="m-0 grid list-none gap-1 p-0">
            {(flow.missing_models ?? []).map((one) => (
              <li key={`${one.folder}/${one.name}`} className="grid min-w-0 gap-0.5">
                <span className="flex min-w-0 items-baseline gap-2 text-ui-sm text-foreground">
                  <Truncate className="min-w-0 flex-1">{one.name}</Truncate>
                  <span className="shrink-0 text-ui-xs text-muted-foreground">{one.folder}</span>
                </span>
                <Truncate className="text-ui-xs text-muted-foreground">
                  {one.url ? new URL(one.url).host : t("workflowMissingModelNoUrl")}
                </Truncate>
              </li>
            ))}
          </ul>
        </LibrarySection>
      )}
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
  const [value, setValue] = React.useState(initial);
  const [pending, setPending] = React.useState(false);
  const [clash, setClash] = React.useState<{ path: string; suggestion: string } | null>(null);
  const [error, setError] = React.useState("");
  const path = workflowPathFrom(value);
  const bad = !validWorkflowPath(path);
  const inputId = React.useId();
  const submit = async () => {
    if (bad || pending) return;
    setPending(true);
    setClash(null);
    setError("");
    try {
      await onSubmit(path);
      onClose();
    } catch (failure) {
      const conflict = conflictOf(failure);
      if (conflict) setClash({ path, suggestion: conflict.suggestion });
      else setError(errorText(failure));
    } finally {
      setPending(false);
    }
  };
  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !pending && onClose()}
      title={title}
      className="w-[min(520px,calc(100vw-32px))]"
      footer={
        <>
          <Button variant="ghost" disabled={pending} onClick={onClose}>{t("cancel")}</Button>
          <Button loading={pending} disabled={bad} onClick={() => void submit()}>{confirmLabel}</Button>
        </>
      }
    >
      <div className="grid gap-3">
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{where}</p>
        <div className="grid gap-1.5">
          <label htmlFor={inputId} className="text-ui-xs font-medium text-muted-foreground">{t("workflowPathLabel")}</label>
          <Input
            id={inputId}
            aria-label={t("workflowPathLabel")}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setClash(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) void submit();
            }}
          />
          {bad && value.trim() ? (
            <p className="m-0 text-ui-xs text-destructive">{t("workflowPathBad")}</p>
          ) : (
            <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowPathHelp")}</p>
          )}
        </div>
        {clash && (
          <div role="alert" className="grid gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
            <span>{t("workflowExists").replace("{path}", clash.path)}</span>
            {clash.suggestion && (
              <span>
                <Button variant="outline" size="sm" onClick={() => { setValue(clash.suggestion); setClash(null); }}>
                  {t("workflowUseSuggestion").replace("{name}", clash.suggestion)}
                </Button>
              </span>
            )}
          </div>
        )}
        {error && <p role="alert" className="m-0 text-ui-sm text-destructive">{error}</p>}
      </div>
    </ModalShell>
  );
}
