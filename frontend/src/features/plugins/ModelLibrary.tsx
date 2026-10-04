import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  ChevronDown,
  CircleAlert,
  Copy,
  Download,
  LayoutGrid,
  Library,
  RefreshCcw,
  Search,
  SearchX,
  TriangleAlert,
  Workflow,
  X,
} from "lucide-react";

import {
  cancelJob,
  getJob,
  getModelDetail,
  getModelLibrary,
  resolveModelLink,
  startModelDownload,
  type Job,
  type MissingModel,
  type ModelFile,
  type ModelLibrary,
  type ModelResolved,
  type PluginInstance,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n, usePreferences } from "@/app/preferences";
import { CatalogBadge, CatalogDetail, CatalogSection } from "@/components/app/CatalogDialog";
import { LibraryDialog, LibraryFilterChips, type LibraryChip, type LibraryNavItem } from "@/components/app/LibraryBrowser";
import { ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { MenuContent, MenuItem, MenuSeparator } from "@/components/ui/menu";
import { OptionPicker } from "@/components/ui/option-picker";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { Progress } from "@/components/ui/progress";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import {
  ALL_FOLDERS,
  DOWNLOADS_VIEW,
  MISSING_VIEW,
  SORTS,
  UNKNOWN_FAMILY,
  familyCounts,
  filterModels,
  folderEntries,
  inFolder,
  sortModels,
  type LibrarySort,
} from "@/features/plugins/modelLibraryView";
import { ModelThumb, folderIcon, modelBaseName, modelSubFolder, normModelName } from "@/components/generation/ModelThumb";
import { formatBytes } from "@/lib/bytes";
import { isImeKeystroke } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

/**
 * 模型库(ADR 0034):一个连接**那台服务器上的模型文件**。任何认领了 `model_library` 的插件连接都走这里,不认识哪一家。
 *
 * 版式是文件浏览器那一套(LibraryBrowser):左边一列目录(按数量排、空的不列),「工作流缺的模型」(一键下载)和
 * 「下载记录」(进度、取消)是钉在这一列底部的特殊项;右边顶上一条工具条 —— 搜索、按底模多选(只列当前目录里有的)、
 * 排序 —— 下面是卡片网格(有预览图用预览图,没有就是按目录分的占位),点开是一页详情(元数据、触发词、在用的工作流)。
 * 下载框先解析链接(文件名、大小、建议的目录),同名文件不覆盖 —— 要求换名。
 *
 * 列表每次打开现问插件(不存库);下载的进度读任务本身,不反复让插件把几百个文件再列一遍。
 */

type Translate = ReturnType<typeof useI18n>;

const keyOf = (model: { folder: string; name: string }) => `${model.folder}/${model.name}`;
const norm = normModelName;
const baseName = modelBaseName;
const subFolder = modelSubFolder;

/** 一个不撞名的建议:`x.safetensors` → `x (1).safetensors`、`x (2).safetensors`……按用户此刻选的目录算(他可能改了目录)。 */
export function freeName(name: string, taken: Set<string>): string {
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : "";
  for (let index = 1; index < 1000; index += 1) {
    const candidate = `${stem} (${index})${ext}`;
    if (!taken.has(norm(candidate))) return candidate;
  }
  return name;
}

/** 文件名只能是一段(插件和宿主都会再查一遍)。 */
const plainName = (name: string) => {
  const text = name.trim();
  return Boolean(text) && text !== "." && text !== ".." && !/[\\/:]/.test(text);
};

const ACTIVE = new Set(["queued", "running"]);

/**
 * 连接标题行上的「模型库」(收起时也在,和「刷新」并排):一颗图标按钮,悬停说它是什么;连接停着时点不了,并说为什么。
 */
export function ModelLibraryButton({ instance, workspaceId }: { instance: PluginInstance; workspaceId: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <IconButton
        variant="outline"
        size="default"
        className="px-3 text-muted-foreground"
        label={t("modelLibraryOpen")}
        hint={t("modelLibraryDesc")}
        disabled={Boolean(instance.blocked_reason)}
        disabledReason={instance.blocked_reason}
        onClick={() => setOpen(true)}
      >
        <Library size={13} />
      </IconButton>
      {open && <ModelLibraryDialog open={open} onOpenChange={setOpen} instance={instance} workspaceId={workspaceId} />}
    </>
  );
}

type DownloadSeed = { url?: string; folder?: string; name?: string };

export function ModelLibraryDialog({
  open,
  onOpenChange,
  instance,
  workspaceId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: PluginInstance;
  workspaceId: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const queryKey = React.useMemo(() => ["model-library", instance.id], [instance.id]);
  const library = useQuery({ queryKey, queryFn: () => getModelLibrary(instance.id), enabled: open, staleTime: 30_000 });
  const [view, setView] = React.useState(ALL_FOLDERS);
  const [families, setFamilies] = React.useState<string[]>([]);
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<LibrarySort>("name");
  const [detailKey, setDetailKey] = React.useState<string | null>(null);
  const [seed, setSeed] = React.useState<DownloadSeed | null>(null);
  //: 这次打开之后发起的下载(列表里的那份是打开时的快照)。
  const [started, setStarted] = React.useState<Job[]>([]);

  const models = React.useMemo(() => library.data?.models ?? [], [library.data]);
  const folders = React.useMemo(() => folderEntries(library.data?.folders ?? []), [library.data]);
  const missing = library.data?.missing ?? [];
  const special = view === MISSING_VIEW || view === DOWNLOADS_VIEW;
  const scope = React.useMemo(() => inFolder(models, special ? ALL_FOLDERS : view), [models, view, special]);
  const familyList = React.useMemo(() => familyCounts(scope), [scope]);
  //: 勾着的底模里,当前目录没有的不算数 —— 换了目录,网格不该因为上一个目录勾的东西莫名其妙是空的。
  const activeFamilies = families.filter((one) => familyList.some(([value]) => value === one));
  const shown = sortModels(filterModels(scope, { families: activeFamilies, query }), sort);
  const detail = detailKey ? models.find((model) => keyOf(model) === detailKey) ?? null : null;

  const downloads = useDownloads(library.data, started, () => {
    void qc.invalidateQueries({ queryKey });
    // 生成表单的下拉、工作流节点:下好的文件要马上选得到(宿主那边已经刷新了这个连接的目录)
    invalidatePluginDependents(qc);
  });

  const changeView = (next: string) => {
    setView(next);
    setFamilies((current) => current.filter((one) => familyCounts(inFolder(models, next)).some(([value]) => value === one)));
  };
  const clearFilters = () => {
    setQuery("");
    setFamilies([]);
  };
  const familyName = (value: string) => (value === UNKNOWN_FAMILY ? t("modelLibraryFamilyUnknown") : value);
  const scopeName = view === ALL_FOLDERS ? "" : view;

  const navItems: LibraryNavItem[] = [
    { value: ALL_FOLDERS, label: t("modelLibraryAll"), count: models.length, icon: <LayoutGrid /> },
    ...folders.map((one) => {
      const Icon = folderIcon(one.name);
      return { value: one.name, label: one.name, count: one.count, icon: <Icon /> };
    }),
  ];
  const pinned: LibraryNavItem[] = [
    ...(missing.length > 0
      ? [{ value: MISSING_VIEW, label: t("modelMissingTitle"), count: missing.length, icon: <TriangleAlert />, tone: "warning" as const }]
      : []),
    ...(downloads.length > 0 ? [{ value: DOWNLOADS_VIEW, label: t("modelLibraryDownloadsNav"), count: downloads.length, icon: <Download /> }] : []),
  ];
  //: 特殊项没了(缺的都下好了)还停在那一页:回到「全部」。
  const current = [...navItems, ...pinned].some((one) => one.value === view) ? view : ALL_FOLDERS;

  const chips: LibraryChip[] = [
    ...(query.trim()
      ? [{
          key: "query",
          label: t("modelLibraryChipSearch").replace("{query}", query.trim()),
          removeLabel: t("modelLibraryChipRemoveSearch").replace("{query}", query.trim()),
          onRemove: () => setQuery(""),
        }]
      : []),
    ...activeFamilies.map((one) => ({
      key: `family:${one}`,
      label: familyName(one),
      removeLabel: t("modelLibraryChipRemoveFamily").replace("{family}", familyName(one)),
      onRemove: () => setFamilies((list) => list.filter((value) => value !== one)),
    })),
  ];

  const searchLabel = scopeName
    ? t("modelLibrarySearchIn").replace("{folder}", scopeName).replace("{n}", String(scope.length))
    : t("modelLibrarySearch").replace("{n}", String(scope.length));

  const actions = (
    <>
      <IconButton
        variant="outline"
        size="default"
        className="px-3 text-muted-foreground"
        label={t("modelLibraryRefresh")}
        loading={library.isFetching}
        onClick={() => void library.refetch()}
      >
        <RefreshCcw size={13} />
      </IconButton>
      <Button onClick={() => setSeed({})} disabled={!library.data}>
        <Download size={13} />
        {t("modelLibraryDownload")}
      </Button>
    </>
  );

  const toolbar =
    current === MISSING_VIEW || current === DOWNLOADS_VIEW ? (
      <>
        <div className="grid min-w-0 flex-1 basis-[240px] gap-0.5">
          <h3 className="m-0 text-ui-md font-semibold text-foreground">
            {current === MISSING_VIEW ? t("modelMissingTitle") : t("modelLibraryDownloadsNav")}
          </h3>
          <p className="m-0 text-ui-xs text-muted-foreground">
            {current === MISSING_VIEW ? t("modelMissingDesc") : t("modelLibraryDownloadsDesc")}
          </p>
        </div>
        {actions}
      </>
    ) : (
      <>
        <label className="relative min-w-[180px] flex-1 basis-[220px]">
          <Search size={14} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder={searchLabel}
            aria-label={scopeName ? t("modelLibrarySearchIn").replace("{folder}", scopeName).replace("{n}", String(scope.length)) : searchLabel}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <FamilyFilter
          families={familyList}
          value={activeFamilies}
          onChange={setFamilies}
          nameOf={familyName}
        />
        <OptionPicker
          className="w-[148px]"
          ariaLabel={t("modelLibrarySort")}
          value={sort}
          onChange={(next) => setSort(SORTS.includes(next as LibrarySort) ? (next as LibrarySort) : "name")}
          options={SORTS.map((one) => ({
            value: one,
            label: t(one === "name" ? "modelLibrarySortName" : one === "size" ? "modelLibrarySortSize" : "modelLibrarySortModified"),
          }))}
        />
        {actions}
      </>
    );

  const content = (openItem: (key: string) => void) => {
    if (library.isLoading) return <p className="m-auto text-ui-sm text-muted-foreground">{t("modelLibraryLoading")}</p>;
    if (library.isError) {
      return (
        <p className="m-auto max-w-[520px] text-center text-ui-sm text-destructive">
          {t("modelLibraryError").replace("{error}", errorText(library.error))}
        </p>
      );
    }
    if (current === MISSING_VIEW) {
      return <MissingList missing={missing} onDownload={(one) => setSeed({ url: one.url, folder: one.folder, name: one.name })} />;
    }
    if (current === DOWNLOADS_VIEW) return <DownloadList jobs={downloads} />;
    if (shown.length === 0) {
      return chips.length > 0 ? (
        <EmptyState
          size="section"
          icon={<SearchX />}
          title={t("modelLibraryNoMatchTitle")}
          body={t("modelLibraryNoMatchBody")}
          action={<Button variant="secondary" onClick={clearFilters}>{t("modelLibraryClearFilters")}</Button>}
        />
      ) : (
        <EmptyState size="section" icon={<Library />} title={t("modelLibraryEmpty")} />
      );
    }
    return (
      <ul
        role="list"
        aria-label={t("modelLibraryTitle").replace("{name}", instance.name)}
        className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,220px),1fr))] gap-3 p-0"
      >
        {shown.map((model) => (
          <li key={keyOf(model)} className="grid min-w-0">
            <ModelCard instanceId={instance.id} model={model} onOpen={() => openItem(keyOf(model))} />
          </li>
        ))}
      </ul>
    );
  };

  return (
    <LibraryDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("modelLibraryTitle").replace("{name}", instance.name)}
      nav={
        library.data
          ? { label: t("modelLibraryFolders"), value: current, onChange: changeView, items: navItems, pinned }
          : undefined
      }
      toolbar={toolbar}
      chips={
        !special && library.data ? (
          <LibraryFilterChips
            label={t("modelLibraryActiveFilters")}
            summary={t("modelLibraryResultCount").replace("{n}", String(shown.length))}
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
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="shrink-0 px-6 pb-2">
              <Button variant="ghost" className="-ml-3" onClick={() => setDetailKey(null)}>
                <ArrowLeft />
                {t("modelLibraryBack")}
              </Button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
              <ModelDetailPage instanceId={instance.id} model={detail} />
            </div>
          </div>
        )
      }
      dialogs={
        seed && library.data ? (
          <ModelDownloadDialog
            instance={instance}
            workspaceId={workspaceId}
            library={library.data}
            seed={seed}
            onClose={() => setSeed(null)}
            onStarted={(job) => {
              setStarted((list) => [job, ...list]);
              // 发起的下载在「下载记录」里看进度
              setView(DOWNLOADS_VIEW);
            }}
          />
        ) : undefined
      }
    >
      {content}
    </LibraryDialog>
  );
}

