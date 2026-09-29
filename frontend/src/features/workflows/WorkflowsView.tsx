import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, FileUp, ListChecks, Pencil, Play, Plus, Store, Trash2, Workflow as WorkflowIcon, X } from "lucide-react";
import { toast } from "sonner";

import {
  createWorkflow,
  deleteWorkflow,
  exportWorkflowFile,
  fetchWorkflowNodeTypes,
  importWorkflow,
  listWorkflows,
  runWorkflow,
  updateWorkflow,
  type Workflow,
  type WorkflowGraph,
  type WorkflowTemplateId,
  type Workspace,
} from "@/api/client";
import { usePreferences } from "@/app/preferences";
import { ActionContextMenuItems, ActionMenu, type MenuAction } from "@/components/app/ActionMenu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { CanvasCardSkeleton } from "@/components/layout/CanvasCardSkeleton";
import { CanvasDetailLoading } from "@/components/layout/CanvasDetailLoading";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { CARD_GRID, PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from "@/components/ui/context-menu";
import { useWorkflowTemplates, WorkflowCommunityDialog } from "@/features/workflows/WorkflowCommunityDialog";
import { WorkflowCard } from "@/features/workflows/WorkflowCard";
import { WorkflowEditor } from "@/features/workflows/WorkflowEditor";
import { analyzeWorkflowNow } from "@/features/workflows/readiness";
import { refreshAfterWorkflowDelete } from "@/features/workflows/workflowViewShared";
import { OPEN_WORKFLOW_TEMPLATE, useOpenRequest, useSectionEntry } from "@/lib/deepLink";
import { saveJsonToDisk } from "@/lib/download";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { usePersistentSelection } from "@/lib/usePersistentTab";

//: 工作流页 = 列表页 + 详情页(编辑器)。编辑器在 WorkflowEditor,节点检查器在 NodeInspector;
//: 检查器仍从这里导出一份,老的引用路径照旧能用。
export { NodeInspector } from "@/features/workflows/NodeInspector";

export function WorkflowsView({ workspace }: { workspace: Workspace }) {
  const { t } = usePreferences();
  const qc = useQueryClient();
  const [menuRenaming, setMenuRenaming] = React.useState<Workflow | null>(null);
  const [menuDeleting, setMenuDeleting] = React.useState<Workflow | null>(null);
  const [communityOpen, setCommunityOpen] = React.useState(false);
  const [communityFocus, setCommunityFocus] = React.useState<string | null>(null);
  //: 官网「在 Mosael 中打开」:打开工作流社区、选中那个模板 —— 添加副本仍由人点。
  useOpenRequest(OPEN_WORKFLOW_TEMPLATE, (templateId) => {
    setCommunityFocus(templateId);
    setCommunityOpen(true);
  });

  // 通知/任务中心深链(mosael:open-* 事件通道):直接选中对应工作流。
  useOpenRequest("mosael:open-workflow", (id) => setSelectedId(id));

  const workflows = useQuery({
    queryKey: ["workflows", workspace.id],
    queryFn: () => listWorkflows(workspace.id),
    // 智能体经确认卡改图后 updated_at 变化,轮询让画布自动跟进。
    refetchInterval: 5000,
  });
  const nodeTypes = useQuery({
    // 节点名、字段名和输出接点名都由后端按 Accept-Language 翻译,所以换了语言这份得重取。
    // 那件事由 PreferencesProvider 统一做(切语言时作废全部查询)—— 此前这里是把 locale 拼进
    // key 自己解决的,但那要求**每个**取后端翻译内容的地方都记得带上它,漏一处就错一处,
    // 而漏的那处不报错(插件详情就是这么漏的)。一种机制,一处说明。
    queryKey: ["workflow-node-types"],
    queryFn: fetchWorkflowNodeTypes,
    staleTime: Infinity,
  });

  const templates = useWorkflowTemplates();
  const create = useMutation({
    mutationFn: (templateId?: WorkflowTemplateId) => {
      if (!templateId) {
        return createWorkflow({ workspace_id: workspace.id, name: t("wfDefaultName"), description: "" });
      }
      // 名称和描述从**后端的模板目录**取(和社区对话框同一份)。此前是前端一张表,而它和
      // 官网、后端各写各的 —— 同一个模板在三处讲三种话。
      const text = templates.data?.find((one) => one.id === templateId);
      return createWorkflow({
        workspace_id: workspace.id,
        name: text?.name ?? t("wfDefaultName"),
        description: text?.description ?? "",
        template_id: templateId,
      });
    },
    onSuccess: (workflow, templateId) => {
      if (templateId) {
        setCommunityOpen(false);
        toast.success(t("wfCommunityAdded").replace("{name}", workflow.name));
      }
      setSelectedId(workflow.id);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
    onError: (error: Error) => toast.error(t("wfCreateFailed"), { description: error.message }),
  });

  const menuRename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => updateWorkflow(id, { name }),
    onSuccess: () => {
      setMenuRenaming(null);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
  });
  const menuRemove = useMutation({
    mutationFn: (id: string) => deleteWorkflow(id),
    onSuccess: () => {
      setMenuDeleting(null);
      refreshAfterWorkflowDelete(qc, workspace.id);
    },
  });
  // 导出:取后端信封(格式/版本权威在后端)→ 落成 .mosael-workflow.json 文件。
  const menuExport = useMutation({
    mutationFn: async (workflow: Workflow) => {
      const envelope = await exportWorkflowFile(workflow.id);
      saveJsonToDisk(`${workflow.name}.mosael-workflow.json`, envelope);
    },
    onError: (error: Error) => toast.error(t("wfExportFailed"), { description: error.message }),
  });
  // 导入:读文件 → JSON 解析(坏文件在本地就报)→ 后端校验落库 → 选中新工作流。
  const importInputRef = React.useRef<HTMLInputElement | null>(null);
  const importFile = useMutation({
    mutationFn: async (file: File) => {
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(await file.text()) as Record<string, unknown>;
      } catch {
        throw new Error(t("wfImportInvalid"));
      }
      return importWorkflow({ workspace_id: workspace.id, data });
    },
    onSuccess: (workflow) => {
      toast.success(t("wfImported").replace("{name}", workflow.name));
      setSelectedId(workflow.id);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
    onError: (error: Error) => toast.error(t("wfImportFailed"), { description: error.message }),
  });
  /**
   * 卡片上的「运行」。和编辑器的运行键**同一个判据**(readiness):有阻断问题就不发请求,说清卡在哪、
   * 给一个去编辑器看的出口。此前这里直接调接口 —— 同一张图在编辑器里运行键是灰的,在列表上却能排进
   * 队列,跑到缺东西的那一步才失败。列表里本来就带着图(卡片数节点用的就是它),判一次的代价是
   * 取齐两份清单,和编辑器共用缓存。
   */
  const menuRun = useMutation({
    mutationFn: async (workflow: Workflow) => {
      const types = await qc.ensureQueryData({ queryKey: ["workflow-node-types"], queryFn: fetchWorkflowNodeTypes });
      const registry = new Map(types.map((item) => [item.type, item]));
      const analysis = await analyzeWorkflowNow(qc, workflow.graph as unknown as WorkflowGraph, registry);
      if (!analysis.runnable) return { blocked: analysis.errorCount };
      return { job: await runWorkflow(workflow.id) };
    },
    onSuccess: (result, workflow) => {
      if ("blocked" in result) {
        toast.error(t("wfRunBlockedInList").replace("{name}", workflow.name).replace("{n}", String(result.blocked)), {
          action: { label: t("wfOpenEditorToFix"), onClick: () => setSelectedId(workflow.id) },
        });
        return;
      }
      toast.success(t("wfRunQueued"));
      // Without this the history panel, if already open with nothing in flight, never polls
      // and never refetches — the run appears only after navigating away and back.
      void qc.invalidateQueries({ queryKey: ["workflow-runs", workflow.id] });
    },
    onError: (error: Error) => toast.error(t("wfRunFailed"), { description: error.message }),
  });
  // 卡片的 ⋯ 和(没在多选时的)右键菜单同一份清单(见 ActionContextMenuItems)。
  const cardActions = (workflow: Workflow): MenuAction[] => [
    { label: t("wfRun"), icon: <Play />, disabled: menuRun.isPending, onSelect: () => menuRun.mutate(workflow) },
    { label: t("rename"), icon: <Pencil />, onSelect: () => setMenuRenaming(workflow) },
    { label: t("wfExport"), icon: <Download />, disabled: menuExport.isPending, onSelect: () => menuExport.mutate(workflow) },
    { label: t("delete"), icon: <Trash2 />, destructive: true, onSelect: () => setMenuDeleting(workflow) },
  ];

  // 列表页 / 详情页两态:**没选中就是列表**。
  //
  // 用 usePersistentSelection 而不是普通 state:页面是条件挂载的(切走整棵卸载),纯 state
  // 会让"进了详情、去别的页面看一眼、回来"变成回到列表 —— 用户报过。
  //
  // 之前我为了去掉"回落到第一条"把这个 hook 一起换掉了,那是看错了地方:回落写在下面那句
  // `?? list[0]` 里,hook 本身返回 null 就是 null(存的是空 = 列表页),正是这里要的。
  const [selectedId, setSelectedId, selectedWorkflowState] = usePersistentSelection(
    "workflows",
    workflows.data?.map((workflow) => workflow.id),
  );
  // 「从起点进来」(统计页的工作流数字等):回到列表,不恢复上次开着的那条。等着投递的那一帧
  // 就按列表画 —— 否则会先把整张画布挂上再卸掉(见 lib/deepLink 的 useSectionEntry)。
  const enteringRoot = useSectionEntry("workflows", () => setSelectedId(null)) !== null;
  const selected = enteringRoot ? null : (workflows.data ?? []).find((w) => w.id === selectedId) ?? null;
  // 多选与素材页同一份状态机(见 lib/useMultiSelect)。
  const { selectMode, enter: enterSelectMode, selectedIds, toggle, selectAll, allSelected, clear, exit, menuTargets } =
    useMultiSelect(workflows.data ?? [], (workflow) => workflow.id);
  const [batchDeleting, setBatchDeleting] = React.useState(false);
  /** 右键菜单:右键的那张在选区里(且不止它一张)就作用于整个选区,只给能对一批做的动作 —— 和工具条上
   *  的批量删除是同一件事;否则是这一张自己的菜单(见 useMultiSelect.menuTargets)。 */
  const contextActions = (workflow: Workflow): MenuAction[] => {
    const targets = menuTargets(workflow.id);
    if (targets.length <= 1) return cardActions(workflow);
    return [
      {
        label: t("deleteSelectedN").replace("{n}", String(targets.length)),
        icon: <Trash2 />,
        destructive: true,
        onSelect: () => setBatchDeleting(true),
      },
    ];
  };
  const batchRemove = useMutation({
    mutationFn: async () => {
      // 没有批量接口:逐条删,失败的报出去(和素材页同一种做法)。
      const failures: string[] = [];
      for (const id of selectedIds) {
        try {
          await deleteWorkflow(id);
        } catch (error) {
          failures.push(String((error as Error).message));
        }
      }
      return failures;
    },
    onSuccess: (failures) => {
      setBatchDeleting(false);
      clear();
      if (failures.length > 0) toast.error(failures.join("\n"));
      refreshAfterWorkflowDelete(qc, workspace.id);
    },
  });

  const restoringSelectedWorkflow =
    (!enteringRoot && selectedWorkflowState.restoring && workflows.isPending) ||
    (selected !== null && nodeTypes.isPending);

  if (restoringSelectedWorkflow) {
    return <CanvasDetailLoading testId="workflows-detail-restoring" />;
  }

  const communityDialog = (
    <WorkflowCommunityDialog
      open={communityOpen}
      workspaceId={workspace.id}
      workflows={workflows.data ?? []}
      installingId={create.isPending ? (create.variables ?? null) : null}
      focusTemplate={communityFocus}
      onOpenChange={(next) => {
        setCommunityOpen(next);
        if (!next) setCommunityFocus(null);
      }}
      onInstall={(templateId) => create.mutate(templateId)}
    />
  );

  if (workflows.isSuccess && (workflows.data ?? []).length === 0) {
    return (
      <div className={STUDIO_PAGE}>
        <PageHeading title={t("navWorkflows")} description={t("studioWorkflowsDesc")} />
        <EmptyState
          icon={<WorkflowIcon size={22} />}
          title={t("wfEmptyTitle")}
          body={t("wfEmptyBody")}
          action={
            <span className="inline-flex flex-wrap items-center justify-center gap-2">
              <Button onClick={() => setCommunityOpen(true)}>
                <Store size={15} /> {t("wfCommunity")}
              </Button>
              <Button
                variant="outline"
                loading={create.isPending && create.variables === undefined}
                onClick={() => create.mutate(undefined)}
              >
                <Plus size={15} /> {t("wfCreate")}
              </Button>
              <Button variant="outline" loading={importFile.isPending} onClick={() => importInputRef.current?.click()}>
                <FileUp size={15} /> {t("wfImport")}
              </Button>
              <input
                ref={importInputRef}
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) importFile.mutate(file);
                }}
              />
            </span>
          }
        />
        {communityDialog}
      </div>
    );
  }

  const importControl = (
    <input
      ref={importInputRef}
      type="file"
      accept=".json,application/json"
      className="hidden"
      onChange={(event) => {
        const file = event.target.files?.[0];
        event.target.value = ""; // 同一文件可再次选择
        if (file) importFile.mutate(file);
      }}
    />
  );

  // ── 详情页:整页给画布。返回列表是**唯一**的出口,所以放在最左、和标题同一行。
  if (selected && nodeTypes.data) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-hidden [&>*]:shrink-0">
        {/* 这一层给编辑器高度:页面容器是 [&>*]:shrink-0,不套 flex-1 的话画布会塌成 0。 */}
        <div className="grid min-h-0 flex-1">
          <WorkflowEditor
            key={selected.id}
            workflow={selected}
            nodeTypes={nodeTypes.data}
            workspaceId={workspace.id}
            onBack={() => setSelectedId(null)}
          />
        </div>
        {importControl}
        </div>
      );
  }

  // ── 列表页:卡片 grid。卡面上给的是**判断"是不是这一条"所需的**:名字、说明、
  //     多少个节点、上次改动是什么时候。
  return (
    <div className={STUDIO_PAGE}>
      <PageHeading title={t("navWorkflows")} description={t("studioWorkflowsDesc")} count={workflows.data?.length} actions={
        <span className="flex flex-wrap items-center gap-2">
          {selectMode ? (
            <>
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                {t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}
              </span>
              <Button variant="outline" onClick={() => selectAll(workflows.data ?? [])}>
                <ListChecks size={13} /> {allSelected(workflows.data ?? []) ? t("mediaDeselectAll") : t("mediaSelectAll")}
              </Button>
              <Button
                variant="outline"
                className="hover:border-destructive/50 hover:text-destructive"
                disabled={selectedIds.size === 0}
                onClick={() => setBatchDeleting(true)}
              >
                <Trash2 size={13} /> {t("delete")}
              </Button>
              <Button variant="outline" onClick={exit}>
                <X size={13} /> {t("cancel")}
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={() => enterSelectMode()}>
                <Check size={13} /> {t("mediaSelectMode")}
              </Button>
              <Button variant="outline" loading={importFile.isPending} onClick={() => importInputRef.current?.click()}>
                <FileUp size={13} /> {t("wfImport")}
              </Button>
              <Button variant="outline" onClick={() => setCommunityOpen(true)}>
                <Store size={13} /> {t("wfCommunity")}
              </Button>
              <Button loading={create.isPending && create.variables === undefined} onClick={() => create.mutate(undefined)}>
                <Plus size={13} /> {t("wfCreate")}
              </Button>
            </>
          )}
        </span>
      } />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* 取不到**不是**一个都没有。缓存里还有旧数据时照常显示它(总比一片空白强),
            但一条都没有又取不回来时,得说清是没连上而不是"你还没有工作流"。 */}
        {workflows.isError && (workflows.data ?? []).length === 0 ? (
          <PageLoadError icon={<WorkflowIcon size={22} />} error={workflows.error} onRetry={() => void workflows.refetch()} />
        ) : (
        <div className={CARD_GRID}>
          {workflows.isLoading &&
            (workflows.data ?? []).length === 0 &&
            [0, 1, 2, 3].map((i) => <CanvasCardSkeleton key={`sk${i}`} description />)}
          {(workflows.data ?? []).map((workflow) => (
            <ContextMenu key={workflow.id}>
              <ContextMenuTrigger asChild>
                <div className="relative h-full">
                  <button type="button" aria-label={workflow.name} className="h-full w-full rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => (selectMode ? toggle(workflow.id) : setSelectedId(workflow.id))}>
                    <WorkflowCard workflow={workflow} />
                    {selectMode && <SelectionCheck selected={selectedIds.has(workflow.id)} />}
                  </button>
                  {!selectMode && <div className="absolute right-2 top-2 rounded-lg bg-panel"><ActionMenu label={`${t("studioActions")}: ${workflow.name}`} actions={cardActions(workflow)} /></div>}
                </div>
              </ContextMenuTrigger>
              <ContextMenuContent>
                <ActionContextMenuItems actions={contextActions(workflow)} />
              </ContextMenuContent>
            </ContextMenu>
          ))}
        </div>
        )}
      </div>
      {importControl}
      {communityDialog}
      <RenameDialog
        open={menuRenaming !== null}
        title={t("rename")}
        initialValue={menuRenaming?.name ?? ""}
        onCancel={() => setMenuRenaming(null)}
        pending={menuRename.isPending}
        onSubmit={(name) => menuRenaming && menuRename.mutate({ id: menuRenaming.id, name })}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        body={t("wfDeleteBody")}
        onCancel={() => setBatchDeleting(false)}
        pending={batchRemove.isPending}
        onConfirm={() => batchRemove.mutate()}
      />
      <ConfirmDialog
        open={menuDeleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("wfDeleteBody")}
        onCancel={() => setMenuDeleting(null)}
        pending={menuRemove.isPending}
        onConfirm={() => menuDeleting && menuRemove.mutate(menuDeleting.id)}
      />
    </div>
  );
}
