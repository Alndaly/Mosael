import type React from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import {
  AlertTriangle,
  Bot,
  CircleCheck,
  Download,
  GitCommitVertical,
  History,
  ListChecks,
  Map as MapIcon,
  Maximize2,
  Pencil,
  Play,
  Plus,
  Redo2,
  Square,
  Trash2,
  Undo2,
} from "lucide-react";
import type { UseMutationResult } from "@tanstack/react-query";

import type { Workflow, WorkflowNodeType } from "@/api/client";
import type { useI18n } from "@/app/preferences";
import { ActionMenu } from "@/components/app/ActionMenu";
import { CanvasInputModeSwitch } from "@/components/app/CanvasInputModeSwitch";
import { CanvasNodeSearch, type CanvasSearchEntry, type CanvasSearchHighlight } from "@/components/app/CanvasNodeSearch";
import { CanvasToolbar, CanvasToolbarGroup } from "@/components/app/CanvasToolbar";
import { EdgeShapeToggle, type EdgeShape } from "@/components/app/canvasEdgeShape";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { AnnotationControls } from "@/features/markers/AnnotationControls";
import { MarkerListButton } from "@/features/markers/MarkerListButton";
import type { CanvasMarker } from "@/features/markers/markers";
import type { useNodePicker } from "@/features/nodeForms/nodePicker";
import { scopeId, type ScopePath } from "@/features/workflows/scope";
import type { WorkflowRunState } from "@/features/workflows/useWorkflowRun";
import type { WorkflowSaveState } from "@/features/workflows/useWorkflowSave";
import type { useWorkflowComments } from "@/features/workflows/WorkflowComments";
import { workflowIssueText } from "@/features/workflows/workflowCanvasModel";
import { cn } from "@/lib/utils";

type SetBoolean = React.Dispatch<React.SetStateAction<boolean>>;

/** 编辑器浮在画布顶上的那条工具条要用到的东西 —— 全是 WorkflowEditor 里现成的状态和动作。 */
export interface WorkflowEditorToolbarProps
  extends Pick<
    WorkflowRunState,
    "analysis" | "checklistCount" | "checklistLabel" | "running" | "stop" | "run" | "launching" | "startRun"
  > {
  t: ReturnType<typeof useI18n>;
  workflow: Workflow;
  registry: Map<string, WorkflowNodeType>;
  agentOpen: boolean;
  setAgentOpen: SetBoolean;
  setAgentMode: (mode: "docked" | "floating") => void;
  scopeKey: string;
  enterScope: (path: ScopePath) => void;
  focusNode: (nodeId: string) => void;
  pendingFocusRef: React.MutableRefObject<{ scope: string; nodeId: string | null } | null>;
  showHistory: boolean;
  setShowHistory: SetBoolean;
  save: WorkflowSaveState["save"];
  dirty: boolean;
  openRevisions: () => Promise<void>;
  exportFile: UseMutationResult<void, Error, void>;
  setRenaming: SetBoolean;
  setDeleting: SetBoolean;
  nodeOptions: ReturnType<typeof useNodePicker>["options"];
  canAddStart: boolean;
  addNode: (type: string) => void;
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
  atRoot: boolean;
  workflowComments: ReturnType<typeof useWorkflowComments>;
  setCollaborationOpen: SetBoolean;
  markerMode: boolean;
  setMarkerMode: SetBoolean;
  enterMarkerMode: () => void;
  markersVisible: boolean;
  setMarkersVisible: SetBoolean;
  markers: CanvasMarker[];
  jumpToMarker: (marker: CanvasMarker) => void;
  searchEntries: CanvasSearchEntry[];
  selectedNodeId: string | null;
  setSearchHit: (hit: CanvasSearchHighlight | null) => void;
  edgeShape: EdgeShape;
  setEdgeShape: (shape: EdgeShape) => void;
  showMinimap: boolean;
  setShowMinimap: (mode: "on" | "off") => void;
  rfRef: React.MutableRefObject<ReactFlowInstance | null>;
  fitCanvas: (instance: ReactFlowInstance, duration?: number) => void;
}