/**
 * 按底模筛:勾几种都行(其中任一),勾的时候菜单不关。只列**当前目录里有的**底模,每种标着几个文件 ——
 * 勾之前就知道会剩多少。只有一种(或一种都认不出)时没什么可筛的,按钮点不了并说为什么。
 */
function FamilyFilter({
  families,
  value,
  onChange,
  nameOf,
}: {
  families: [string, number][];
  value: string[];
  onChange: (value: string[]) => void;
  nameOf: (family: string) => string;
}) {
  const t = useI18n();
  const chosen = new Set(value);
  const label =
    value.length === 0
      ? t("modelLibraryFamilyButton")
      : value.length === 1
        ? `${t("modelLibraryFamilyButton")} · ${nameOf(value[0])}`
        : `${t("modelLibraryFamilyButton")} · ${value.length}`;
  if (families.length < 2) {
    return (
      <Hint label={t("modelLibraryFamilyHint")} disabledReason={t("modelLibraryFamilySingle")}>
        <Button variant="outline" disabled aria-label={t("modelLibraryFamilyLabel")}>
          {t("modelLibraryFamilyButton")}
          <ChevronDown />
        </Button>
      </Hint>
    );
  }
  return (
    <Popover>
      <Hint label={t("modelLibraryFamilyHint")}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            aria-label={`${t("modelLibraryFamilyLabel")}${value.length ? ` · ${label}` : ""}`}
            className={cn("max-w-[220px]", value.length > 0 && "border-primary/40 bg-accent text-primary")}
          >
            <Truncate>{label}</Truncate>
            <ChevronDown />
          </Button>
        </PopoverTrigger>
      </Hint>
      <MenuContent label={t("modelLibraryFamilyLabel")} align="end">
        {families.map(([family, count]) => (
          <MenuItem
            key={family}
            role="menuitemcheckbox"
            aria-label={`${nameOf(family)} ${count}`}
            checked={chosen.has(family)}
            label={nameOf(family)}
            truncate
            hint={count}
            onClick={() => onChange(chosen.has(family) ? value.filter((one) => one !== family) : [...value, family])}
          />
        ))}
        {value.length > 0 && (
          <>
            <MenuSeparator />
            <MenuItem label={t("modelLibraryFamilyClear")} onClick={() => onChange([])} />
          </>
        )}
      </MenuContent>
    </Popover>
  );
}

