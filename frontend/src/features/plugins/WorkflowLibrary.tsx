import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  CircleAlert,
  ClipboardCopy,
  Copy,
  ExternalLink,
  EyeOff,
  FileOutput,
  Import,
  Folder,
  FolderInput,
  FolderOpen,
  FolderPen,
  FolderPlus,
  Info,
  LayoutGrid,
  LayoutPanelLeft,
  MoreHorizontal,
  PackagePlus,
  PanelRightOpen,
  PencilLine,
  Plus,
  Puzzle,
  RefreshCcw,
  RotateCcw,
  Search,
  SearchX,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  TriangleAlert,
  Unplug,
  Workflow,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  assetThumbnailUrl,
  copyWorkflow,
  createWorkflowFolder,
  getWorkflowContent,
  getWorkflowLibrary,
  rebootWorkflowServer,
  renameWorkflow,
  renameWorkflowFolder,
  restoreWorkflow,
  startNodeInstall,
  trashWorkflow,
  trashWorkflowFolder,
  type Job,
  type PluginInstance,
  type WorkflowFile,
  type WorkflowNodePack,
  type WorkflowTrashed,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n, usePreferences } from "@/app/preferences";
import { ActionContextMenuItems, ActionMenu, type MenuAction } from "@/components/app/ActionMenu";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import {
  LIBRARY_DENSITIES,
  LIBRARY_TABLE_HEAD,
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
import { previewBlurClass } from "@/components/generation/ModelThumb";
import { previewTreatment, useModelPreviewSettings } from "@/components/generation/modelPreviewSettings";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuTrigger, openContextMenuFromKeyboard } from "@/components/ui/context-menu";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import type { Focused, ModelFocus, WorkflowFocus } from "@/features/plugins/libraryLinks";
import { ConnectionFailureActions } from "@/features/plugins/localServiceStatus";
import { invalidatePluginDependents, refreshConnectionCatalog } from "@/features/plugins/pluginCaches";
import { WorkflowAppEditor, WorkflowAppSection } from "@/features/plugins/WorkflowAppEditor";
import { WorkflowFacts, kindName } from "@/features/plugins/WorkflowFacts";
import { WorkflowOutputs } from "@/features/plugins/WorkflowOutputs";
import {
  FolderDeleteDialog,
  FolderPathDialog,
  MoveWorkflowDialog,
  WORKFLOW_DRAG_TYPE,
  carriesWorkflow,
  dragWorkflow,
} from "@/features/plugins/WorkflowFolders";
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
  baseName,
  filesIn,
  filterWorkflows,
  folderOfView,
  folderTree,
  folderView,
  freeFolderPath,
  freeWorkflowPath,
  inFolder,
  inView,
  joinPath,
  lacksSomething,
  parentOf,
  sortWorkflows,
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
 * 和模型库同一套骨架(LibraryBrowser):左边一列是那台机器上 `workflows/` 里的文件夹树(和 ComfyUI 自己的侧栏同一份,空的也列;
 * 选一个只看它和它下面的),「缺节点或模型」钉在这一列底部;右边顶上搜索、按种类筛、
 * 排序、三档显示方式;一张卡是节点图的缩略预览(照插件给的图摘要画)、名字、种类、节点数、缺什么。点开是详情:能填什么 /
 * 能调什么 / 交出什么、用到的模型、缺的节点和模型、最近的产出、Mosael 里谁在用它;「用它生成」交给 AI 工作台;桌面版「在工作台
 * 里打开」、网页版「在 ComfyUI 里打开」(新标签页)开那台服务器自己的画布(见 workflowEditor),回来时刷新。和模型库互相跳
 * (见 ConnectionLibraries):用到的模型点了停到模型库那一项,缺的点了去模型库下载;从模型库跳过来停到那一张。
 *
 * 工具条上的「新建」在 ComfyUI 自己的画布上开一张新的(桌面版在工作台里,网页版开新标签页,见 workflowEditor;存盘是 ComfyUI
 * 自己的,回来时刷新,新存的那张就出现在列表里);「导入」(或者往库上拖一个文件)导入别处的工作流,见 WorkflowImport。
 *
 * **文件夹**(见 WorkflowFolders):左栏顶上「新建文件夹」;文件夹上右键(或 ⋯、Shift+F10)新建子文件夹、改名、删除(只删空的);
 * 卡片拖到左边的文件夹上就是「移动到…」那个文件夹(先确认)。**右键菜单**:卡片和列表的一行上右键、悬停 / 聚焦时出现的 ⋯、
 * Shift+F10 / 菜单键都打开同一份菜单 —— 打开详情、在工作台里打开(网页版是在 ComfyUI 里打开)、编辑应用表单、复制 / 改名 /
 * 移动 / 导出、复制路径、
 * 去补缺的模型 / 节点、删除;点不了的写着为什么。
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
  //: 正在确认的文件夹改动(新建在哪个文件夹下面、给哪个改名、删哪个)
  const [folderAsk, setFolderAsk] = React.useState<
    { kind: "create"; parent: string } | { kind: "rename"; path: string } | { kind: "delete"; path: string } | null
  >(null);
  //: 正在挪哪一张(「移动到…」,或者拖到了左边哪个文件夹上)
  const [moving, setMoving] = React.useState<{ flow: WorkflowFile; folder?: string } | null>(null);
  //: 拖着一张卡片经过左边的哪一项(高亮它)
  const [dropTarget, setDropTarget] = React.useState<string | null>(null);
  //: 从菜单的「下载缺的模型」「装缺的节点」打开详情时,停到哪一节
  const [detailFocus, setDetailFocus] = React.useState<"models" | "nodes" | null>(null);
  //: 正在编辑哪一张的应用表单(ADR 0038):详情里「编辑应用表单」、卡片菜单里「编辑应用表单…」打开
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
  //: 这里改了工作流(存了精简表单、导入、改名、复制、恢复):模型下拉里它叫什么、能填什么都跟着变。那份目录是后端按这个
  //: 连接存着的,只让界面重问拿到的还是旧的 —— 画板里搜不到刚起的表单标题。所以和从编辑器回来一样,先让目录重拉。
  const changed = () => {
    void qc.invalidateQueries({ queryKey: ["workflow-library", instance.id] });
    void refreshConnectionCatalog(qc, instance.id);
  };
  //: 从编辑器回来:那边可能存了改动、换了模型 —— 先让这个连接的目录重拉,再让工作流库、模型库和生成选项重新问
  //: (工作台关上时它自己也会让目录重拉,见 ComfyWorkbench 的 useCatalogFollowsWorkbench —— 同一时刻的两次并成一次)
  const editorReturned = React.useCallback(() => {
    void refreshConnectionCatalog(qc, instance.id).finally(() => {
      void qc.invalidateQueries({ queryKey: ["workflow-library", instance.id] });
      void qc.invalidateQueries({ queryKey: ["model-library", instance.id] });
    });
  }, [instance.id, qc]);
  const editor = useWorkflowEditor(instance, editorReturned, workspaceId);

  const workflows = React.useMemo(() => library.data?.workflows ?? [], [library.data]);
  const trash = library.data?.trash ?? [];
  const taken = React.useMemo(() => new Set(workflows.map(keyOf)), [workflows]);
  const folders = React.useMemo(() => folderTree(library.data?.folders ?? [], workflows), [library.data, workflows]);
  //: 那台机器上看得见的文件(工作流和别的文件):文件夹里有一个就不能删
  const files = React.useMemo(
    () => [...workflows.map(keyOf), ...(library.data?.others ?? []).map((one) => one.path)],
    [workflows, library.data],
  );
  const problems = workflows.filter(lacksSomething).length;
  const navItems: LibraryNavItem[] = [
    { value: ALL_WORKFLOWS, label: t("workflowLibraryAll"), count: workflows.length, icon: <LayoutGrid /> },
    ...folders.map((one) => ({
      value: folderView(one.path), label: one.name, fullLabel: one.path, depth: one.depth, count: one.count,
      icon: view === folderView(one.path) ? <FolderOpen /> : <Folder />,
    })),
  ];
  const pinned: LibraryNavItem[] = [
    ...(problems > 0
      ? [{ value: PROBLEMS_VIEW, label: t("workflowLibraryProblems"), count: problems, icon: <TriangleAlert />, tone: "warning" as const }]
      : []),
    ...(trash.length > 0 ? [{ value: TRASH_VIEW, label: t("workflowLibraryTrash"), count: trash.length, icon: <Trash2 /> }] : []),
  ];
  const current = [...navItems, ...pinned].some((one) => one.value === view) ? view : ALL_WORKFLOWS;
  //: 选中的文件夹(`""` = 没选文件夹:全部、缺东西的、回收站)
  const selectedFolder = folderOfView(current) ?? "";
  const scope = inView(workflows, current);
  const shown = sortWorkflows(filterWorkflows(scope, { kind, query }), sort);
  const detail = detailKey ? workflows.find((flow) => keyOf(flow) === detailKey) ?? null : null;

  //: 「在工作台里打开」(网页版「在 ComfyUI 里打开」)、「新建」开的是哪里(插件报了编辑器才有)
  const editorTarget = library.data?.editor ?? null;

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
        <Import size={13} />
        {t("workflowImport")}
      </Button>
    </Hint>
  );
  //: 「新建」:在这台 ComfyUI 自己的画布上开一张新的(插件报了编辑器才有)
  const newButton = editorTarget ? (
    <Hint label={t(embeddedWorkbench(editorTarget) ? "workflowNewInWorkbenchHint" : "workflowNewHintTab")}>
      <Button disabled={editor.opening !== null} loading={editor.opening === NEW_NOTE_PATH}
              onClick={() => void editor.create(editorTarget)}>
        <Plus size={13} />
        {t("workflowNew")}
      </Button>
    </Hint>
  ) : null;
  //: 「新建」、卡片菜单里打开一张之后留下的那句话:在列表上就摆在列表上(详情里的那一张摆在详情里)
  const listNote = editor.note && (editor.note.path === NEW_NOTE_PATH || !detailKey)
    ? <EditorNoteLine note={editor.note} onDismiss={editor.dismiss} />
    : null;
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

  //: 搜索框说的是**现在这一页**有几张:选了文件夹就说在哪个文件夹里
  const searchLabel = selectedFolder
    ? t("workflowLibrarySearchIn").replace("{folder}", baseName(selectedFolder)).replace("{n}", String(scope.length))
    : t("workflowLibrarySearch").replace("{n}", String(scope.length));

  // --- 文件夹 -----------------------------------------------------------------------------
  //: 文件夹改了名、删了:选着的是它(或它里面的)就跟过去 / 退回上一级
  const followFolder = (from: string, to: string | null) => {
    if (!selectedFolder || (selectedFolder !== from && !inFolder(selectedFolder, from))) return;
    if (to !== null) setView(folderView(`${to}${selectedFolder.slice(from.length)}`));
    else setView(parentOf(from) ? folderView(parentOf(from)) : ALL_WORKFLOWS);
  };
  const folderActions = (path: string): MenuAction[] => {
    const inside = filesIn(path, files);
    return [
      { label: t("workflowFolderNewInside"), icon: <FolderPlus />, onSelect: () => setFolderAsk({ kind: "create", parent: path }) },
      { label: t("workflowFolderRename"), icon: <FolderPen />, onSelect: () => setFolderAsk({ kind: "rename", path }) },
      {
        label: t("workflowFolderDelete"), icon: <Trash2 />, destructive: true, disabled: inside > 0,
        description: inside > 0 ? t("workflowFolderDeleteNotEmpty").replace("{n}", String(inside)) : undefined,
        onSelect: () => setFolderAsk({ kind: "delete", path }),
      },
    ];
  };
  //: 拖一张卡片到左边「全部」(顶层)或一个文件夹上:松手就是「移动到…」那里(先确认)
  const dropOn = (value: string, folder: string) => ({
    onDragOver: (event: React.DragEvent) => {
      if (!carriesWorkflow(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      setDropTarget(value);
    },
    onDragLeave: (event: React.DragEvent) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropTarget(null);
    },
    onDrop: (event: React.DragEvent) => {
      if (!carriesWorkflow(event)) return;
      event.preventDefault();
      setDropTarget(null);
      const flow = workflows.find((one) => keyOf(one) === event.dataTransfer.getData(WORKFLOW_DRAG_TYPE));
      if (flow && parentOf(flow.path) !== folder) setMoving({ flow, folder });
    },
  });
  const renderNavItem = (item: LibraryNavItem, tab: React.ReactElement) => {
    const folder = folderOfView(item.value);
    if (item.value !== ALL_WORKFLOWS && folder === null) return tab;
    const over = dropTarget === item.value;
    const drop = dropOn(item.value, folder ?? "");
    if (folder === null) {
      return (
        <div role="none" data-drop-target={over || undefined} className={cn("rounded-md", over && "ring-2 ring-primary")} {...drop}>
          {tab}
        </div>
      );
    }
    const actions = folderActions(folder);
    const label = t("workflowFolderActions").replace("{name}", folder);
    return (
      <ContextMenu>
        <div
          role="none"
          data-drop-target={over || undefined}
          className={cn("group/folder relative rounded-md", over && "ring-2 ring-primary")}
          {...drop}
        >
          <ContextMenuTrigger asChild onKeyDown={openContextMenuFromKeyboard}>{tab}</ContextMenuTrigger>
          {/* 悬停 / 聚焦时出现的 ⋯(盖住数量):只有选中的那一项进 Tab 顺序,别的用右键或 Shift+F10 */}
          <span className="absolute right-0.5 top-1/2 -translate-y-1/2 rounded-md bg-secondary opacity-0 transition-opacity focus-within:opacity-100 group-hover/folder:opacity-100 has-[[data-state=open]]:opacity-100">
            <ActionMenu
              label={label}
              actions={actions}
              trigger={
                <IconButton variant="ghost" size="icon-xs" label={label} aria-haspopup="menu" tabIndex={item.value === current ? 0 : -1}>
                  <MoreHorizontal />
                </IconButton>
              }
            />
          </span>
        </div>
        <ContextMenuContent>
          <ActionContextMenuItems actions={actions} />
        </ContextMenuContent>
      </ContextMenu>
    );
  };
  //: 文件夹改名的确认框多说一句:里面几张工作流跟着换路径、Mosael 里在用其中哪几张(换了路径它们跑的时候会说找不到)
  const folderRenameNote = (path: string) => {
    const inside = workflows.filter((flow) => inFolder(flow.path, path));
    if (inside.length === 0) return undefined;
    const used = inside.flatMap((flow) => (flow.used_by ?? []).map((one) => one.name));
    return [
      t("workflowFolderRenameNote").replace("{n}", String(inside.length)),
      used.length > 0 ? `${t("workflowFolderRenameUsedBy")}${[...new Set(used)].join(t("listSeparator"))}` : "",
    ].filter(Boolean).join(" ");
  };
  const newFolder = (
    <Hint label={t("workflowFolderNewHint")}>
      <Button variant="ghost" size="xs" className="text-muted-foreground" onClick={() => setFolderAsk({ kind: "create", parent: selectedFolder })}>
        <FolderPlus size={13} />
        {t("workflowFolderNew")}
      </Button>
    </Hint>
  );

  // --- 一张卡片的菜单(右键、⋯、Shift+F10 是同一份)------------------------------------------
  const exportFlow = (flow: WorkflowFile) => {
    void getWorkflowContent(instance.id, flow.path)
      .then((found) => saveJsonToDisk(`${flow.label}.json`, found.content))
      .catch((error: unknown) => toast.error(errorText(error)));
  };
  const copyPath = (flow: WorkflowFile) => {
    void Promise.resolve()
      .then(() => navigator.clipboard.writeText(flow.path))
      .then(
        () => toast.success(t("workflowPathCopied").replace("{path}", flow.path)),
        () => toast.error(t("workflowPathCopyFailed")),
      );
  };
  //: 改那台机器上这一张的几样、复制路径、删除 —— 详情头上的 ⋯ 也是这几样
  const fileActions = (flow: WorkflowFile): MenuAction[] => [
    { group: "file", label: t("workflowCopy"), icon: <Copy />,
      onSelect: () => setAction({ kind: "copy", path: flow.path, initial: freeWorkflowPath(flow.path, taken) }) },
    { group: "file", label: t("workflowRename"), icon: <PencilLine />,
      onSelect: () => setAction({ kind: "rename", path: flow.path, initial: flow.path }) },
    { group: "file", label: t("workflowMove"), icon: <FolderInput />, onSelect: () => setMoving({ flow }) },
    { group: "file", label: t("workflowExport"), icon: <FileOutput />, description: t("workflowExportDesc"), onSelect: () => exportFlow(flow) },
    { group: "path", label: t("workflowCopyPath"), icon: <ClipboardCopy />, onSelect: () => copyPath(flow) },
    { group: "delete", label: t("workflowDelete"), icon: <Trash2 />, destructive: true, onSelect: () => setAction({ kind: "delete", flow }) },
  ];
  const cardActions = (flow: WorkflowFile, openItem: (key: string) => void): MenuAction[] => {
    const workbench = editorTarget ? embeddedWorkbench(editorTarget) : false;
    const models = flow.missing_models?.length ?? 0;
    const nodes = flow.missing_nodes?.length ?? 0;
    const lacking: MenuAction[] = [
      ...(models > 0
        ? [{ group: "fix", label: t("workflowMenuMissingModels").replace("{n}", String(models)), icon: <Boxes />,
             onSelect: () => { setDetailFocus("models"); openItem(keyOf(flow)); } }]
        : []),
      ...(nodes > 0
        ? [{ group: "fix", label: t("workflowMenuMissingNodes").replace("{n}", String(nodes)), icon: <Puzzle />,
             onSelect: () => { setDetailFocus("nodes"); openItem(keyOf(flow)); } }]
        : []),
    ];
    const file = fileActions(flow);
    return [
      { group: "open", label: t("workflowMenuOpen"), icon: <PanelRightOpen />, onSelect: () => openItem(keyOf(flow)) },
      //: 只有一个:桌面版「在工作台里打开」,网页版「在 ComfyUI 里打开」(新标签页)
      {
        group: "open", label: t(workbench ? "workflowOpenInWorkbench" : "workflowOpenInComfy"),
        icon: workbench ? <LayoutPanelLeft /> : <ExternalLink />, disabled: !editorTarget || editor.opening !== null,
        description: editorTarget ? undefined : t("workflowMenuNoEditor"),
        onSelect: () => { if (editorTarget) void editor.open(editorTarget, flow); },
      },
      {
        group: "app", label: t("workflowMenuEditApp"), icon: <SlidersHorizontal />, disabled: !flow.app,
        description: flow.app ? undefined : t("workflowMenuAppUnavailable"), onSelect: () => setEditingApp(flow),
      },
      ...file.slice(0, -1),
      ...lacking,
      ...file.slice(-1),
    ];
  };

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
          placeholder={searchLabel}
          aria-label={searchLabel}
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
          actions={<ConnectionFailureActions instanceId={instance.id} onCheckSettings={onCheckSettings} />}
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
    const menuOf = (flow: WorkflowFile) => ({
      label: t("workflowActions").replace("{name}", flow.label),
      actions: cardActions(flow, openItem),
    });
    if (density === "list") {
      return (
        <WorkflowTable
          label={listLabel}
          workflows={shown}
          menuOf={menuOf}
          onDragEnd={() => setDropTarget(null)}
          onOpen={(flow) => openItem(keyOf(flow))}
        />
      );
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
            <WorkflowCard
              flow={flow}
              large={density === "large"}
              menu={menuOf(flow)}
              onDragEnd={() => setDropTarget(null)}
              onOpen={() => openItem(keyOf(flow))}
            />
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
      nav={
        library.data
          ? { label: t("workflowLibraryFolders"), value: current, onChange: setView, items: navItems, pinned, action: newFolder,
              renderItem: renderNavItem }
          : undefined
      }
      toolbar={toolbar}
      dropzone={
        library.data
          ? {
              handlers: drop.handlers,
              overlay: drop.active ? (
                <div className="pointer-events-none absolute inset-0 z-20 grid place-items-center rounded-[inherit] bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
                  <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
                    <Import size={20} />
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
            {listNote}
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
            onOpen={(where) => void editor.open(where, detail)}
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
            outputs={detail.last_output && workspaceId
              ? <WorkflowOutputs instanceId={instance.id} workspaceId={workspaceId} path={detail.path} label={detail.label} />
              : null}
            onBack={() => setDetailKey(null)}
            actions={fileActions(detail)}
            focusSection={detailFocus === "models" ? t("workflowMissingModels") : detailFocus === "nodes" ? t("workflowMissingNodes") : null}
            onFocused={() => setDetailFocus(null)}
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
                //: 在详情里改的停到改完的那一张;在列表上(右键菜单)改的留在列表上
                if (action.kind !== "restore" && detailKey) setDetailKey(done.path);
              }}
            />
          )}
          {moving && (
            <MoveWorkflowDialog
              path={moving.flow.path}
              label={moving.flow.label}
              folders={folders}
              initialFolder={moving.folder}
              where={t("workflowWriteWhere").replace("{server}", instance.name)}
              usedBy={(moving.flow.used_by ?? []).map((one) => one.name)}
              onClose={() => setMoving(null)}
              onSubmit={async (path) => {
                try {
                  const done = await renameWorkflow(instance.id, moving.flow.path, path);
                  if (detailKey === moving.flow.path) setDetailKey(done.path);
                } finally {
                  //: 成了要重新列;没成(那张已经不在了、目标被占了)也重新列 —— 手里这份列表旧了
                  changed();
                }
              }}
            />
          )}
          {folderAsk?.kind === "create" && (
            <FolderPathDialog
              title={t("workflowFolderNewTitle")}
              confirmLabel={t("workflowFolderNewConfirm")}
              where={t("workflowFolderWhere").replace("{server}", instance.name)}
              initial={freeFolderPath(joinPath(folderAsk.parent, t("workflowFolderDefaultName")), folders.map((one) => one.path))}
              onClose={() => setFolderAsk(null)}
              onSubmit={async (path) => {
                const done = await createWorkflowFolder(instance.id, path);
                void qc.invalidateQueries({ queryKey: ["workflow-library", instance.id] });
                setView(folderView(done.path));
              }}
            />
          )}
          {folderAsk?.kind === "rename" && (
            <FolderPathDialog
              title={t("workflowFolderRenameTitle").replace("{name}", folderAsk.path)}
              confirmLabel={t("workflowFolderRenameConfirm")}
              where={t("workflowFolderWhere").replace("{server}", instance.name)}
              note={folderRenameNote(folderAsk.path)}
              initial={folderAsk.path}
              onClose={() => setFolderAsk(null)}
              onSubmit={async (path) => {
                if (path === folderAsk.path) return;
                try {
                  const done = await renameWorkflowFolder(instance.id, folderAsk.path, path);
                  followFolder(folderAsk.path, done.path);
                } finally {
                  changed();
                }
              }}
            />
          )}
          {folderAsk?.kind === "delete" && (
            <FolderDeleteDialog
              path={folderAsk.path}
              server={instance.name}
              subfolders={folders.filter((one) => inFolder(one.path, folderAsk.path)).length}
              onClose={() => setFolderAsk(null)}
              onConfirm={async () => {
                try {
                  await trashWorkflowFolder(instance.id, folderAsk.path);
                  followFolder(folderAsk.path, null);
                } finally {
                  changed();
                }
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
 * 大卡片上「最近的那一份产出」那一枚小图:和详情里那一组同一套 NSFW 规矩(modelPreviewSettings)—— 判成 NSFW 的按设置模糊
 * (悬停卡片看清)或只剩一枚「已隐藏」的眼睛。
 */
function CardOutputThumb({ output }: { output: NonNullable<WorkflowFile["last_output"]> }) {
  const t = useI18n();
  const [settings] = useModelPreviewSettings();
  const treatment = previewTreatment(settings, Boolean(output.nsfw?.flagged));
  if (treatment === "hidden") {
    return (
      <span data-hidden-preview="" aria-label={t("modelPreviewHidden")}
            className="grid size-8 shrink-0 place-items-center rounded-md bg-[color-mix(in_srgb,var(--primary)_8%,var(--panel))] text-muted-foreground">
        <EyeOff size={12} aria-hidden />
      </span>
    );
  }
  return (
    <span className="group/thumb size-8 shrink-0 overflow-hidden rounded-md bg-secondary" data-treatment={treatment}>
      <img src={assetThumbnailUrl(output.asset_id)} alt="" loading="lazy" draggable={false}
           className={cn("size-full object-cover", previewBlurClass(treatment))} />
    </span>
  );
}

/** 一张卡片 / 一行的菜单:右键、⋯、Shift+F10 打开的是同一份(见 WorkflowLibraryDialog 的 cardActions)。 */
type CardMenu = { label: string; actions: MenuAction[] };

/** 悬停 / 聚焦时出现的 ⋯。点它不冒泡到卡片 / 那一行(列表的一行整行可点)。 */
function CardMenuButton({ menu, className }: { menu: CardMenu; className?: string }) {
  return (
    <span
      className={cn(
        "opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100 has-[[data-state=open]]:opacity-100",
        className,
      )}
      onClick={(event) => event.stopPropagation()}
    >
      <ActionMenu label={menu.label} actions={menu.actions} />
    </span>
  );
}

/** 这张工作流上那张表单的标题(ADR 0045:表单是它的一个入口)。没有表单、表单没起标题是空串。 */
function formTitle(flow: WorkflowFile): string {
  return flow.app?.status === "ok" && flow.app.app ? (flow.app.title ?? "").trim() : "";
}

/** 名字下面一行淡色小字「表单:快速用krea2生图」—— AI Studio、画板里看到的表单名,在库里找得到是哪张工作流。 */
function FormTitleLine({ flow }: { flow: WorkflowFile }) {
  const t = useI18n();
  const title = formTitle(flow);
  if (!title) return null;
  return (
    <span data-workflow-form-title="" className="block min-w-0 text-ui-2xs text-muted-foreground">
      <Truncate>{t("workflowFormTitleLine").replace("{title}", title)}</Truncate>
    </span>
  );
}

/**
 * 一张卡:节点图缩略预览(4:3,整张图塞进去不裁)、名字(一行截断,悬停看全路径)、种类在左、节点数在右;缺东西的再一行。
 * 大卡片多一行:最近一次的产出、Mosael 里几处在用。**整张可点**:名字那颗按钮用 `after:` 盖满整张卡。
 *
 * 右键、右上角悬停出现的 ⋯、在卡片上按 Shift+F10 / 菜单键,开的是同一份菜单;整张卡能拖,拖到左边的文件夹上就是移过去。
 */
function WorkflowCard({ flow, large, menu, onOpen, onDragEnd }: {
  flow: WorkflowFile;
  large: boolean;
  menu: CardMenu;
  onOpen: () => void;
  onDragEnd: () => void;
}) {
  const t = useI18n();
  const used = flow.used_by?.length ?? 0;
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild onKeyDown={openContextMenuFromKeyboard}>
    <article
      data-library-item={keyOf(flow)}
      draggable
      onDragStart={(event) => dragWorkflow(event, keyOf(flow))}
      onDragEnd={onDragEnd}
      className={cn(
        "group relative grid min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_1fr] overflow-hidden rounded-xl border border-border bg-panel transition-colors",
        "hover:border-border-strong hover:bg-panel-subtle data-[state=open]:border-primary",
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
        <FormTitleLine flow={flow} />
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
              <CardOutputThumb output={flow.last_output} />
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
      <CardMenuButton menu={menu} className="absolute right-2 top-2 z-10 rounded-lg bg-panel" />
    </article>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ActionContextMenuItems actions={menu.actions} />
      </ContextMenuContent>
    </ContextMenu>
  );
}

/**
 * 列表:一行一张,扫一大批工作流时比卡片快。名字是行里那颗按钮;整行也点得开。一行和一张卡片同一份菜单(右键、行尾悬停出现
 * 的 ⋯、Shift+F10),也能拖到左边的文件夹上。
 *
 * 维护者:「这个弹窗列表模式下似乎UI有点问题」——
 * - 表头钉在顶上、**不透明**(LIBRARY_TABLE_HEAD):滚上去的那一行不再透过表头;
 * - **每行一样高**(WORKFLOW_ROW_HEIGHT):缺东西的只摆一枚「缺 4 种节点 · 3 个模型」,缺的是哪几样在悬停里;此前两枚叠成两行,
 *   那几行高出一截;
 * - 种类一律灰字:此前转不过来的那几行是橙色,和「缺什么」那一列说的是同一件事。转不过来、又不是缺东西的(别的原因),
 *   「缺什么」那一列摆一枚「转不过来」,原因在悬停里;
 * - 全在根目录时不摆「目录」那一列(一整列空着);窄的时候先收掉「目录」「节点」「改动时间」,名字那一列留着。
 */
function WorkflowTable({ label, workflows, menuOf, onOpen, onDragEnd }: {
  label: string;
  workflows: WorkflowFile[];
  menuOf: (flow: WorkflowFile) => CardMenu;
  onOpen: (flow: WorkflowFile) => void;
  onDragEnd: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const head = LIBRARY_TABLE_HEAD;
  const cell = cn("border-b border-divider px-2 py-1.5 align-middle", WORKFLOW_ROW_HEIGHT);
  //: 全在根目录:没有可看的目录,这一列不摆
  const folders = workflows.some((flow) => flow.folder);
  //: 窄的时候先收掉的几列(名字、种类、缺什么、在用留着)
  const wide = "max-lg:hidden";
  return (
    <table aria-label={label} className="w-full min-w-[560px] table-fixed border-separate border-spacing-0 text-ui-sm">
      <thead>
        <tr>
          <th scope="col" className={cn(head, "w-[76px]")}>
            <span className="sr-only">{t("workflowLibraryColPreview")}</span>
          </th>
          <th scope="col" className={head}>{t("workflowLibraryColName")}</th>
          {folders && <th scope="col" data-col="folder" className={cn(head, "w-[120px]", wide)}>{t("workflowLibraryColFolder")}</th>}
          <th scope="col" className={cn(head, "w-[80px]")}>{t("workflowLibraryKind")}</th>
          <th scope="col" className={cn(head, "w-[64px] text-right", wide)}>{t("workflowLibraryColNodes")}</th>
          <th scope="col" className={cn(head, "w-[108px]", wide)}>{t("modelModified")}</th>
          <th scope="col" className={cn(head, "w-[176px]")}>{t("workflowLibraryColMissing")}</th>
          <th scope="col" className={cn(head, "w-[56px] text-right")}>{t("modelLibraryColUsed")}</th>
          <th scope="col" className={cn(head, "w-[44px]")}>
            <span className="sr-only">{t("workflowLibraryColActions")}</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {workflows.map((flow) => {
          const used = flow.used_by?.length ?? 0;
          const menu = menuOf(flow);
          return (
            <ContextMenu key={keyOf(flow)}>
              <ContextMenuTrigger asChild onKeyDown={openContextMenuFromKeyboard}>
            <tr
              data-library-item={keyOf(flow)}
              draggable
              onDragStart={(event) => dragWorkflow(event, keyOf(flow))}
              onDragEnd={onDragEnd}
              onClick={() => onOpen(flow)}
              className="group cursor-pointer transition-colors hover:bg-panel-subtle has-[[data-library-open]:focus-visible]:bg-panel-subtle data-[state=open]:bg-panel-subtle"
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
                  <Truncate hint={flow.path !== `${flow.label}.json` ? flow.path : undefined}>{flow.label}</Truncate>
                </button>
                <FormTitleLine flow={flow} />
              </td>
              {folders && (
                <td className={cn(cell, "text-ui-xs text-muted-foreground", wide)}>
                  <Truncate>{flow.folder}</Truncate>
                </td>
              )}
              <td data-col="kind" className={cn(cell, "text-ui-xs text-muted-foreground")}>{kindName(t, flow.kind)}</td>
              <td className={cn(cell, "text-right text-ui-xs tabular-nums text-muted-foreground", wide)}>{flow.node_count}</td>
              <td className={cn(cell, "text-ui-xs tabular-nums text-muted-foreground", wide)}>
                {flow.modified != null ? new Date(flow.modified * 1000).toLocaleDateString(locale) : ""}
              </td>
              <td className={cell}>
                <LackChip flow={flow} />
              </td>
              <td className={cn(cell, "text-right text-ui-xs tabular-nums", used > 0 ? "text-success" : "text-muted-foreground")}>
                {used > 0 ? used : ""}
              </td>
              <td className={cn(cell, "text-right")}>
                <CardMenuButton menu={menu} />
              </td>
            </tr>
              </ContextMenuTrigger>
              <ContextMenuContent>
                <ActionContextMenuItems actions={menu.actions} />
              </ContextMenuContent>
            </ContextMenu>
          );
        })}
      </tbody>
    </table>
  );
}

/** 列表的一行多高:预览(40px)上下各留 6px。缺东西、名字长短都不改它。 */
const WORKFLOW_ROW_HEIGHT = "h-[53px]";

/**
 * 列表「缺什么」那一格:**只摆一枚**(「缺 4 种节点 · 3 个模型」「缺 2 种节点」),缺的是哪几样在悬停里 —— 两枚叠成两行
 * 会把那一行撑高。不缺东西、却转不过来的(别的原因)摆一枚「转不过来」,原因在悬停里。
 */
function LackChip({ flow }: { flow: WorkflowFile }) {
  const t = useI18n();
  const nodes = flow.missing_nodes ?? [];
  const models = flow.missing_models ?? [];
  const text =
    nodes.length && models.length
      ? t("workflowLibraryMissingBoth").replace("{nodes}", String(nodes.length)).replace("{models}", String(models.length))
      : nodes.length
        ? t("workflowLibraryMissingNodes").replace("{n}", String(nodes.length))
        : models.length
          ? t("workflowLibraryMissingModels").replace("{n}", String(models.length))
          : "";
  const detail = [...nodes.map((one) => one.type), ...models.map((one) => one.name)].join(" · ");
  if (!text && !flow.problem) return null;
  return (
    <Hint label={text || t("workflowLibraryBroken")} hint={(text ? detail : flow.problem) || undefined}>
      <span data-lack-chip="" tabIndex={-1} className="inline-flex max-w-full">
        <CatalogBadge tone="warning" icon={text ? <CircleAlert /> : <TriangleAlert />}>
          <Truncate>{text || t("workflowLibraryBroken")}</Truncate>
        </CatalogBadge>
      </span>
    </Hint>
  );
}

/** 打开一张 /「新建」之后留下的那句话:没打开成那一张、开了新标签页要自己点开、这版前端不能新建、或者出了错。 */
function EditorNoteLine({ note, onDismiss }: { note: EditorNote; onDismiss: () => void }) {
  const t = useI18n();
  const created = note.path === NEW_NOTE_PATH;
  const keys: Record<Exclude<EditorNote["kind"], "error">, Parameters<typeof t>[0]> = {
    missing: "workflowEditorMissing",
    tab: "workflowEditorTab",
    notReady: created ? "workflowNewNotReady" : "workflowEditorNotReady",
    unsupported: "workflowNewUnsupported",
    newTab: "workflowNewTab",
    starting: "localServiceStartingNote",
  };
  const text =
    note.kind === "error"
      ? note.message || t(created ? "workflowNewFailed" : "workflowWorkbenchFailed")
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
  onOpen,
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
  outputs,
  onBack,
  actions,
  focusSection,
  onFocused,
}: {
  flow: WorkflowFile;
  editor: WorkflowEditor | null;
  /** 正在开哪一张(新建是 `NEW_NOTE_PATH`);`null` 是没在开 */
  opening: string | null;
  note: EditorNote | null;
  /** 桌面版在工作台里打开(ADR 0038),网页版在新标签页里打开那台 ComfyUI */
  onOpen: (editor: WorkflowEditor) => void;
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
  /** 「最近的产出」那一组(见 WorkflowOutputs);没有产出时不给 */
  outputs: React.ReactNode;
  onBack: () => void;
  /** 头上 ⋯ 里的几样:复制、改名、移动、导出、复制路径、删除(和卡片菜单里的同一份)。 */
  actions: MenuAction[];
  /** 从卡片菜单的「下载缺的模型」「装缺的节点」进来:停到这一节(节的标题)。 */
  focusSection: string | null;
  onFocused: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const generation = flow.generation;

  //: 停到那一节:滚过去,焦点给它的标题(读屏从这一节读起)
  React.useEffect(() => {
    if (!focusSection) return;
    const frame = window.requestAnimationFrame(() => {
      const section = Array.from(document.querySelectorAll<HTMLElement>("section[aria-label]"))
        .find((one) => one.getAttribute("aria-label") === focusSection);
      section?.scrollIntoView({ block: "start" });
      section?.querySelector<HTMLElement>("h4")?.focus({ preventScroll: true });
      onFocused();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [focusSection, onFocused]);

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
          {formTitle(flow) && <span data-workflow-form-title="">{t("workflowFormTitleLine").replace("{title}", formTitle(flow))}</span>}
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
        {editor && (embeddedWorkbench(editor) ? (
          <Hint label={t("workflowOpenInWorkbenchHint")}>
            <Button variant="outline" disabled={opening !== null} loading={opening === flow.path} onClick={() => onOpen(editor)}>
              <LayoutPanelLeft size={13} />
              {t("workflowOpenInWorkbench")}
            </Button>
          </Hint>
        ) : (
          <Hint label={t("workflowOpenInComfyHint")}>
            <Button variant="outline" disabled={opening !== null} onClick={() => onOpen(editor)}>
              <ExternalLink size={13} />
              {t("workflowOpenInComfy")}
            </Button>
          </Hint>
        ))}
        {/* 改那台机器上的文件:每一样都先弹确认(见 WorkflowPathDialog / MoveWorkflowDialog / ConfirmDialog);导出只是下载到本机 */}
        <ActionMenu
          label={t("workflowMore")}
          actions={actions}
          trigger={
            <IconButton variant="outline" size="default" className="px-3 text-muted-foreground" label={t("workflowMore")} aria-haspopup="menu">
              <MoreHorizontal size={14} />
            </IconButton>
          }
        />
        </>
      }
      media={media}
    >
      {note && <EditorNoteLine note={note} onDismiss={onDismissNote} />}
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
            //: 和「缺的模型」的「下载」同一个尺寸(xs、带图标),放在行尾那一格里(见 WorkflowFacts 的 FactLine)
            <Button variant="outline" size="xs"
                    aria-label={t("workflowInstallPackLabel").replace("{name}", pack.title)} onClick={() => onInstall(pack)}>
              <PackagePlus size={12} />
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
      {outputs}
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