/**
 * 画布顶上那条浮动工具条:助手、运行(就绪清单 / 执行历史 / 运行·停止)、更多、添加节点、撤销重做、
 * 讨论与标记、查找与视图。
 *
 * **是一个返回元素的函数,不是组件** —— 编辑器直接调它,React 树和拆出来之前一模一样(工具条里的
 * 弹层、下拉的开合状态挂在哪一层都不变)。
 */
export function workflowEditorToolbar({
  t,
  workflow,
  registry,
  agentOpen,
  setAgentOpen,
  setAgentMode,
  analysis,
  checklistCount,
  checklistLabel,
  scopeKey,
  enterScope,
  focusNode,
  pendingFocusRef,
  showHistory,
  setShowHistory,
  running,
  stop,
  run,
  launching,
  startRun,
  save,
  dirty,
  openRevisions,
  exportFile,
  setRenaming,
  setDeleting,
  nodeOptions,
  canAddStart,
  addNode,
  canUndo,
  canRedo,
  undo,
  redo,
  atRoot,
  workflowComments,
  setCollaborationOpen,
  markerMode,
  setMarkerMode,
  enterMarkerMode,
  markersVisible,
  setMarkersVisible,
  markers,
  jumpToMarker,
  searchEntries,
  selectedNodeId,
  setSearchHit,
  edgeShape,
  setEdgeShape,
  showMinimap,
  setShowMinimap,
  rfRef,
  fitCanvas,
}: WorkflowEditorToolbarProps): React.ReactElement {
  return (
    <CanvasToolbar
      label={t("canvasTools")}
      data-workflow-toolbar-actions=""
      end={
        <>
          <CanvasToolbarGroup label={t("wfAgentTitle")}>
            <Button
              variant="ghost"
              size="icon-sm"
              className={cn(agentOpen && "bg-secondary text-foreground")}
              aria-label={t("wfAgentTitle")}
              title={t("wfAgentTitle")}
              aria-pressed={agentOpen}
              onClick={() => {
                setAgentOpen((value) => !value);
                if (!agentOpen) setAgentMode("docked");
              }}
            >
              <Bot size={14} />
            </Button>
          </CanvasToolbarGroup>
          <CanvasToolbarGroup label={t("wfRun")}>
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    // 组已经有自己的边框和底了,按钮**不再各带一层** —— 那是胶囊套胶囊。
                    // 状态靠颜色说,不靠再画一圈线。
                    "inline-flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border-0 bg-transparent text-xs font-[650] text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground",
                    checklistCount > 0 ? "gap-1 px-2" : "w-8 justify-center",
                    analysis.errorCount
                      ? "bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive hover:bg-[color-mix(in_srgb,var(--destructive)_18%,transparent)] hover:text-destructive"
                      : analysis.warnCount
                        ? "bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] text-warning hover:bg-[color-mix(in_srgb,var(--warning)_18%,transparent)] hover:text-warning"
                        : "bg-[color-mix(in_srgb,var(--success)_10%,transparent)] text-success hover:bg-[color-mix(in_srgb,var(--success)_16%,transparent)] hover:text-success",
                  )}
                  aria-label={`${t("wfChecklist")}: ${checklistLabel}`}
                  title={checklistLabel}
                >
                  {checklistCount > 0 ? <AlertTriangle size={13} /> : <CircleCheck size={14} />}
                  {checklistCount > 0 && (
                    <em className="inline-grid h-[15px] min-w-[15px] place-items-center rounded-full bg-[color-mix(in_srgb,currentColor_18%,transparent)] px-1 text-ui-2xs font-bold not-italic leading-none text-current">
                      {checklistCount}
                    </em>
                  )}
                </button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-80 p-1.5">
                {analysis.issues.length === 0 ? (
                  <div className="flex items-center gap-1.5 p-2 text-ui-sm text-success">
                    <CircleCheck size={14} /> {t("wfChecklistReady")}
                  </div>
                ) : (
                  <>
                    <div className="px-2 pb-1.5 pt-1 text-ui-xs font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                      {analysis.errorCount
                        ? t("wfChecklistBlocked").replace("{n}", String(analysis.errorCount))
                        : t("wfChecklistWarnOnly").replace("{n}", String(analysis.warnCount))}
                    </div>
                    <div className="flex max-h-80 flex-col gap-0.5 overflow-auto">
                      {[...analysis.issues]
                        .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1))
                        .map((issue, i) => (
                          <button
                            key={`${issue.nodeId}-${issue.code}-${i}`}
                            type="button"
                            className={cn(
                              "grid cursor-pointer grid-cols-[14px_auto_1fr] items-center gap-1.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-left hover:bg-muted",
                              issue.severity === "error" ? "[&>svg]:text-destructive" : "[&>svg]:text-warning",
                            )}
                            onClick={() => {
                              // 带人去问题所在的那一层,聚焦那个节点。已经在那一层就直接聚焦;要换层就
                              // 先记下来,等那一层的画布挂好(onInit)再聚焦。「缺开始节点」不属于哪个节点,只回主流程。
                              const target = issue.nodeId === "__workflow__" ? null : issue.nodeId;
                              if (scopeId(issue.path) === scopeKey) {
                                if (target) focusNode(target);
                                return;
                              }
                              pendingFocusRef.current = { scope: scopeId(issue.path), nodeId: target };
                              enterScope(issue.path);
                            }}
                          >
                            <AlertTriangle size={12} />
                            <span className="whitespace-nowrap text-xs font-semibold">{issue.nodeName}</span>
                            <span className="truncate text-ui-xs text-muted-foreground">
                              {workflowIssueText(t, issue, registry)}
                            </span>
                          </button>
                        ))}
                    </div>
                  </>
                )}
              </PopoverContent>
            </Popover>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("wfHistory")}
              title={t("wfHistory")}
              aria-pressed={showHistory}
              className={cn(showHistory && "bg-secondary text-foreground")}
              onClick={() => setShowHistory((v) => !v)}
            >
              <History size={14} />
            </Button>
            {/* **在跑的时候,这颗按钮是「停止」。**
                此前它一直是 ▶:点完之后画布上节点一个个亮起来,而工具栏里没有任何出口 ——
                唯一能取消的地方是任务中心列表那一行的 ×,没人会想到去那儿找。
                看着它跑的这一页就该能停下它。 */}
            {running ? (
              <Button
                size="icon-sm"
                variant="outline"
                className="hover:border-destructive/50 hover:text-destructive"
                loading={stop.isPending}
                aria-label={t("wfStop")}
                title={t("jobCancelHint")}
                onClick={() => stop.mutate()}
              >
                <Square size={14} />
              </Button>
            ) : (
              <Button
                size="icon-sm"
                disabled={!analysis.runnable}
                loading={run.isPending || launching}
                aria-label={t("wfRun")}
                title={
                  !analysis.runnable
                    ? t("wfRunBlocked")
                    : save.isPending
                      ? t("wfSaving")
                      : dirty && save.isError
                        ? t("wfRunRetriesSave")
                        : t("wfRun")
                }
                onClick={() => void startRun()}
              >
                <Play size={14} />
              </Button>
            )}
          </CanvasToolbarGroup>
          <CanvasToolbarGroup label={t("more")}>
            <ActionMenu
              label={t("more")}
              // 和列表页卡片上的 ⋯ 同一组条目(运行在工具栏上已经有了,不重复):
              // 重命名本来只能点标题,没人知道标题能点。删除由 ActionMenu 自动隔开成单独一组。
              actions={[
                {
                  label: t("rename"),
                  icon: <Pencil />,
                  onSelect: () => setRenaming(true),
                },
                {
                  label: t("wfRevisionHistory"),
                  hint: `v${workflow.revision}`,
                  icon: <GitCommitVertical />,
                  disabled: save.isPending,
                  onSelect: () => {
                    void openRevisions();
                  },
                },
                {
                  label: t("wfExport"),
                  icon: <Download />,
                  disabled: exportFile.isPending,
                  onSelect: () => exportFile.mutate(),
                },
                {
                  label: t("delete"),
                  icon: <Trash2 />,
                  destructive: true,
                  onSelect: () => setDeleting(true),
                },
              ]}
            />
          </CanvasToolbarGroup>
        </>
      }
    >
      <CanvasToolbarGroup label={t("canvasEditTools")}>
        <SearchableSelect
          value=""
          // 标记走单独一条:它不是节点,addNode 会去 registry 里查类型,查不到就什么也不发生。
          onValueChange={(value) => {
            setMarkerMode(false);
            workflowComments.exit();
            addNode(value);
          }}
          searchPlaceholder={t("wfAddNode")}
          options={[...nodeOptions.filter((option) => option.value !== "start" || canAddStart)]}
          trigger={
            <button
              type="button"
              data-wf-add-node=""
              // 组里全是圆形图标钮,只有它带文字就会显得突出一截 —— 而它并不比「运行」更重要。
              // 名字进 title/aria-label,悬停仍然说得出自己是谁。
              className="inline-flex h-8 items-center gap-2 rounded-md bg-action px-3 text-action-foreground hover:bg-action/90"
              aria-label={t("wfAddNode")}
              title={t("wfAddNode")}
            >
              <Plus size={15} /> {t("wfAddNode")}
            </button>
          }
        />
        <Button
          variant="ghost"
          size="icon-sm"
          title={`${t("undo")} ⌘Z`}
          aria-label={t("undo")}
          disabled={!canUndo}
          onClick={undo}
        >
          <Undo2 size={14} />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          title={`${t("redo")} ⇧⌘Z`}
          aria-label={t("redo")}
          disabled={!canRedo}
          onClick={redo}
        >
          <Redo2 size={14} />
        </Button>
      </CanvasToolbarGroup>
      {/* 讨论和标记钉在**主流程**的画布坐标上,体里是另一张画布 —— 在那儿摆出来,
          要么标在错的位置,要么落进体里跟着体一起被执行器忽略。 */}
      {atRoot && (
        <>
      <CanvasToolbarGroup label={t("boardCommentMode")}>
        {workflowComments.controls(() => setMarkerMode(false))}
        <Button
          variant="ghost"
          size="icon-sm"
          title={t("boardDiscussionCenter")}
          aria-label={t("boardDiscussionCenter")}
          onClick={() => setCollaborationOpen(true)}
        >
          <ListChecks size={14} />
        </Button>
      </CanvasToolbarGroup>
      <CanvasToolbarGroup label={t("markers")}>
        <AnnotationControls
          kind="marker"
          active={markerMode}
          visible={markersVisible}
          onMode={() => (markerMode ? setMarkerMode(false) : enterMarkerMode())}
          onVisible={() => {
            setMarkersVisible(!markersVisible);
            if (markersVisible) setMarkerMode(false);
          }}
        />
        <MarkerListButton
          markers={markers}
          onJump={(marker) => {
            setMarkersVisible(true);
            jumpToMarker(marker);
          }}
        />
      </CanvasToolbarGroup>
        </>
      )}
      <CanvasToolbarGroup label={t("canvasViewTools")}>
        <CanvasNodeSearch
          entries={searchEntries}
          selectedId={selectedNodeId}
          onFocus={focusNode}
          onHighlight={setSearchHit}
        />
        <EdgeShapeToggle value={edgeShape} onChange={setEdgeShape} />
        <CanvasInputModeSwitch />
        <Button
          variant="ghost"
          size="icon-sm"
          className={cn(showMinimap && "bg-secondary text-foreground")}
          aria-label={t("wfMinimap")}
          title={t("wfMinimap")}
          aria-pressed={showMinimap}
          onClick={() => setShowMinimap(showMinimap ? "off" : "on")}
        >
          <MapIcon size={14} />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={t("boardsFitView")}
          title={t("boardsFitView")}
          onClick={() => {
            if (rfRef.current) fitCanvas(rfRef.current);
          }}
        >
          <Maximize2 size={14} />
        </Button>
      </CanvasToolbarGroup>
    </CanvasToolbar>
  );
}
