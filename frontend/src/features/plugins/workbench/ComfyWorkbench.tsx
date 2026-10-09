import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Boxes, ListChecks, PanelRightClose, PanelRightOpen, Play, Save, TriangleAlert } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { ChromeStatusSlot } from "@/components/app/chromeStatusSlot";
import { APP_CHROME, ChromeAboveDialogs } from "@/components/ui/appChrome";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint, HintRegion } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { ComfyNavigationSwitch } from "@/features/plugins/ComfyNavigationSwitch";
import { refreshConnectionCatalog } from "@/features/plugins/pluginCaches";
import { useAgentPlace } from "@/features/agent/activePlace";
import { comfyPlace } from "@/features/agent/places";
import { AppPanel } from "@/features/plugins/workbench/AppPanel";
import { AssistantPanel } from "@/features/plugins/workbench/AssistantPanel";
import { useColumnWidth } from "@/features/plugins/workbench/columnWidth";
import { useFollowWorkbenchPlaces } from "@/features/plugins/workbench/followPlaces";
import { WorkbenchTabs } from "@/features/plugins/workbench/WorkbenchTabs";
import { MissingPanel } from "@/features/plugins/workbench/MissingPanel";
import { ModelsPanel } from "@/features/plugins/workbench/ModelsPanel";
import { RunPanel, useCanvasRun } from "@/features/plugins/workbench/RunPanel";
import { savedPath } from "@/features/plugins/workbench/workbenchLogic";
import { PanelLoading, PanelNote } from "@/features/plugins/workbench/workbenchParts";
import { onWorkbenchPlaces, useWorkbench, workbenchCall, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";
import { comboFromEvent, formatCombo, listenKeys } from "@/lib/shortcuts";
import { HANDLE_COLUMN, HANDLE_ON_LEFT_EDGE } from "@/lib/useResizableSidebar";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { WINDOW_CHROME_INSET } from "@/lib/windowChrome";
import { cn } from "@/lib/utils";

const TABS = ["models", "missing", "app", "run", "assistant"] as const;
type Tab = (typeof TABS)[number];
const BAR_REGION = { side: "bottom" as const };
//: 等桥多久才说「连不上」:第一次打开要下整套前端,慢的机器上要好几十秒
const BRIDGE_PATIENCE_MS = 45_000;
const COLUMN_REGION = { side: "left" as const };
const SAVE_KEY = "Mod+S";

/** 这一下按键落在工作台自己的顶栏或右边那一列里(助手的输入框也在这一列)。 */
const inWorkbench = (target: EventTarget | null) =>
  target instanceof Element && target.closest("[data-comfy-workbench-bar], [data-comfy-workbench-column]") !== null;

/**
 * 每个页签自己滚动(竖排的 flex,面板的根占满剩下的高 —— 空的、在读的摆在正中,见 workbenchParts)。能拿焦点:在里面点了
 * 不能聚焦的地方(一段说明),焦点落在这一层上,方向键、PageDown 滚的就是它;内嵌网页亮着时,落在外壳外面的按键会被
 * 吞掉(见 embeddedFocus),落在这里的不会。
 */
const TAB_PANEL =
  "flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain p-3 focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-inset focus-visible:ring-ring";
/** 「助手」页签:对话面板自己滚、自己留边,这一层只占满剩下的高。 */
const ASSISTANT_PANEL = "grid min-h-0 flex-1";

/**
 * 在工作台里**存了**一张工作流(这一张从「有没存的改动」变成存好了,或者第一次存出一个路径),或者工作台关上了:这个连接的
 * 目录重拉,依赖它的查询重问。精简表单、工作流的名字都住在那张图里;AI 工作台的「引擎参数」、画板、工作流节点读的是后端按
 * 连接存着的那份目录。
 *
 * 此前只有「从工作流库打开、再回到工作流库」这一条路会重拉(工作流库的 editorReturned):从 AI 工作台的「在工作台里打开」进来、
 * 在应用表单里加了一项、存好就回去,右栏还是那张旧表,要等一分钟的指纹巡检加上页面重挂才对得上。存的那一刻(ComfyUI 自己的
 * Ctrl+S 也算 —— 桥报的 `modified` 跟着变)和关上的那一刻都拉,几处同时要的并成一次(refreshConnectionCatalog)。
 */
function useCatalogFollowsWorkbench(target: WorkbenchTarget | null, workflow: ComfyWorkbenchState["workflow"] | null) {
  const qc = useQueryClient();
  const instanceId = target?.instanceId ?? "";
  const seen = React.useRef<{ instanceId: string; key: string; modified: boolean; temporary: boolean } | null>(null);
  React.useEffect(() => {
    const before = seen.current;
    const now = instanceId && workflow
      ? { instanceId, key: workflow.key, modified: workflow.modified, temporary: workflow.temporary }
      : null;
    seen.current = now;
    if (!before || !now || before.instanceId !== now.instanceId || before.key !== now.key) return;
    const saved = (before.modified && !now.modified) || (before.temporary && !now.temporary);
    if (saved) void refreshConnectionCatalog(qc, now.instanceId);
  }, [instanceId, workflow, qc]);
  const open = React.useRef("");
  React.useEffect(() => {
    const was = open.current;
    open.current = instanceId;
    if (was && was !== instanceId) void refreshConnectionCatalog(qc, was);
  }, [instanceId, qc]);
}

/**
 * 「表单」页签认的是**同一张**,不是它此刻的路径:同一张在 ComfyUI 里第一次存盘、改名、挪文件夹(桥报一次 `renames`),
 * `workflow.key` 跟着变 —— 按 key 重挂的话,还没同步到画布的表单草稿(标题、挑的项、顺序)就静默没了(PLG-10)。地方变了的
 * 消息和新快照在同一拍里交出来(见 workbenchSession.receive),这里先记下「新 key 还是那一张」,面板就不重挂;换到别的一张照旧重挂。
 */
function useSameWorkflowKey(workflowKey: string): string {
  const [aliases] = React.useState(() => new Map<string, string>());
  React.useEffect(() => onWorkbenchPlaces((news) => {
    for (const { from, to } of news.renames) aliases.set(to.key, aliases.get(from.key) ?? from.key);
  }), [aliases]);
  return aliases.get(workflowKey) ?? workflowKey;
}

/**
 * ComfyUI 工作台(ADR 0038 §3):全屏,左边整块是那台 ComfyUI 自己的画布(内嵌视图,每个自定义节点照常能用),Mosael 的东西
 * 都画在它旁边 —— 顶栏(连接、工作流名、有没有没存的改动、操控方式、「保存」「运行」)和右边能收起、能拉宽拉窄的一列(模型库、
 * 缺失项、应用、运行与结果、助手 —— 智能体,ADR 0042)。网页是原生视图、盖在一切 DOM 上:顶栏占着视图上沿那 `barHeight`(和主进程 EMBED_HEADER_HEIGHT
 * 同一个数,见 contracts/shared-constants.json),右边那一列开着时视图让出那么宽(见 columnWidth);要确认的事就地确认。
 *
 * 和画布通话的是主进程注入的桥(只拉不推,见 electron/publish/comfyWorkbench);这版前端缺了哪一样,那一处就说「这版 ComfyUI
 * 前端不支持 X」,画布照常是一个能用的 ComfyUI。
 *
 * **画布上换了一张**(在 ComfyUI 自己的标签栏、侧栏里):桥报的 `workflow.key` 变了,模型库、缺失项、应用这几个面板按它重挂
 * (各自从头读这一张),运行与结果把这一张跑过的排在前面。同一张里改了图(`revision` 变了),缺失项过一会儿自己重新检查。
 */
export function ComfyWorkbench({ barHeight }: { barHeight: number }) {
  const t = useI18n();
  const { target, state, events, runs } = useWorkbench();
  const [tab, setTab] = usePersistentTab<Tab>("comfy-workbench.tab", "models", TABS);
  const [open, setOpen] = usePersistentTab<"open" | "closed">("comfy-workbench.column", "open", ["open", "closed"]);
  //: 去过的面板留着(切回来不重读、跑的进度不断)
  const [visited, setVisited] = React.useState<Set<Tab>>(() => new Set([tab]));
  const [saveNote, setSaveNote] = React.useState("");
  const run = useCanvasRun(target);
  const columnOpen = open === "open";
  const column = useColumnWidth(columnOpen && Boolean(target));
  const workflow = state?.workflow ?? null;
  const workflowKey = workflow?.key ?? "";
  //: 表单页签按「同一张」挂:存盘、改名时不重挂,草稿不丢
  const formsKey = useSameWorkflowKey(workflowKey);
  //: 工作台盖在页面上时,「眼下这一处」是这台 ComfyUI 上开着的那张(ADR 0044 §3、§11):助手接那一张的对话,换标签页
  //: 就换成那一张的;每条消息带着它,这一轮就有 ComfyUI 那份工具。关了工作台退回下面那一页。
  const agentPlace = useAgentPlace(target ? comfyPlace(target.instanceId, workflow) : null);
  //: 同一张存盘、改名后对话跟着它走;智能体开的新标签页接住开它的那段对话(ADR 0044 §6、§9)
  useFollowWorkbenchPlaces();
  //: 存好一张、关上工作台:这个连接的目录重拉(精简表单住在那张图里)
  useCatalogFollowsWorkbench(target, workflow);
  //: 一直没收到桥那边的回话(这版前端太旧、页面要先登录、桥注入不上):说一句,画布照常能用
  const [stuck, setStuck] = React.useState(false);
  React.useEffect(() => {
    setStuck(false);
    if (state) return;
    const timer = setTimeout(() => setStuck(true), BRIDGE_PATIENCE_MS);
    return () => clearTimeout(timer);
  }, [state, target?.instanceId]);

  React.useEffect(() => {
    setVisited((current) => (current.has(tab) ? current : new Set([...current, tab])));
  }, [tab]);
  //: 换了一张:上一张没存成的那句话不是这一张的
  React.useEffect(() => setSaveNote(""), [workflowKey]);
  //: 「保存」是前端自己的保存命令(和 ComfyUI 菜单「工作流 → 保存」同一条):顶栏那一颗和 ⌘S / Ctrl+S 都走这里
  const canSave = state?.capabilities?.save !== false;
  const saveNow = Boolean(state) && canSave;
  const unsaved = Boolean(workflow?.temporary);
  const save = React.useCallback(async () => {
    setSaveNote("");
    const result = await workbenchCall({ op: "save" });
    if (!result.ok) setSaveNote(t("workbenchCallFailed").replace("{why}", result.error));
    //: 没存过的那张:ComfyUI 在画布上弹出起名字的框(框里的输入已经选中)—— 键盘交给画布,接着就能打名字、回车。不交的话
    //: 按 ⌘S 时焦点还在这一列里,打的字落进助手的输入框(真机上看到的)
    else if (unsaved) void window.mosaelPublish?.focusPage?.();
  }, [t, unsaved]);
  //: ⌘S / Ctrl+S(维护者:「可以通过快捷键快速保存」):焦点在工作台自己的顶栏、右边这一列时和顶栏的「保存」一样 —— 在助手的
  //: 输入框里打着字也算,存盘不是改字。焦点在画布里时这一下根本到不了这一页(原生视图收走;应用菜单里也没有占 ⌘S 的项),
  //: ComfyUI 自己存,不会存两次。在捕获阶段接住、不往下传:工作台底下那一页(比如工作流编辑器)也认 ⌘S,不能让它跟着存一次
  //: 看不见的东西。存不了的时候(还没连上、这版前端没有保存命令)照样接住,什么都不做。
  React.useEffect(
    () =>
      listenKeys(
        window,
        (event) => {
          if (comboFromEvent(event) !== SAVE_KEY || !inWorkbench(event.target)) return;
          event.preventDefault();
          event.stopImmediatePropagation();
          if (saveNow) void save();
        },
        true,
      ),
    [saveNow, save],
  );
  //: 「助手」开好一张新的、还缺模型:「去下载」换到缺失项那一页
  const showMissing = React.useCallback(() => setTab("missing"), [setTab]);

  if (!target) return null;
  const capabilities = state?.capabilities ?? null;
  const path = savedPath(state);
  const workflowName = workflow ? workflow.name || path || t("workbenchUnsaved") : "";
  const modified = Boolean(workflow?.modified);
  const canRun = Boolean(capabilities?.export) && Boolean(path);
  const runBlocked = !state ? t("workbenchConnecting")
    : !capabilities?.export ? t("workbenchUnsupported").replace("{what}", t("workbenchCapExport"))
    : !path ? t("workbenchRunNeedsSave") : undefined;

  const startRun = () => {
    setTab("run");
    if (!columnOpen) setOpen("open");
    run.mutate({ path, workflowKey, workflowName });
  };
  const tabLabel: Record<Tab, string> = {
    models: t("workbenchTabModels"),
    missing: t("workbenchTabMissing"),
    app: t("workbenchTabApp"),
    run: t("workbenchTabRun"),
    assistant: t("workbenchTabAssistant"),
  };

  //: 顶栏:控件一律 sm 一档(32px、text-ui-sm),居中排在栏里;文字那一段同一个字号
  const bar = (
    <div
      {...APP_CHROME}
      data-comfy-workbench-bar=""
      style={{ height: barHeight }}
      className={cn(
        "fixed inset-x-0 top-0 z-[200] flex items-center gap-2 border-b border-border bg-panel px-2.5 [-webkit-app-region:drag]",
        WINDOW_CHROME_INSET,
      )}
    >
      <HintRegion.Provider value={BAR_REGION}>
        <Hint label={t("publishBackHint")}>
          <Button
            variant="outline"
            size="sm"
            data-publish-back=""
            data-bar-control=""
            className="[-webkit-app-region:no-drag] shrink-0"
            onClick={() => void window.mosaelPublish?.hideView()}
          >
            <ArrowLeft />
            {t("publishBackToApp")}
          </Button>
        </Hint>
        <div className="flex min-w-0 flex-1 items-center gap-1.5 px-1 text-ui-sm">
          <span className="shrink-0 font-medium text-primary">{t("workbenchTitle")}</span>
          <Truncate className="min-w-0 shrink text-muted-foreground">{target.instanceName}</Truncate>
          {workflowName && <span aria-hidden className="shrink-0 text-muted-foreground">/</span>}
          {workflowName && (
            <h1 className="m-0 min-w-0 text-ui-sm font-semibold text-foreground">
              <Truncate>{workflowName}</Truncate>
            </h1>
          )}
          {modified && (
            <Hint label={t("workbenchUnsavedChanges")}>
              <span role="img" aria-label={t("workbenchUnsavedChanges")} className="inline-block size-2 shrink-0 rounded-full bg-warning" />
            </Hint>
          )}
          {!state && <span className="shrink-0 text-muted-foreground">{t("workbenchConnecting")}</span>}
        </div>
        {/* 等人拍板的卡、免提浮标:画布在前台时收在这里(ADR 0051,见 ChromeStatusSlot) */}
        <ChromeStatusSlot size="sm" />
        <ComfyNavigationSwitch connectionId={target.instanceId} size="sm" />
        <Hint label={canSave ? t("workbenchSaveHint") : t("workbenchUnsupported").replace("{what}", t("workbenchCapSave"))}
              shortcut={canSave ? formatCombo(SAVE_KEY) : null}>
          <Button variant="outline" size="sm" data-bar-control="" className="[-webkit-app-region:no-drag] shrink-0"
                  disabled={!saveNow} onClick={() => void save()}>
            <Save />
            {t("workbenchSave")}
          </Button>
        </Hint>
        <Hint label={t("workbenchRunHintShort")} disabledReason={runBlocked}>
          <Button size="sm" data-bar-control="" className="[-webkit-app-region:no-drag] shrink-0" disabled={!canRun}
                  loading={run.isPending} onClick={startRun}>
            <Play />
            {t("workbenchRun")}
          </Button>
        </Hint>
        <IconButton
          variant="ghost"
          size="icon-sm"
          data-bar-control=""
          className="[-webkit-app-region:no-drag] shrink-0"
          label={columnOpen ? t("workbenchColumnHide") : t("workbenchColumnShow")}
          aria-expanded={columnOpen}
          onClick={() => setOpen(columnOpen ? "closed" : "open")}
        >
          {columnOpen ? <PanelRightClose /> : <PanelRightOpen />}
        </IconButton>
      </HintRegion.Provider>
    </div>
  );

  const aside = columnOpen ? (
    <HintRegion.Provider value={COLUMN_REGION}>
      <aside
        {...APP_CHROME}
        data-comfy-workbench-column=""
        aria-label={t("workbenchColumn")}
        style={{ top: barHeight, width: column.width }}
        className="fixed bottom-0 right-0 z-[200] flex flex-col border-l border-border bg-panel"
      >
        <div
          {...column.handleProps}
          aria-label={t("workbenchColumnResize")}
          data-workbench-resize=""
          //: 竖条压在列左边那条分割线上(和别处的拖柄一样);线左边是原生的画布,热区不往那边伸(见 HANDLE_ON_LEFT_EDGE)
          className={cn("absolute inset-y-0 z-10 focus-visible:outline-none focus-visible:before:bg-primary", HANDLE_COLUMN,
                        HANDLE_ON_LEFT_EDGE, column.dragging && "before:bg-primary")}
        />
        <WorkbenchTabs
          label={t("workbenchColumn")}
          idPrefix="comfy-workbench"
          active={tab}
          onSelect={setTab}
          tabs={TABS.map((one) => ({ value: one, label: tabLabel[one], icon: <TabIcon tab={one} /> }))}
        />
        {saveNote && <p role="alert" className="m-0 flex-none px-3 pt-3 text-ui-xs text-destructive">{saveNote}</p>}
        {!state && (
          <div className={TAB_PANEL}>
            {stuck ? <PanelNote tone="warning">{t("workbenchBridgeMissing")}</PanelNote> : <PanelLoading label={t("workbenchConnecting")} />}
          </div>
        )}
        {state && TABS.filter((one) => visited.has(one)).map((one) => (
          <div key={one} role="tabpanel" id={`comfy-workbench-panel-${one}`} aria-labelledby={`comfy-workbench-tab-${one}`}
               hidden={tab !== one} {...(one === "assistant" ? { className: ASSISTANT_PANEL }
                 : { tabIndex: 0, "data-workbench-scroll": "", className: TAB_PANEL })}>
            {/* 换了一张工作流(key 变了):模型库、缺失项、应用各自重挂,从头读这一张 */}
            {one === "models" && (
              <ModelsPanel key={workflowKey} target={target} node={state.selection.node} capabilities={capabilities} />
            )}
            {one === "missing" && (
              <MissingPanel key={workflowKey} target={target} capabilities={capabilities} active={tab === "missing"}
                            revision={workflow?.revision ?? 0} />
            )}
            {one === "app" && (
              <AppPanel key={formsKey} target={target} workflowKey={workflowKey} path={path} canvasModified={Boolean(workflow?.modified)}
                        canExport={capabilities ? capabilities.export : false}
                        canMark={capabilities ? capabilities.marks : false} />
            )}
            {one === "run" && (
              <RunPanel target={target} runs={runs} events={events} workflowKey={workflowKey} active={tab === "run"}
                        canMark={Boolean(capabilities?.marks && capabilities?.export)} runError={run.error} />
            )}
            {one === "assistant" && agentPlace && (
              <AssistantPanel target={target} place={agentPlace} runs={runs} workflowKey={workflowKey} onShowMissing={showMissing} />
            )}
          </div>
        ))}
      </aside>
    </HintRegion.Provider>
  ) : null;

  //: 顶栏和那一列都挂到 body 末尾:排在底下开着的工作流库后面,顶栏才拖得动窗口(见 ChromeAboveDialogs)
  return (
    <ChromeAboveDialogs>
      {bar}
      {aside}
    </ChromeAboveDialogs>
  );
}

/** 页签前面的图标(大小跟着页签那一档,16px)。 */
function TabIcon({ tab }: { tab: (typeof TABS)[number] }) {
  const Icon = { models: Boxes, missing: TriangleAlert, app: ListChecks, run: Play, assistant: Bot }[tab];
  return <Icon aria-hidden />;
}