/**
 * 要盯着的下载:打开时列表里带的那几条 + 这次发起的。在跑的隔一会儿读一次任务本身(不让插件把几百个文件再列一遍);
 * 有一条成功了就让模型库重新列一遍(`onSucceeded`)。
 */
function useDownloads(library: ModelLibrary | undefined, started: Job[], onSucceeded: () => void): Job[] {
  const known = React.useMemo(() => {
    //: 列表重新列过之后,它带的那一份比「发起时」的那一份新:先认它的。
    const listed = library?.downloads ?? [];
    const ids = new Set(listed.map((job) => job.id));
    return [...started.filter((job) => !ids.has(job.id)), ...listed];
  }, [library, started]);
  const watching = known.filter((job) => ACTIVE.has(job.status)).map((job) => job.id);
  const live = useQuery({
    queryKey: ["model-downloads", watching],
    queryFn: () => Promise.all(watching.map((id) => getJob(id))),
    enabled: watching.length > 0,
    refetchInterval: 1500,
  });
  const fresh = new Map((live.data ?? []).map((job) => [job.id, job]));
  const merged = known.map((job) => fresh.get(job.id) ?? job);
  const succeeded = merged.filter((job) => job.status === "succeeded" && watching.includes(job.id)).map((job) => job.id).join(",");
  const callback = React.useRef(onSucceeded);
  callback.current = onSucceeded;
  React.useEffect(() => {
    if (succeeded) callback.current();
  }, [succeeded]);
  return merged;
}

