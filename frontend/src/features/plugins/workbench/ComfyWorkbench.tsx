import React from "react";
import { ArrowLeft, Boxes, ListChecks, PanelRightClose, PanelRightOpen, Play, Save, TriangleAlert } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { APP_CHROME, ChromeAboveDialogs } from "@/components/ui/appChrome";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint, HintRegion } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { ComfyNavigationSwitch } from "@/features/plugins/ComfyNavigationSwitch";
import { AppPanel } from "@/features/plugins/workbench/AppPanel";
import { DRAG_GUARD, useColumnWidth } from "@/features/plugins/workbench/columnWidth";
import { MissingPanel } from "@/features/plugins/workbench/MissingPanel";
import { ModelsPanel } from "@/features/plugins/workbench/ModelsPanel";
import { RunPanel, useCanvasRun } from "@/features/plugins/workbench/RunPanel";
import { savedPath } from "@/features/plugins/workbench/workbenchLogic";
import { PanelLoading, PanelNote } from "@/features/plugins/workbench/workbenchParts";
import { useWorkbench, workbenchCall } from "@/features/plugins/workbench/workbenchSession";
import { HANDLE_COLUMN } from "@/lib/useResizableSidebar";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { WINDOW_CHROME_INSET } from "@/lib/windowChrome";
import { cn } from "@/lib/utils";

const TABS = ["models", "missing", "app", "run"] as const;
type Tab = (typeof TABS)[number];
const BAR_REGION = { side: "bottom" as const };
//: 等桥多久才说「连不上」:第一次打开要下整套前端,慢的机器上要好几十秒
const BRIDGE_PATIENCE_MS = 45_000;
const COLUMN_REGION = { side: "left" as const };

/**
 * 每个页签自己滚动(竖排的 flex,面板的根占满剩下的高 —— 空的、在读的摆在正中,见 workbenchParts)。能拿焦点:在里面点了
 * 不能聚焦的地方(一段说明),焦点落在这一层上,方向键、PageDown 滚的就是它;内嵌网页亮着时,落在外壳外面的按键会被
 * 吞掉(见 embeddedFocus),落在这里的不会。
 */
const TAB_PANEL =
  "flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain p-3 focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-inset focus-visible:ring-ring";

/**
 * ComfyUI 工作台(ADR 0038 §3):全屏,左边整块是那台 ComfyUI 自己的画布(内嵌视图,每个自定义节点照常能用),Mosael 的东西
 * 都画在它旁边 —— 顶栏(连接、工作流名、有没有没存的改动、操控方式、「保存」「运行」)和右边能收起、能拉宽拉窄的一列(模型库、
 * 缺失项、应用、运行与结果)。网页是原生视图、盖在一切 DOM 上:顶栏占着视图上沿那 `barHeight`(和主进程 EMBED_HEADER_HEIGHT
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

  if (!target) return null;
  const capabilities = state?.capabilities ?? null;
  const path = savedPath(state);
  const workflowName = workflow ? workflow.name || path || t("workbenchUnsaved") : "";
  const modified = Boolean(workflow?.modified);
  const canSave = capabilities?.save !== false;
  const canRun = Boolean(capabilities?.export) && Boolean(path);
  const runBlocked = !state ? t("workbenchConnecting")
    : !capabilities?.export ? t("workbenchUnsupported").replace("{what}", t("workbenchCapExport"))
    : !path ? t("workbenchRunNeedsSave") : undefined;

  const startRun = () => {
    setTab("run");
    if (!columnOpen) setOpen("open");
    run.mutate({ path, workflowKey, workflowName });
  };
  const save = async () => {
    setSaveNote("");
    const result = await workbenchCall({ op: "save" });
    if (!result.ok) setSaveNote(t("workbenchCallFailed").replace("{why}", result.error));
  };

  const tabLabel: Record<Tab, string> = {
    models: t("workbenchTabModels"),
    missing: t("workbenchTabMissing"),
    app: t("workbenchTabApp"),
    run: t("workbenchTabRun"),
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
        <ComfyNavigationSwitch connectionId={target.instanceId} size="sm" />
        <Hint label={canSave ? t("workbenchSaveHint") : t("workbenchUnsupported").replace("{what}", t("workbenchCapSave"))}>
          <Button variant="outline" size="sm" data-bar-control="" className="[-webkit-app-region:no-drag] shrink-0"
                  disabled={!state || !canSave} onClick={() => void save()}>
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
          className={cn("absolute inset-y-0 left-0 z-10 focus-visible:outline-none focus-visible:before:bg-primary", HANDLE_COLUMN,
                        column.dragging && "before:bg-primary")}
        />
        <div role="tablist" aria-label={t("workbenchColumn")} className="flex h-11 flex-none items-stretch gap-1 border-b border-border px-2">
          {TABS.map((one) => (
            <button
              key={one}
              type="button"
              role="tab"
              id={`comfy-workbench-tab-${one}`}
              aria-selected={tab === one}
              aria-controls={`comfy-workbench-panel-${one}`}
              className={cn(
                "inline-flex cursor-pointer items-center gap-1.5 border-0 border-b-2 bg-transparent px-2 text-ui-xs",
                tab === one ? "border-primary font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setTab(one)}
            >
              {one === "models" ? <Boxes size={13} aria-hidden /> : one === "missing" ? <TriangleAlert size={13} aria-hidden />
                : one === "app" ? <ListChecks size={13} aria-hidden /> : <Play size={13} aria-hidden />}
              {tabLabel[one]}
            </button>
          ))}
        </div>
        {saveNote && <p role="alert" className="m-0 flex-none px-3 pt-3 text-ui-xs text-destructive">{saveNote}</p>}
        {!state && (
          <div className={TAB_PANEL}>
            {stuck ? <PanelNote tone="warning">{t("workbenchBridgeMissing")}</PanelNote> : <PanelLoading label={t("workbenchConnecting")} />}
          </div>
        )}
        {state && TABS.filter((one) => visited.has(one)).map((one) => (
          <div key={one} role="tabpanel" id={`comfy-workbench-panel-${one}`} aria-labelledby={`comfy-workbench-tab-${one}`}
               hidden={tab !== one} tabIndex={0} data-workbench-scroll="" className={TAB_PANEL}>
            {/* 换了一张工作流(key 变了):模型库、缺失项、应用各自重挂,从头读这一张 */}
            {one === "models" && (
              <ModelsPanel key={workflowKey} target={target} node={state.selection.node} capabilities={capabilities} />
            )}
            {one === "missing" && (
              <MissingPanel key={workflowKey} target={target} capabilities={capabilities} active={tab === "missing"}
                            revision={workflow?.revision ?? 0} />
            )}
            {one === "app" && (
              <AppPanel key={workflowKey} target={target} canExport={capabilities ? capabilities.export : false}
                        canMark={capabilities ? capabilities.marks : false} />
            )}
            {one === "run" && (
              <RunPanel target={target} runs={runs} events={events} workflowKey={workflowKey} active={tab === "run"}
                        canMark={Boolean(capabilities?.marks && capabilities?.export)} runError={run.error} />
            )}
          </div>
        ))}
      </aside>
      {/* 拖着那条边时网页多让出的那一截(见 columnWidth 的 DRAG_GUARD):铺一块底色,光标照样是左右拉的 */}
      {column.dragging && (
        <div
          {...APP_CHROME}
          aria-hidden
          data-workbench-drag-guard=""
          style={{ top: barHeight, right: column.width, width: DRAG_GUARD }}
          className="fixed bottom-0 z-[200] cursor-col-resize bg-panel-inset"
        />
      )}
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
