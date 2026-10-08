import React from "react";
import { FailureCard, failureFields } from "@/components/failure/FailureCard";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  CircleAlert,
  Copy,
  Download,
  ImageDown,
  LayoutGrid,
  Library,
  ListFilter,
  MoreHorizontal,
  RefreshCcw,
  SearchX,
  TriangleAlert,
  Unplug,
  Workflow,
  X,
} from "lucide-react";

import {
  cancelJob,
  getJob,
  resolveModelLink,
  startModelDownload,
  startModelLookup,
  type Job,
  type MissingModel,
  type ModelFile,
  type ModelLibrary,
  type ModelPreviewTools,
  type ModelResolved,
  type PluginInstance,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n, usePreferences } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import {
  LIBRARY_DENSITIES,
  LIBRARY_TABLE_HEAD,
  LibraryDensitySwitch,
  LibraryDialog,
  LibraryFilterChips,
  LibraryToolbarLabel,
  type LibraryChip,
  type LibraryDensity,
  type LibraryNavItem,
  type LibraryReturn,
} from "@/components/app/LibraryBrowser";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { SearchInput } from "@/components/ui/search-input";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { MenuContent, MenuItem, MenuItemBody, MenuSeparator } from "@/components/ui/menu";
import { OptionPicker } from "@/components/ui/option-picker";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { Progress } from "@/components/ui/progress";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import type { Focused, ModelFocus } from "@/features/plugins/libraryLinks";
import { ConnectionFailureActions } from "@/features/plugins/localServiceStatus";
import { FamilyBadge, ModelDetail, placeOf, useModelActionsHost } from "@/features/plugins/ModelDetail";
import { ModelActionsContext } from "@/features/plugins/modelActions";
import { ModelContextMenu, isMenuKey } from "@/features/plugins/ModelMenu";
import { ActiveFamiliesContext } from "@/features/plugins/activeFamilies";
import { EncoderPairs } from "@/features/plugins/ModelEncoder";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import {
  ALL_FOLDERS,
  DOWNLOADS_VIEW,
  MISSING_VIEW,
  SORTS,
  familyCounts,
  type FamilyCount,
  familyLabelKey,
  filterModels,
  folderEntries,
  inFolder,
  sortModels,
  type LibrarySort,
} from "@/features/plugins/modelLibraryView";
import { ModelPreviewSettingsButton } from "@/components/generation/ModelPreviewSettingsButton";
import {
  ModelThumb,
  NsfwMark,
  PreviewOriginMark,
  folderIcon,
  modelBaseName,
  normModelName,
} from "@/components/generation/ModelThumb";
import {
  previewTreatment,
  useModelPreviewSettings,
  type ModelPreviewSettings,
} from "@/components/generation/modelPreviewSettings";
import { useModelLibrary } from "@/components/generation/useModelLibrary";
import { formatBytes } from "@/lib/bytes";
import { useElementWidth } from "@/lib/useElementWidth";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { useVirtualRows, type VirtualRows } from "@/lib/useVirtualRows";
import { isImeKeystroke } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

/**
 * 模型库(ADR 0034):一个连接**那台服务器上的模型文件**。任何认领了 `model_library` 的插件连接都走这里,不认识哪一家。
 *
 * 版式是文件浏览器那一套(LibraryBrowser):左边一列目录(按数量排、空的不列),「工作流缺的模型」(一键下载)和
 * 「下载记录」(进度、取消)是钉在这一列底部的特殊项;右边顶上一条工具条 —— 搜索、按底模多选(只列当前目录里有的)、
 * 排序 —— 下面是卡片网格(有预览图用预览图,没有就是按目录分的占位),点开是一页详情(元数据、触发词、在用的工作流)。
 * 下载框先解析链接(文件名、大小、建议的目录),同名文件不覆盖 —— 要求换名。和工作流库互相跳(见 ConnectionLibraries):
 * 在用的工作流旁边能跳到工作流库那一张;从工作流库跳过来停到那一项,或者为它缺的文件打开下载框。
 *
 * 列表每次打开现问插件(不存库);下载的进度读任务本身,不反复让插件把几百个文件再列一遍。
 */

type Translate = ReturnType<typeof useI18n>;

const keyOf = (model: { folder: string; name: string }) => `${model.folder}/${model.name}`;
const norm = normModelName;
const baseName = modelBaseName;

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

type DownloadSeed = { url?: string; folder?: string; name?: string };