function DownloadList({ jobs }: { jobs: Job[] }) {
  const t = useI18n();
  const cancel = useMutation({ mutationFn: (id: string) => cancelJob(id) });
  return (
    <section className="grid min-w-0 gap-2 rounded-xl border border-border bg-panel p-3" aria-label={t("modelDownloadsTitle")}>
      <h3 className="m-0 text-ui-sm font-semibold text-foreground">{t("modelDownloadsTitle")}</h3>
      <ul className="m-0 grid list-none gap-2 p-0">
        {jobs.map((job) => {
          const name = String((job.payload as Record<string, unknown>).filename ?? "");
          const folder = String((job.payload as Record<string, unknown>).folder ?? "");
          const active = ACTIVE.has(job.status);
          return (
            <li key={job.id} className="grid min-w-0 gap-1.5">
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex min-w-0 flex-1 items-baseline gap-2">
                  <Truncate className="text-ui-sm text-foreground">{name}</Truncate>
                  <span className="shrink-0 text-ui-xs text-muted-foreground">{folder}</span>
                </span>
                {job.status === "succeeded" && (
                  <CatalogBadge tone="success" icon={<Check />}>{t("modelDownloadDone")}</CatalogBadge>
                )}
                {job.status === "failed" && (
                  <CatalogBadge tone="warning" icon={<CircleAlert />}>{t("modelDownloadFailedLabel")}</CatalogBadge>
                )}
                {active && (
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={t("modelDownloadCancelLabel").replace("{name}", name)}
                    loading={cancel.isPending && cancel.variables === job.id}
                    onClick={() => cancel.mutate(job.id)}
                  >
                    <X size={13} />
                    {t("modelDownloadCancel")}
                  </Button>
                )}
              </div>
              {active && <Progress value={Math.round((job.progress || 0) * 100)} aria-label={name} />}
              <p
                className={cn(
                  "m-0 min-w-0 break-words text-ui-xs leading-relaxed",
                  job.status === "failed" ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {job.status === "failed" ? job.error || job.message : job.message}
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function MissingList({ missing, onDownload }: { missing: MissingModel[]; onDownload: (one: MissingModel) => void }) {
  const t = useI18n();
  return (
    <section className="grid min-w-0 gap-2 rounded-xl border border-warning/40 bg-panel p-3" aria-label={t("modelMissingTitle")}>
      <div className="grid gap-0.5">
        <h3 className="m-0 text-ui-sm font-semibold text-foreground">{t("modelMissingTitle")}</h3>
        <p className="m-0 text-ui-xs text-muted-foreground">{t("modelMissingDesc")}</p>
      </div>
      <ul className="m-0 grid list-none gap-2 p-0">
        {missing.map((one) => (
          <li key={keyOf(one)} className="flex min-w-0 items-center gap-3">
            <span className="grid min-w-0 flex-1 gap-0.5">
              <span className="flex min-w-0 items-baseline gap-2">
                <Truncate className="text-ui-sm text-foreground" hint={one.url}>{one.name}</Truncate>
                <span className="shrink-0 text-ui-xs text-muted-foreground">{one.folder}</span>
              </span>
              <Truncate className="text-ui-xs text-muted-foreground">
                {t("modelMissingFor").replace("{workflows}", (one.workflows ?? []).map((flow) => flow.label).join(t("listSeparator")))}
              </Truncate>
            </span>
            <Button variant="outline" size="sm" onClick={() => onDownload(one)}>
              <Download size={13} />
              {t("modelMissingDownload")}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FamilyBadge({ model }: { model: ModelFile }) {
  const t = useI18n();
  if (!model.family) return null;
  return (
    <Hint label={model.family_source === "filename" ? t("modelFamilySourceFilename") : t("modelFamilySourceMetadata")}>
      <span className="inline-flex">
        <CatalogBadge tone={model.family_source === "filename" ? "muted" : "primary"}>{model.family}</CatalogBadge>
      </span>
    </Hint>
  );
}

function ModelCard({ instanceId, model, onOpen }: { instanceId: string; model: ModelFile; onOpen: () => void }) {
  const t = useI18n();
  const sub = subFolder(model.name);
  const meta = [model.folder + (sub ? `/${sub}` : ""), model.size != null ? formatBytes(model.size) : ""].filter(Boolean).join(" · ");
  const used = model.used_by?.length ?? 0;
  return (
    <article
      data-library-item={keyOf(model)}
      className={cn(
        "relative grid min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_1fr] overflow-hidden rounded-xl border border-border bg-panel transition-colors",
        "hover:border-border-strong hover:bg-panel-subtle",
        "has-[[data-library-open]:focus-visible]:border-primary has-[[data-library-open]:focus-visible]:ring-2 has-[[data-library-open]:focus-visible]:ring-ring",
      )}
    >
      <ModelThumb instanceId={instanceId} model={model} className="aspect-[4/3] w-full" />
      <div className="grid min-w-0 content-start gap-1.5 p-3">
        <h3 className="m-0 min-w-0 text-ui-sm font-semibold leading-snug text-foreground">
          <button
            type="button"
            data-library-open
            className="block max-w-full cursor-pointer text-left after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none"
            onClick={onOpen}
          >
            <Truncate>{baseName(model.name)}</Truncate>
          </button>
        </h3>
        <Truncate as="p" className="m-0 text-ui-xs text-muted-foreground">{meta}</Truncate>
        {(model.family || used > 0 || (model.triggers?.length ?? 0) > 0) && (
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <FamilyBadge model={model} />
            {used > 0 && <CatalogBadge tone="success" icon={<Workflow />}>{t("modelUsedCount").replace("{n}", String(used))}</CatalogBadge>}
            {(model.triggers?.length ?? 0) > 0 && (
              <CatalogBadge tone="muted">{t("modelTriggerCount").replace("{n}", String(model.triggers?.length ?? 0))}</CatalogBadge>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <Button
      variant="outline"
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      {label}
    </Button>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <dt className="text-ui-xs text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 break-words text-ui-sm text-foreground">{children}</dd>
    </div>
  );
}

function ModelDetailPage({ instanceId, model }: { instanceId: string; model: ModelFile }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const meta = useQuery({
    queryKey: ["model-library-detail", instanceId, model.folder, model.name],
    queryFn: () => getModelDetail(instanceId, model.folder, model.name),
  });
  const Icon = folderIcon(model.folder);
  const entries = Object.entries(meta.data?.metadata ?? {});
  const triggers = model.triggers ?? [];
  return (
    <CatalogDetail
      icon={<Icon />}
      title={baseName(model.name)}
      badges={<FamilyBadge model={model} />}
      meta={[model.folder, model.size != null ? formatBytes(model.size) : ""].filter(Boolean).join(" · ")}
      actions={<CopyButton text={model.name} label={t("modelCopyName")} />}
      aside={
        <CatalogSection title={t("modelFileFacts")}>
          <dl className="m-0 grid gap-3">
            <Fact label={t("modelFolder")}>{model.folder}</Fact>
            <Fact label={t("modelFileName")}>{model.name}</Fact>
            {model.size != null && <Fact label={t("modelSize")}>{formatBytes(model.size)}</Fact>}
            {model.modified != null && (
              <Fact label={t("modelModified")}>{new Date(model.modified * 1000).toLocaleString(locale)}</Fact>
            )}
            {model.family && (
              <Fact label={t("modelFamily")}>
                {model.family}
                <span className="block text-ui-xs text-muted-foreground">
                  {model.family_source === "filename" ? t("modelFamilySourceFilename") : t("modelFamilySourceMetadata")}
                </span>
              </Fact>
            )}
          </dl>
        </CatalogSection>
      }
    >
      {model.has_preview && (
        <ModelThumb instanceId={instanceId} model={model} className="max-h-[420px] w-full rounded-xl object-contain" />
      )}
      {triggers.length > 0 && (
        <CatalogSection title={t("modelTriggers")} count={triggers.length}>
          {model.triggers_source === "tags" && <p className="m-0 text-ui-xs text-muted-foreground">{t("modelTriggersFromTags")}</p>}
          <div className="flex min-w-0 flex-wrap gap-1.5">
            {triggers.map((word) => (
              <Hint key={word} label={t("modelTriggerCopy").replace("{word}", word)}>
                <button
                  type="button"
                  className="cursor-pointer rounded-full bg-secondary px-2.5 py-1 text-ui-xs text-foreground hover:bg-secondary/70"
                  onClick={() => void navigator.clipboard?.writeText(word)}
                >
                  {word}
                </button>
              </Hint>
            ))}
          </div>
        </CatalogSection>
      )}
      <CatalogSection title={t("modelUsedBy")} count={model.used_by?.length ?? 0}>
        {(model.used_by?.length ?? 0) > 0 ? (
          <ul className="m-0 grid list-none gap-1 p-0">
            {(model.used_by ?? []).map((flow) => (
              <li key={flow.id} className="flex min-w-0 items-center gap-2 text-ui-sm text-foreground">
                <Workflow size={13} className="shrink-0 text-muted-foreground" />
                <Truncate hint={flow.id !== flow.label ? flow.id : undefined}>{flow.label}</Truncate>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("modelUsedByNone")}</p>
        )}
      </CatalogSection>
      {(meta.data?.tags?.length ?? 0) > 0 && (
        <CatalogSection title={t("modelTags")} count={meta.data?.tags?.length}>
          <div className="flex min-w-0 flex-wrap gap-1.5">
            {(meta.data?.tags ?? []).slice(0, 60).map((one) => (
              <span key={one.tag} className="rounded-full bg-secondary px-2.5 py-1 text-ui-xs text-foreground">
                {one.tag}
                <span className="ml-1 tabular-nums text-muted-foreground">{one.count}</span>
              </span>
            ))}
          </div>
        </CatalogSection>
      )}
      <CatalogSection title={t("modelMetadata")} count={entries.length || undefined}>
        {meta.isLoading ? (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("modelMetadataLoading")}</p>
        ) : meta.isError ? (
          <p className="m-0 text-ui-xs text-destructive">{errorText(meta.error)}</p>
        ) : entries.length === 0 ? (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("modelMetadataEmpty")}</p>
        ) : (
          <dl className="m-0 grid min-w-0 grid-cols-[minmax(120px,max-content)_minmax(0,1fr)] gap-x-4 gap-y-1.5">
            {entries.map(([key, value]) => (
              <React.Fragment key={key}>
                <Truncate as="dt" className="text-ui-xs text-muted-foreground">{key}</Truncate>
                <Truncate as="dd" lines={3} className="m-0 break-all text-ui-xs text-foreground">{value}</Truncate>
              </React.Fragment>
            ))}
          </dl>
        )}
      </CatalogSection>
    </CatalogDetail>
  );
}

function sourceLabel(t: Translate, resolved: ModelResolved): string {
  if (resolved.source === "huggingface") return t("modelDownloadSourceHuggingface");
  if (resolved.source === "civitai") return t("modelDownloadSourceCivitai");
  let host = "";
  try {
    host = new URL(resolved.url).host;
  } catch {
    host = resolved.url;
  }
  return t("modelDownloadSourceDirect").replace("{host}", host);
}

function ModelDownloadDialog({
  instance,
  workspaceId,
  library,
  seed,
  onClose,
  onStarted,
}: {
  instance: PluginInstance;
  workspaceId: string;
  library: ModelLibrary;
  seed: DownloadSeed;
  onClose: () => void;
  onStarted: (job: Job) => void;
}) {
  const t = useI18n();
  const [url, setUrl] = React.useState(seed.url ?? "");
  const [filename, setFilename] = React.useState(seed.name ?? "");
  const [folder, setFolder] = React.useState(seed.folder ?? "");
  const resolve = useMutation({
    mutationFn: (link: string) => resolveModelLink(instance.id, link),
    onSuccess: (found) => {
      setFilename((current) => current || seed.name || found.filename);
      setFolder((current) => current || seed.folder || found.folder);
    },
  });
  const start = useMutation({
    mutationFn: () =>
      startModelDownload(instance.id, {
        workspace_id: workspaceId,
        url: resolve.data?.url ?? url.trim(),
        folder,
        filename: filename.trim(),
      }),
    onSuccess: (job) => {
      onStarted(job);
      onClose();
    },
  });
  const resolveRef = React.useRef(resolve.mutate);
  resolveRef.current = resolve.mutate;
  React.useEffect(() => {
    if (seed.url) resolveRef.current(seed.url);
  }, [seed.url]);

  const taken = React.useMemo(
    () => new Set((library.models ?? []).filter((model) => model.folder === folder).map((model) => norm(model.name))),
    [library.models, folder],
  );
  const exists = Boolean(folder && filename.trim() && taken.has(norm(filename)));
  const route = library.download?.route ?? "none";
  const resolved = resolve.data;
  const nameOk = plainName(filename);
  const canStart = Boolean(resolved && folder && nameOk && !exists && route !== "none");
  const folderOptions = [...(library.folders ?? [])]
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .map((one) => ({ value: one.name, label: t("modelDownloadFolderOption").replace("{name}", one.name).replace("{n}", String(one.count)) }));

  return (
    <ModalShell
      open
      onOpenChange={(open) => !open && onClose()}
      title={t("modelDownloadTitle").replace("{name}", instance.name)}
      className="w-[560px] max-w-[calc(100vw-32px)]"
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={!canStart} loading={start.isPending} onClick={() => start.mutate()}>
            <Download size={13} />
            {t("modelDownloadConfirm").replace("{folder}", folder || "…")}
          </Button>
        </div>
      }
    >
      <div className="grid min-w-0 gap-4">
        <label className="grid min-w-0 gap-1.5">
          <span className="text-ui-sm font-medium text-foreground">{t("modelDownloadLink")}</span>
          <div className="flex min-w-0 gap-2">
            <Input
              className="min-w-0 flex-1"
              value={url}
              placeholder={t("modelDownloadLinkPlaceholder")}
              onChange={(event) => setUrl(event.target.value)}
              onKeyDown={(event) => {
                if (isImeKeystroke(event)) return;
                if (event.key === "Enter" && url.trim()) resolve.mutate(url.trim());
              }}
            />
            <Button variant="outline" disabled={!url.trim()} loading={resolve.isPending} onClick={() => resolve.mutate(url.trim())}>
              {t("modelDownloadResolve")}
            </Button>
          </div>
        </label>
        {resolve.isError && <p className="m-0 break-words text-ui-sm text-destructive">{errorText(resolve.error)}</p>}
        {resolved && (
          <>
            <dl className="m-0 grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3 rounded-lg bg-secondary/50 p-3">
              <Fact label={t("modelDownloadSource")}>{sourceLabel(t, resolved)}</Fact>
              <Fact label={t("modelDownloadSize")}>
                {resolved.size != null ? formatBytes(resolved.size) : t("modelDownloadSizeUnknown")}
              </Fact>
              {resolved.title && <Fact label={t("modelDownloadModelName")}>{resolved.title}</Fact>}
              {resolved.family && <Fact label={t("modelFamily")}>{resolved.family}</Fact>}
              {(resolved.triggers ?? []).length > 0 && (
                <div className="col-span-2">
                  <Fact label={t("modelTriggers")}>{(resolved.triggers ?? []).join(t("listSeparator"))}</Fact>
                </div>
              )}
            </dl>
            <label className="grid min-w-0 gap-1.5">
              <span className="text-ui-sm font-medium text-foreground">{t("modelDownloadFilename")}</span>
              <Input value={filename} onChange={(event) => setFilename(event.target.value)} aria-invalid={!nameOk || exists} />
              {!nameOk && filename && <span className="text-ui-xs text-destructive">{t("modelDownloadFilenameBad")}</span>}
            </label>
            <div className="grid min-w-0 gap-1.5">
              <span className="text-ui-sm font-medium text-foreground">{t("modelDownloadFolder")}</span>
              <OptionPicker
                ariaLabel={t("modelDownloadFolder")}
                value={folder}
                onChange={setFolder}
                options={folderOptions}
                placeholder={t("modelDownloadFolderPick")}
                searchPlaceholder={t("modelDownloadFolderSearch")}
              />
            </div>
            {exists && (
              <div role="alert" className="grid gap-2 rounded-lg border border-warning/40 p-3 text-ui-sm text-foreground">
                <span>{t("modelDownloadExists").replace("{folder}", folder).replace("{name}", filename.trim())}</span>
                <span>
                  <Button variant="outline" size="sm" onClick={() => setFilename(freeName(filename.trim(), taken))}>
                    {t("modelDownloadUseSuggestion").replace("{name}", freeName(filename.trim(), taken))}
                  </Button>
                </span>
              </div>
            )}
            {route === "manager" && (
              /* 走 ComfyUI-Manager 时先说清楚的几件事:令牌会留在那台机器上(只在真要带 Civitai 令牌时说)、
                 看不到按字节的进度、开始之后取消停不下那边的下载。 */
              <div
                role="note"
                aria-label={t("modelDownloadManagerCaution")}
                className="grid gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-ui-xs leading-relaxed text-foreground"
              >
                <strong className="text-ui-sm">{t("modelDownloadManagerCaution")}</strong>
                <ul className="m-0 grid list-disc gap-1 pl-4">
                  {resolved.source === "civitai" && resolved.uses_token && <li>{t("modelDownloadCivitaiTokenInUrl")}</li>}
                  {resolved.source === "huggingface" && resolved.uses_token && <li>{t("modelDownloadHfTokenUnsupported")}</li>}
                  <li>{t("modelDownloadManagerNoProgress")}</li>
                  <li>{t("modelDownloadManagerCancel")}</li>
                </ul>
              </div>
            )}
            <p className={cn("m-0 break-words text-ui-xs leading-relaxed", route === "none" ? "text-destructive" : "text-muted-foreground")}>
              {route === "none" && <strong className="mr-1">{t("modelDownloadCannot")}</strong>}
              {library.download?.note}
              {route === "local" && ` ${t("modelDownloadDiskLocal")}`}
              {route === "manager" && ` ${t("modelDownloadDiskRemote")}`}
            </p>
            {start.isError && <p className="m-0 break-words text-ui-sm text-destructive">{errorText(start.error)}</p>}
          </>
        )}
      </div>
    </ModalShell>
  );
}