export function ModelLibraryDialog({
  open,
  onOpenChange,
  instance,
  workspaceId,
  focus,
  onShowWorkflow,
  onCheckSettings,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: PluginInstance;
  workspaceId: string;
  /** 从工作流库跳过来:停到这一项,或者为缺的那个文件打开下载框。 */
  focus?: Focused<ModelFocus> | null;
  /** 在用的工作流旁边「在工作流库里看」:连接也认领了工作流库才给。 */
  onShowWorkflow?: (path: string) => void;
  onCheckSettings?: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const library = useModelLibrary(instance.id, { enabled: open, staleTime: 30_000 });
  const queryKey = library.queryKey;
  //: 下完一个、找完一批、存回一张之后作废的是这个连接的模型库(不管挑法是哪一种)
  const libraryPrefix = React.useMemo(() => ["model-library", instance.id], [instance.id]);
  const [view, setView] = React.useState(ALL_FOLDERS);
  const [families, setFamilies] = React.useState<string[]>([]);
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<LibrarySort>("name");
  //: 显示方式记在本机(每台电脑屏幕不一样大);默认小卡片 —— 一屏多看几张。
  const [density, setDensity] = usePersistentTab<LibraryDensity>("model-library.density", "small", LIBRARY_DENSITIES);
  //: 预览图分档、NSFW 单独管(ADR 0038 §9):记在本机,模型库、生成表单的下拉、工作台面板读同一份
  const [previewSettings] = useModelPreviewSettings();
  const [detailKey, setDetailKey] = React.useState<string | null>(null);
  //: 打开详情时要直接跳到哪一节(菜单里的「在用的工作流」)
  const [detailSection, setDetailSection] = React.useState<"used" | null>(null);
  //: 稳定的一个:网格里几百张记忆化的卡拿着它,它一变卡就全重画
  const openDetail = React.useCallback((key: string) => {
    setDetailSection(null);
    setDetailKey(key);
  }, []);
  const [seed, setSeed] = React.useState<DownloadSeed | null>(null);
  //: 这次打开之后发起的下载(列表里的那份是打开时的快照)。
  const [started, setStarted] = React.useState<Job[]>([]);
  React.useEffect(() => {
    if (focus?.model) setDetailKey(keyOf(focus.model));
    else if (focus?.download) setSeed({ ...focus.download });
  }, [focus]);

  const models = React.useMemo(() => library.data?.models ?? [], [library.data]);
  const folders = React.useMemo(() => folderEntries(library.data?.folders ?? []), [library.data]);
  const missing = library.data?.missing ?? [];
  const special = view === MISSING_VIEW || view === DOWNLOADS_VIEW;
  const scope = React.useMemo(() => inFolder(models, special ? ALL_FOLDERS : view), [models, view, special]);
  const familyList = React.useMemo(() => familyCounts(scope), [scope]);
  //: 勾着的底模里,当前目录没有的不算数 —— 换了目录,网格不该因为上一个目录勾的东西莫名其妙是空的。
  const activeFamilies = React.useMemo(
    () => families.filter((one) => familyList.some(([value]) => value === one)),
    [families, familyList],
  );
  //: 记忆化:弹窗为别的事重渲(下载进度、开关)时,网格拿到的还是同一份清单,不重新分行、开窗。
  const shown = React.useMemo(
    () => sortModels(filterModels(scope, { families: activeFamilies, query }), sort),
    [scope, activeFamilies, query, sort],
  );
  const detail = detailKey ? models.find((model) => keyOf(model) === detailKey) ?? null : null;
  const tools = library.data?.preview_tools;
  //: 菜单、详情页要的本事(在 Civitai 上找、存为预览图、标 NSFW……),连同查找任务和「存为预览图」的确认框:和工作台的
  //: 模型库面板同一份(见 ModelDetail)
  const { actions, lookups, dialogs: actionDialogs } = useModelActionsHost({
    instanceId: instance.id,
    instanceName: instance.name,
    workspaceId,
    queryKey,
    shown,
    tools,
    onOpen: (model, section) => {
      setDetailSection(section);
      setDetailKey(keyOf(model));
    },
  });
  //: 「为缺预览图的模型补图」先确认:写的是那台服务器
  const [filling, setFilling] = React.useState(false);
  const fill = useMutation({
    mutationFn: () => startModelLookup(instance.id, { workspace_id: workspaceId, save: true, pick: previewSettings.nsfw === "show" ? "cover" : "safest" }),
    onSuccess: (job) => {
      setFilling(false);
      lookups.add(job);
    },
  });

  const downloads = useDownloads(library.data, started, () => {
    void qc.invalidateQueries({ queryKey: libraryPrefix });
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
  const familyName = (value: string) => {
    const key = familyLabelKey(value);
    return key ? t(key) : value;
  };
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

  const toolbarActions = (
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
      <FillPreviewsButton tools={tools} running={lookups.batchRunning} onClick={() => setFilling(true)} />
      <DownloadButton onClick={() => setSeed({})} />
    </>
  );

  //: 还没读出来(在读 / 读不出来):搜索框、筛选、下载不能装作「0 个文件」—— 搜索框不写数字、点不了,
  //: 筛选和排序不摆,下载点不了并说为什么。在读时的进度、读不出来时的「重试」在内容区里。
  const toolbar = !library.data ? (
    <>
      <SearchInput className="min-w-[180px] flex-1 basis-[180px]" disabled placeholder={t("modelLibrarySearchPending")} aria-label={t("modelLibrarySearchPending")} />
      <DownloadButton disabledReason={library.isError ? t("modelLibraryUnreadable") : t("modelLibraryStillReading")} />
    </>
  ) : current === MISSING_VIEW || current === DOWNLOADS_VIEW ? (
      <>
        <div className="grid min-w-0 flex-1 basis-[240px] gap-0.5">
          <h3 className="m-0 text-ui-md font-semibold text-foreground">
            {current === MISSING_VIEW ? t("modelMissingTitle") : t("modelLibraryDownloadsNav")}
          </h3>
          <p className="m-0 text-ui-xs text-muted-foreground">
            {current === MISSING_VIEW ? t("modelMissingDesc") : t("modelLibraryDownloadsDesc")}
          </p>
        </div>
        {toolbarActions}
      </>
    ) : (
      <>
        {/* 放不放得下一行按搜索框最窄的时候算(basis = min),放得下它再往宽里长。 */}
        <SearchInput className="min-w-[180px] flex-1 basis-[180px]"
            placeholder={searchLabel}
            aria-label={scopeName ? t("modelLibrarySearchIn").replace("{folder}", scopeName).replace("{n}", String(scope.length)) : searchLabel}
            value={query}
            onChange={(event) => setQuery(event.target.value)} />
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
        <LibraryDensitySwitch value={density} onChange={setDensity} />
        <ModelPreviewSettingsButton />
        {toolbarActions}
      </>
    );

  const content = (openItem: (key: string) => void, returnTo: React.RefObject<LibraryReturn | null>) => {
    //: 状态放在内容区(纵向弹性盒)里:加载中撑满剩下的高度、自己居中,出错 / 空用 EmptyState 的 m-auto ——
    //: 弹窗多高都在工具条下面那一整块的正中。
    if (library.isPending) return <LoadingState label={t("modelLibraryLoading")} className="h-auto flex-1" />;
    if (library.isError) {
      return (
        <PageLoadError
          size="section"
          icon={<Unplug />}
          title={t("modelLibraryErrorTitle")}
          error={library.error}
          onRetry={() => void library.refetch()}
          retrying={library.isFetching}
          actions={<ConnectionFailureActions instanceId={instance.id} onCheckSettings={onCheckSettings} />}
        />
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
    const listLabel = t("modelLibraryTitle").replace("{name}", instance.name);
    if (density === "list") {
      return (
        <ModelTable
          label={listLabel}
          instanceId={instance.id}
          models={shown}
          settings={previewSettings}
          onOpen={openItem}
          returnTo={returnTo}
        />
      );
    }
    return (
      <ModelGrid
        label={listLabel}
        instanceId={instance.id}
        models={shown}
        large={density === "large"}
        settings={previewSettings}
        onOpen={openItem}
        returnTo={returnTo}
      />
    );
  };

  return (
    <ModelActionsContext.Provider value={actions}>
    <ActiveFamiliesContext.Provider value={activeFamilies}>
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
      onOpenItem={openDetail}
      onBack={() => setDetailKey(null)}
      detail={
        detail && (
          // 按文件换一份:从工作流库跳过来时详情可能直接从这一个换到那一个,上一个的「看清」「取不到预览图」不能带过去
          <ModelDetail
            key={keyOf(detail)}
            instanceId={instance.id}
            model={detail}
            settings={previewSettings}
            section={detailSection}
            onShowWorkflow={onShowWorkflow}
            onBack={() => setDetailKey(null)}
          />
        )
      }
      dialogs={
        <>
          {seed && library.data && (
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
          )}
          {actionDialogs}
          <ConfirmDialog
            open={filling}
            title={t("modelFillPreviewsTitle")}
            body={[t("modelFillPreviewsBody").replace("{server}", instance.name), fill.isError ? errorText(fill.error) : ""]
              .filter(Boolean).join("\n\n")}
            confirmLabel={t("modelFillPreviewsStart")}
            pending={fill.isPending}
            onCancel={() => {
              fill.reset();
              setFilling(false);
            }}
            onConfirm={() => fill.mutate()}
          />
        </>
      }
    >
      {content}
    </LibraryDialog>
    </ActiveFamiliesContext.Provider>
    </ModelActionsContext.Provider>
  );
}

/**
 * 「为缺预览图的模型补图」:那台服务器上没有预览图的,逐个在 Civitai 上找,按哈希对上的把示例图写回去(先确认)。写不回
 * (没有那条路)、找不了时点不了并说为什么;正在补时转圈。
 */
function FillPreviewsButton({ tools, running, onClick }: { tools: ModelPreviewTools | undefined; running: boolean; onClick: () => void }) {
  const t = useI18n();
  const why = !tools ? t("modelLibraryStillReading") : !tools.save ? tools.save_note || t("modelSavePreviewUnavailable")
    : !tools.lookup ? t("modelLookupUnavailable") : null;
  return (
    <IconButton
      variant="outline"
      size="default"
      className="px-3 text-muted-foreground"
      label={t("modelFillPreviews")}
      hint={t("modelFillPreviewsHint")}
      disabled={Boolean(why)}
      disabledReason={why}
      loading={running}
      onClick={onClick}
    >
      <ImageDown size={13} />
    </IconButton>
  );
}

/** 工具条上的主操作。工具条窄了最后才收字(见 LibraryToolbarLabel);还没读出来时点不了,并说为什么。 */
function DownloadButton({ onClick, disabledReason }: { onClick?: () => void; disabledReason?: string }) {
  const t = useI18n();
  return (
    <IconButton
      variant="default"
      size="default"
      label={t("modelLibraryDownload")}
      disabled={Boolean(disabledReason)}
      disabledReason={disabledReason}
      onClick={onClick}
    >
      <Download size={13} />
      <LibraryToolbarLabel collapse="last">{t("modelLibraryDownload")}</LibraryToolbarLabel>
    </IconButton>
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
  families: FamilyCount[];
  value: string[];
  onChange: (value: string[]) => void;
  nameOf: (family: string) => string;
}) {
  const t = useI18n();
  const chosen = new Set(value);
  //: 常配它的文本编码器也会列出来:数目上写明几个是「常配」,勾了之后多出来的不让人意外
  const tally = (count: number, paired: number) =>
    !paired
      ? String(count)
      : t(count ? "modelLibraryFamilyCountPaired" : "modelLibraryFamilyOnlyPaired").replace("{n}", String(count)).replace("{m}", String(paired));
  //: 勾了几种就写几,不写名字:勾的是哪几种,工具条下面那行筛选里一个个写着;按钮上再写一遍名字,勾一个长名字
  //: (「Wan Video 14B t2v」)就把工具条挤成两行。
  const label = value.length === 0 ? t("modelLibraryFamilyButton") : `${t("modelLibraryFamilyButton")} · ${value.length}`;
  //: 工具条窄了先收这几个字(见 LibraryToolbarLabel),换成筛选图标;勾了哪几种,按钮换成强调色,下面那行筛选里一个个写着。
  const text = (
    <LibraryToolbarLabel collapse="first" icon={<ListFilter size={13} />}>
      <span className="flex min-w-0 items-center gap-2">
        <Truncate>{label}</Truncate>
        <ChevronDown />
      </span>
    </LibraryToolbarLabel>
  );
  if (families.length < 2) {
    return (
      <IconButton
        variant="outline"
        size="default"
        disabled
        label={t("modelLibraryFamilyLabel")}
        hint={t("modelLibraryFamilyHint")}
        disabledReason={t("modelLibraryFamilySingle")}
      >
        {text}
      </IconButton>
    );
  }
  return (
    <Popover>
      <PopoverTrigger asChild>
        <IconButton
          variant="outline"
          size="default"
          label={`${t("modelLibraryFamilyLabel")}${value.length ? ` · ${label}` : ""}`}
          hint={t("modelLibraryFamilyHint")}
          className={cn("max-w-[220px]", value.length > 0 && "border-primary/40 bg-accent text-primary")}
        >
          {text}
        </IconButton>
      </PopoverTrigger>
      <MenuContent label={t("modelLibraryFamilyLabel")} align="end">
        {families.map(([family, count, paired]) => (
          <MenuItem
            key={family}
            role="menuitemcheckbox"
            aria-label={`${nameOf(family)} ${tally(count, paired)}`}
            checked={chosen.has(family)}
            label={nameOf(family)}
            truncate
            hint={tally(count, paired)}
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
              {/* 下载挂了:全应用那一份失败展示(一行档),那一句、原文在「详情」里 */}
              {job.status === "failed" ? (
                <FailureCard size="inline" lines={2} title={t("modelDownloadFailedLabel")}
                             {...failureFields(job, job.message || t("modelDownloadFailedLabel"))} />
              ) : (
                <p className="m-0 min-w-0 break-words text-ui-xs leading-relaxed text-muted-foreground">{job.message}</p>
              )}
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
          <ContextMenu key={keyOf(one)}>
            <ContextMenuTrigger asChild>
          <li data-missing-item={keyOf(one)} className="flex min-w-0 items-center gap-3">
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
            </ContextMenuTrigger>
            {/* 缺的那个文件:下载框带着地址、目录、文件名;也能只复制名字和地址,自己去那台机器上放 */}
            <ContextMenuContent aria-label={t("modelMenuLabel").replace("{name}", one.name)}>
              <ContextMenuItem onSelect={() => onDownload(one)}>
                <MenuItemBody icon={<Download />} label={t("modelMissingMenuDownload")} description={one.folder} />
              </ContextMenuItem>
              <ContextMenuSeparator />
              <ContextMenuItem onSelect={() => void navigator.clipboard?.writeText(one.name)}>
                <MenuItemBody icon={<Copy />} label={t("modelCopyName")} />
              </ContextMenuItem>
              <ContextMenuItem onSelect={() => void navigator.clipboard?.writeText(one.url)}>
                <MenuItemBody icon={<Copy />} label={t("modelMissingCopyLink")} description={one.url} />
              </ContextMenuItem>
            </ContextMenuContent>
          </ContextMenu>
        ))}
      </ul>
    </section>
  );
}

/**
 * 网格一行几张、一行多高。一张卡至少 `min` 宽,一行能放几张放几张(此前 `repeat(auto-fill, minmax(min(100%, Npx), 1fr))`
 * 的同一条规则);列间距、行间距都是 `gap`(`className` 里写的那一份)。卡片 = 3:4 的预览图 + 下面那几行字(连同内边距、
 * 上下边框约 `text` 高)—— 一行真画出来之后按量到的算,这只是还没画时的估计。
 */
const GRID = {
  small: { min: 136, gap: 10, text: 63, className: "gap-x-2.5 pb-2.5" },
  large: { min: 200, gap: 12, text: 96, className: "gap-x-3 pb-3" },
} as const;
/** 列表一行多高(36 的缩略图上下各 6,加一条分隔线);同上,只是还没画时的估计。 */
const TABLE_ROW_PX = 49;
/**
 * 视口上下各多画这么高(useVirtualRows 默认 800)。多画的那几行里的图浏览器也会去要:第一次打开、宿主还没缓存时,每一张
 * 都要那台服务器现转一次(ComfyUI 一次只转一张),多画一行,眼前这几张就多等一行。一行卡片两三百高,400 够滚轮滚一下不露白。
 */
const OVERSCAN_PX = 400;

/** 滚的是 LibraryDialog 的内容区。从网格 / 表格自己的元素往上找:内容区在外层,它的 ref 要等这里的 layout effect 都跑完才挂上。 */
const scrollerOf = (element: HTMLElement | null) => element?.closest<HTMLElement>("[data-library-content]") ?? null;

/**
 * 从详情回到网格 / 表格(见 LibraryDialog 的 `children`):挂上时取走 `returnTo`、滚回进详情前的位置,记下要放回焦点的
 * 那一条。**写在 useVirtualRows 前面**:它在 layout effect 里按此刻的滚动位置开窗,位置得先还原。
 */
function useClaimReturn(
  returnTo: React.RefObject<LibraryReturn | null>,
  scrollRef: React.RefObject<HTMLElement | null>,
  models: ModelFile[],
): React.RefObject<string | null> {
  const pending = React.useRef<string | null>(null);
  React.useLayoutEffect(() => {
    const back = returnTo.current;
    const scroller = scrollRef.current;
    if (!back || !scroller || !models.some((model) => keyOf(model) === back.key)) return;
    returnTo.current = null;
    scroller.scrollTop = back.scrollTop;
    pending.current = back.key;
    // 只在挂上时认领一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return pending;
}

/**
 * 要放回焦点的那一条画出来了:滚进视野(多半已经在了)、放回焦点。还没画出来(行高的估计和上次量到的差得多)就先把
 * 它那一行滚进来,画出来之后的这一次再放。`ready`:一行几张已经按真宽度算过 —— 之前按一列排的位置不作数。
 */
function useFocusReturned(
  pending: React.RefObject<string | null>,
  listRef: React.RefObject<HTMLElement | null>,
  virtual: VirtualRows,
  rowOf: (key: string) => number,
  ready: boolean,
) {
  React.useLayoutEffect(() => {
    const key = pending.current;
    if (!key || !ready) return;
    const item = Array.from(listRef.current?.querySelectorAll<HTMLElement>("[data-library-item]") ?? []).find(
      (one) => one.dataset.libraryItem === key,
    );
    if (item) {
      pending.current = null;
      item.scrollIntoView({ block: "nearest" });
      item.querySelector<HTMLElement>("[data-library-open]")?.focus({ preventScroll: true });
      return;
    }
    const row = rowOf(key);
    if (row < 0) pending.current = null;
    else virtual.reveal(row);
  });
}

/**
 * 卡片网格:**只画看得见的那几行**(上下各留一段缓冲,见 useVirtualRows),其余的用留白占着高度 —— 滚动条说的还是整份
 * 清单。五百多个文件全挂在页面上时,一次换目录、一次悬停都要浏览器过一遍六千多个节点、解几十张原图。一行几张按网格
 * 的宽度算,每行一个键(行首那个文件加一行几张)。卡片记忆化:换目录、搜索、下载进度这些让弹窗重渲的事,已经画着的卡
 * 不跟着重画;悬停、看清(模糊预览图)都是每张卡自己的 CSS。
 */
function ModelGrid({
  label,
  instanceId,
  models,
  large,
  settings,
  onOpen,
  returnTo,
}: {
  label: string;
  instanceId: string;
  models: ModelFile[];
  large: boolean;
  settings: ModelPreviewSettings;
  onOpen: (key: string) => void;
  returnTo: React.RefObject<LibraryReturn | null>;
}) {
  const layout = large ? GRID.large : GRID.small;
  const scrollRef = React.useRef<HTMLElement | null>(null);
  const listRef = React.useRef<HTMLDivElement | null>(null);
  const [listElement, setListElement] = React.useState<HTMLDivElement | null>(null);
  const attachList = React.useCallback((element: HTMLDivElement | null) => {
    listRef.current = element;
    scrollRef.current = scrollerOf(element);
    setListElement(element);
  }, []);
  //: 量到之前(挂上后的头一次渲染)直接读一次 —— 不然先按一列排一遍、开一遍窗,下一次渲染才改对。
  const width = useElementWidth(listElement) || (listElement?.clientWidth ?? 0);
  const columns = Math.max(1, Math.floor((width + layout.gap) / (layout.min + layout.gap)));
  const rows = React.useMemo(() => {
    const out: ModelFile[][] = [];
    for (let at = 0; at < models.length; at += columns) out.push(models.slice(at, at + columns));
    return out;
  }, [models, columns]);
  const rowKeys = React.useMemo(() => rows.map((row) => `${columns}:${keyOf(row[0])}`), [rows, columns]);
  const cardWidth = width > 0 ? (width - layout.gap * (columns - 1)) / columns : layout.min;
  const estimate = Math.round(((cardWidth - 2) * 4) / 3 + layout.text + layout.gap);
  const pending = useClaimReturn(returnTo, scrollRef, models);
  const virtual = useVirtualRows({ keys: rowKeys, scrollRef, listRef, estimate, overscanPx: OVERSCAN_PX });
  const rowOf = (key: string) => {
    const index = models.findIndex((model) => keyOf(model) === key);
    return index < 0 ? -1 : Math.floor(index / columns);
  };
  useFocusReturned(pending, listRef, virtual, rowOf, listElement !== null);
  return (
    <div ref={attachList} role="list" aria-label={label} data-density={large ? "large" : "small"} data-model-grid="">
      {virtual.padTop > 0 && <div aria-hidden="true" data-pad-top="" style={{ height: virtual.padTop }} />}
      {rows.slice(virtual.start, virtual.end).map((row, offset) => {
        const index = virtual.start + offset;
        const key = rowKeys[index];
        return (
          <div
            key={key}
            ref={virtual.measure(key)}
            role="none"
            className={cn("grid", layout.className)}
            style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
          >
            {row.map((model, column) => (
              <div
                key={keyOf(model)}
                role="listitem"
                aria-setsize={models.length}
                aria-posinset={index * columns + column + 1}
                className="grid min-w-0"
              >
                <ModelCard instanceId={instanceId} model={model} large={large} settings={settings} onOpen={onOpen} />
              </div>
            ))}
          </div>
        );
      })}
      <div aria-hidden="true" data-pad-bottom="" style={{ height: virtual.padBottom }} />
    </div>
  );
}

/**
 * 一张卡。预览图一律 3:4(这台机器上的预览图大多是竖的 2:3 / 3:4,统一比例后网格整齐,也不再把竖图裁成一条),
 * 偏上取景(人像的脸在上半截);用的是宿主缩好的缩略图,框先占好位置,图到了淡入。名字一行截断、悬停看全名;底模在左、
 * 大小在右,位置固定 —— 认不出底模时左边空着,大小不跟着挪。大卡片多一行:目录(和子目录)、几张工作流在用。
 * **整张可点**:名字那颗按钮用 `after:` 盖满整张卡。
 */
const ModelCard = React.memo(function ModelCard({
  instanceId,
  model,
  large,
  settings,
  onOpen,
}: {
  instanceId: string;
  model: ModelFile;
  large: boolean;
  settings: ModelPreviewSettings;
  onOpen: (key: string) => void;
}) {
  const t = useI18n();
  const used = model.used_by?.length ?? 0;
  //: 预览是视频的:鼠标移上来、焦点进来时静音循环播(清晰时;模糊、不显示的不播)
  const [playing, setPlaying] = React.useState(false);
  const video = model.preview_kind === "video";
  return (
    <ModelContextMenu model={model}>
      {(openMenu) => (
    <article
      data-library-item={keyOf(model)}
      onPointerEnter={video ? () => setPlaying(true) : undefined}
      onPointerLeave={video ? () => setPlaying(false) : undefined}
      onFocus={video ? () => setPlaying(true) : undefined}
      onBlur={video ? (event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setPlaying(false); } : undefined}
      className={cn(
        "group/thumb relative grid min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_1fr] overflow-hidden rounded-xl border border-border bg-panel transition-colors",
        "hover:border-border-strong hover:bg-panel-subtle",
        "has-[[data-library-open]:focus-visible]:border-primary has-[[data-library-open]:focus-visible]:ring-2 has-[[data-library-open]:focus-visible]:ring-ring",
      )}
    >
      <div data-card-thumb="" className="relative overflow-hidden bg-secondary">
        <ModelThumb
          instanceId={instanceId}
          model={model}
          treatment={previewTreatment(settings, Boolean(model.nsfw?.flagged))}
          play={playing}
          className="aspect-[3/4] w-full object-[50%_20%]"
        />
      </div>
      <span className="absolute left-1.5 top-1.5 flex gap-1">
        <NsfwMark nsfw={model.nsfw} />
        <PreviewOriginMark origin={model.preview_origin} />
      </span>
      <CardMenuButton model={model} onOpenMenu={openMenu} />
      <div className={cn("grid min-w-0 content-start", large ? "gap-1.5 p-2.5" : "gap-1 p-2")}>
        <h3 className={cn("m-0 min-w-0 font-semibold leading-snug text-foreground", large ? "text-ui-sm" : "text-ui-xs")}>
          <button
            type="button"
            data-library-open
            className="block max-w-full cursor-pointer text-left after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none"
            onClick={() => onOpen(keyOf(model))}
            onKeyDown={(event) => {
              if (!isMenuKey(event)) return;
              event.preventDefault();
              openMenu(event.currentTarget);
            }}
          >
            <Truncate hint={large ? undefined : placeOf(model)}>{baseName(model.name)}</Truncate>
          </button>
        </h3>
        <div className="flex h-6 min-w-0 items-center justify-between gap-2">
          <span className="flex min-w-0">
            <FamilyBadge model={model} />
          </span>
          {model.size != null && (
            <span className="shrink-0 text-ui-xs tabular-nums text-muted-foreground">{formatBytes(model.size)}</span>
          )}
        </div>
        {model.encoder && <EncoderPairs encoder={model.encoder} />}
        {large && (
          <div className="flex min-w-0 items-center justify-between gap-2 text-ui-xs text-muted-foreground">
            <Truncate>{placeOf(model)}</Truncate>
            {used > 0 && (
              <Hint label={t("modelUsedCount").replace("{n}", String(used))}>
                <span className="relative z-10 inline-flex shrink-0 items-center gap-1 text-success">
                  <Workflow size={12} aria-hidden />
                  <span className="tabular-nums">{used}</span>
                </span>
              </Hint>
            )}
          </div>
        )}
      </div>
    </article>
      )}
    </ModelContextMenu>
  );
});

/**
 * 卡片右上角的 ⋯:悬停、或焦点在卡片里时出来(触屏上一直在),打开的就是右键那一个菜单(见 ModelMenu)。
 * 叠在名字那颗按钮盖满整张卡的 `after:` 上面。
 */
function CardMenuButton({ model, onOpenMenu, className }: { model: ModelFile; onOpenMenu: (anchor: HTMLElement) => void; className?: string }) {
  const t = useI18n();
  return (
    <IconButton
      variant="secondary"
      size="icon-xs"
      aria-haspopup="menu"
      data-model-menu-button=""
      label={t("modelMenuLabel").replace("{name}", baseName(model.name))}
      className={cn(
        "absolute right-1.5 top-1.5 z-10 opacity-0 shadow-[var(--shadow-floating)] transition-opacity duration-100",
        "group-hover/thumb:opacity-100 group-focus-within/thumb:opacity-100 focus-visible:opacity-100",
        "[@media(hover:none)]:opacity-100",
        className,
      )}
      onClick={(event) => {
        event.stopPropagation();
        onOpenMenu(event.currentTarget);
      }}
    >
      <MoreHorizontal />
    </IconButton>
  );
}

/**
 * 列表:一行一个文件,扫一大批文件时比卡片快。名字是行里那颗按钮(键盘从它进详情);整行也点得开(鼠标方便)。
 * 列宽固定(`table-fixed`),名字在自己那一列里截断,不撑开表格;太窄时横向滚,不挤成一团。和网格一样只画看得见的
 * 那几行,上下用跨满一行的空行撑着高度;行记忆化。
 */
function ModelTable({
  label,
  instanceId,
  models,
  settings,
  onOpen,
  returnTo,
}: {
  label: string;
  instanceId: string;
  models: ModelFile[];
  settings: ModelPreviewSettings;
  onOpen: (key: string) => void;
  returnTo: React.RefObject<LibraryReturn | null>;
}) {
  const t = useI18n();
  const scrollRef = React.useRef<HTMLElement | null>(null);
  const bodyRef = React.useRef<HTMLTableSectionElement | null>(null);
  const attachBody = React.useCallback((element: HTMLTableSectionElement | null) => {
    bodyRef.current = element;
    scrollRef.current = scrollerOf(element);
  }, []);
  const keys = React.useMemo(() => models.map(keyOf), [models]);
  const pending = useClaimReturn(returnTo, scrollRef, models);
  const virtual = useVirtualRows({ keys, scrollRef, listRef: bodyRef, estimate: TABLE_ROW_PX, overscanPx: OVERSCAN_PX });
  useFocusReturned(pending, bodyRef, virtual, (key) => keys.indexOf(key), true);
  //: 表头钉在顶上(滚到几百行时还看得出哪一列是什么),底色不透明(见 LIBRARY_TABLE_HEAD)。
  const head = LIBRARY_TABLE_HEAD;
  return (
    // 不另包一层 overflow-x:那一层会成为表头吸顶的参照,表头就钉不住了。太窄时由内容区自己横向滚。
    <table aria-label={label} className="w-full min-w-[680px] table-fixed border-separate border-spacing-0 text-ui-sm">
      <colgroup>
        <col className="w-[52px]" />
        <col />
        <col className="w-[140px]" />
        <col className="w-[120px]" />
        <col className="w-[84px]" />
        <col className="w-[108px]" />
        <col className="w-[56px]" />
      </colgroup>
      <thead>
        <tr>
          <th scope="col" className={head}>
            <span className="sr-only">{t("modelLibraryColPreview")}</span>
          </th>
          <th scope="col" className={head}>{t("modelFileName")}</th>
          <th scope="col" className={head}>{t("modelFolder")}</th>
          <th scope="col" className={head}>{t("modelFamily")}</th>
          <th scope="col" className={cn(head, "text-right")}>{t("modelSize")}</th>
          <th scope="col" className={head}>{t("modelModified")}</th>
          <th scope="col" className={cn(head, "text-right")}>{t("modelLibraryColUsed")}</th>
        </tr>
      </thead>
      <tbody ref={attachBody}>
        {virtual.padTop > 0 && <TableSpacer height={virtual.padTop} />}
        {models.slice(virtual.start, virtual.end).map((model) => (
          <ModelRow
            key={keyOf(model)}
            rowRef={virtual.measure(keyOf(model))}
            instanceId={instanceId}
            model={model}
            settings={settings}
            onOpen={onOpen}
          />
        ))}
        {virtual.padBottom > 0 && <TableSpacer height={virtual.padBottom} />}
      </tbody>
    </table>
  );
}

/** 表格里没画的那些行占着的高度:一个跨满七列的空行。 */
function TableSpacer({ height }: { height: number }) {
  return (
    <tr aria-hidden="true">
      <td colSpan={7} className="p-0" style={{ height }} />
    </tr>
  );
}

const TABLE_CELL = "border-b border-divider px-2 py-1.5 align-middle";

const ModelRow = React.memo(function ModelRow({
  rowRef,
  instanceId,
  model,
  settings,
  onOpen,
}: {
  rowRef: (element: HTMLElement | null) => void;
  instanceId: string;
  model: ModelFile;
  settings: ModelPreviewSettings;
  onOpen: (key: string) => void;
}) {
  const { locale } = usePreferences();
  const used = model.used_by?.length ?? 0;
  const cell = TABLE_CELL;
  return (
    <ModelContextMenu model={model}>
      {(openMenu) => (
    <tr
      ref={rowRef}
      data-library-item={keyOf(model)}
      onClick={() => onOpen(keyOf(model))}
      className="group/thumb cursor-pointer transition-colors hover:bg-panel-subtle has-[[data-library-open]:focus-visible]:bg-panel-subtle"
    >
      <td className={cell}>
        <span className="block size-9 overflow-hidden rounded-md bg-secondary">
          <ModelThumb
            instanceId={instanceId}
            model={model}
            compact
            treatment={previewTreatment(settings, Boolean(model.nsfw?.flagged))}
            className="size-9 object-[50%_20%]"
          />
        </span>
      </td>
      <td className={cell}>
        <span className="flex min-w-0 items-center gap-1.5">
          <button
            type="button"
            data-library-open
            className="block min-w-0 max-w-full cursor-pointer rounded-sm text-left font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={(event) => {
              event.stopPropagation();
              onOpen(keyOf(model));
            }}
            onKeyDown={(event) => {
              if (!isMenuKey(event)) return;
              event.preventDefault();
              openMenu(event.currentTarget);
            }}
          >
            <Truncate>{baseName(model.name)}</Truncate>
          </button>
          <NsfwMark nsfw={model.nsfw} className="shrink-0" />
          <PreviewOriginMark origin={model.preview_origin} className="shrink-0 shadow-none" />
          <CardMenuButton model={model} onOpenMenu={openMenu} className="static ml-auto shrink-0 shadow-none" />
        </span>
      </td>
      <td className={cn(cell, "text-ui-xs text-muted-foreground")}>
        <Truncate>{placeOf(model)}</Truncate>
      </td>
      <td className={cell}>
        <span className="flex min-w-0">
          <FamilyBadge model={model} pairs />
        </span>
      </td>
      <td className={cn(cell, "text-right text-ui-xs tabular-nums text-muted-foreground")}>
        {model.size != null ? formatBytes(model.size) : ""}
      </td>
      <td className={cn(cell, "text-ui-xs tabular-nums text-muted-foreground")}>
        {model.modified != null ? new Date(model.modified * 1000).toLocaleDateString(locale) : ""}
      </td>
      <td className={cn(cell, "text-right text-ui-xs tabular-nums", used > 0 ? "text-success" : "text-muted-foreground")}>
        {used > 0 ? used : ""}
      </td>
    </tr>
      )}
    </ModelContextMenu>
  );
});

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 gap-0.5">
      <dt className="text-ui-xs text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 break-words text-ui-sm text-foreground">{children}</dd>
    </div>
  );
}

function sourceLabel(t: Translate, resolved: ModelResolved): string {
  if (resolved.source === "huggingface") return t("modelDownloadSourceHuggingface");
  if (resolved.source === "civitai") return t("modelDownloadSourceCivitai");
  if (resolved.source === "modelscope") return t("modelDownloadSourceModelscope");
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
        {seed.name && !seed.url && !resolved && (
          // 工作流缺的模型、又没写下载地址(从工作流库跳过来的):说清楚要找的是哪个文件
          <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">
            {t("modelDownloadWanted").replace("{name}", seed.name).replace("{folder}", seed.folder ?? "")}
          </p>
        )}
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
              /* 走 ComfyUI-Manager 时先说清楚的几件事:令牌会留在那台机器上(只在真要带 Civitai 令牌时说;
                 HuggingFace / ModelScope 的令牌则带不过去)、看不到按字节的进度、开始之后取消停不下那边的下载。 */
              <div
                role="note"
                aria-label={t("modelDownloadManagerCaution")}
                className="grid gap-1.5 rounded-lg border border-warning/40 bg-warning/5 p-3 text-ui-xs leading-relaxed text-foreground"
              >
                <strong className="text-ui-sm">{t("modelDownloadManagerCaution")}</strong>
                <ul className="m-0 grid list-disc gap-1 pl-4">
                  {resolved.source === "civitai" && resolved.uses_token && <li>{t("modelDownloadCivitaiTokenInUrl")}</li>}
                  {resolved.source === "huggingface" && resolved.uses_token && <li>{t("modelDownloadHfTokenUnsupported")}</li>}
                  {resolved.source === "modelscope" && resolved.uses_token && (
                    <li>{t("modelDownloadModelscopeTokenUnsupported")}</li>
                  )}
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
