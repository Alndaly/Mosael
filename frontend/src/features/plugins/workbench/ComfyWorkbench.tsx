import React from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, Boxes, ListChecks, PanelRightClose, PanelRightOpen, Play, Save, TriangleAlert } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { LoadingState } from "@/components/layout/LoadingState";
import { APP_CHROME } from "@/components/ui/appChrome";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint, HintRegion } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { ComfyNavigationSwitch } from "@/features/plugins/ComfyNavigationSwitch";
import { AppPanel } from "@/features/plugins/workbench/AppPanel";
import { MissingPanel } from "@/features/plugins/workbench/MissingPanel";
import { ModelsPanel } from "@/features/plugins/workbench/ModelsPanel";
import { RunPanel, useCanvasRun } from "@/features/plugins/workbench/RunPanel";
import { savedPath } from "@/features/plugins/workbench/workbenchLogic";
import { PanelNote } from "@/features/plugins/workbench/workbenchParts";
import { useWorkbench, workbenchCall } from "@/features/plugins/workbench/workbenchSession";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { WINDOW_CHROME_INSET } from "@/lib/windowChrome";
import { cn } from "@/lib/utils";

/** 右边那一列多宽:网页右侧让出这么宽(主进程 setShellInset,最多让出一半)。 */
export const WORKBENCH_COLUMN_WIDTH = 420;

const TABS = ["models", "missing", "app", "run"] as const;
type Tab = (typeof TABS)[number];
const BAR_REGION = { side: "bottom" as const };
//: 等桥多久才说「连不上」:第一次打开要下整套前端,慢的机器上要好几十秒
const BRIDGE_PATIENCE_MS = 45_000;
const COLUMN_REGION = { side: "left" as const };

/**
 * ComfyUI 工作台(ADR 0038 §3):全屏,左边整块是那台 ComfyUI 自己的画布(内嵌视图,每个自定义节点照常能用),Mosael 的东西
 * 都画在它旁边 —— 顶栏(连接、工作流名、有没有没存的改动、操控方式、「保存」「运行」)和右边能收起的一列(模型库、缺失项、应用、
 * 运行与结果)。网页是原生视图、盖在一切 DOM 上:顶栏占着视图上沿那 56px,右边那一列开着时视图让出那么宽;要确认的事就地确认。
 *
 * 和画布通话的是主进程注入的桥(只拉不推,见 electron/publish/comfyWorkbench);这版前端缺了哪一样,那一处就说「这版 ComfyUI
 * 前端不支持 X」,画布照常是一个能用的 ComfyUI。
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
  React.useEffect(() => {
    void window.mosaelPageTools?.setInset(columnOpen ? WORKBENCH_COLUMN_WIDTH : 0);
  }, [columnOpen]);
  React.useEffect(() => () => void window.mosaelPageTools?.setInset(0), []);

  if (!target) return null;
  const capabilities = state?.capabilities ?? null;
  const path = savedPath(state);
  const workflowName = state?.workflow ? state.workflow.name || path || t("workbenchUnsaved") : "";
  const modified = Boolean(state?.workflow?.modified);
  const canSave = capabilities?.save !== false;
  const canRun = Boolean(capabilities?.export) && Boolean(path);
  const runBlocked = !state ? t("workbenchConnecting")
    : !capabilities?.export ? t("workbenchUnsupported").replace("{what}", t("workbenchCapExport"))
    : !path ? t("workbenchRunNeedsSave") : undefined;

  const startRun = () => {
    setTab("run");
    if (!columnOpen) setOpen("open");
    run.mutate(path);
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
          <button
            type="button"
            data-publish-back=""
            className="[-webkit-app-region:no-drag] inline-flex shrink-0 cursor-pointer items-center gap-[5px] whitespace-nowrap rounded-md border border-border bg-transparent px-2.5 py-[5px] text-ui-sm text-foreground hover:bg-secondary"
            onClick={() => void window.mosaelPublish?.hideView()}
          >
            <ArrowLeft size={14} /> {t("publishBackToApp")}
          </button>
        </Hint>
        <div className="flex min-w-0 flex-1 items-baseline gap-1.5 px-1">
          <span className="shrink-0 text-ui-xs font-medium text-primary">{t("workbenchTitle")}</span>
          <Truncate className="min-w-0 shrink text-ui-xs text-muted-foreground">{target.instanceName}</Truncate>
          {workflowName && <span aria-hidden className="text-ui-xs text-muted-foreground">/</span>}
          {workflowName && (
            <h1 className="m-0 min-w-0 text-ui-sm font-semibold text-foreground">
              <Truncate>{workflowName}</Truncate>
            </h1>
          )}
          {modified && (
            <Hint label={t("workbenchUnsavedChanges")}>
              <span role="img" aria-label={t("workbenchUnsavedChanges")} className="inline-block size-2 shrink-0 self-center rounded-full bg-warning" />
            </Hint>
          )}
          {!state && <span className="shrink-0 text-ui-xs text-muted-foreground">{t("workbenchConnecting")}</span>}
        </div>
        <ComfyNavigationSwitch connectionId={target.instanceId} />
        <Hint label={canSave ? t("workbenchSaveHint") : t("workbenchUnsupported").replace("{what}", t("workbenchCapSave"))}>
          <Button variant="outline" size="sm" className="[-webkit-app-region:no-drag] shrink-0" disabled={!state || !canSave}
                  onClick={() => void save()}>
            <Save size={13} />
            {t("workbenchSave")}
          </Button>
        </Hint>
        <Hint label={t("workbenchRunHintShort")} disabledReason={runBlocked}>
          <Button size="sm" className="[-webkit-app-region:no-drag] shrink-0" disabled={!canRun} loading={run.isPending}
                  onClick={startRun}>
            <Play size={13} />
            {t("workbenchRun")}
          </Button>
        </Hint>
        <IconButton
          variant="ghost"
          size="icon-sm"
          className="[-webkit-app-region:no-drag] shrink-0"
          label={columnOpen ? t("workbenchColumnHide") : t("workbenchColumnShow")}
          aria-expanded={columnOpen}
          onClick={() => setOpen(columnOpen ? "closed" : "open")}
        >
          {columnOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
        </IconButton>
      </HintRegion.Provider>
    </div>
  );

  const column = columnOpen ? (
    <HintRegion.Provider value={COLUMN_REGION}>
      <aside
        {...APP_CHROME}
        data-comfy-workbench-column=""
        aria-label={t("workbenchColumn")}
        style={{ top: barHeight, width: WORKBENCH_COLUMN_WIDTH }}
        className="fixed bottom-0 right-0 z-[200] flex flex-col border-l border-border bg-panel"
      >
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
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {saveNote && <p role="alert" className="m-0 mb-3 text-ui-xs text-destructive">{saveNote}</p>}
          {!state && (stuck
            ? <PanelNote tone="warning">{t("workbenchBridgeMissing")}</PanelNote>
            : <LoadingState label={t("workbenchConnecting")} className="h-auto py-10" />)}
          {state && TABS.filter((one) => visited.has(one)).map((one) => (
            <div key={one} role="tabpanel" id={`comfy-workbench-panel-${one}`} aria-labelledby={`comfy-workbench-tab-${one}`}
                 hidden={tab !== one}>
              {one === "models" && <ModelsPanel target={target} node={state?.selection.node ?? null} capabilities={capabilities} />}
              {one === "missing" && <MissingPanel target={target} canExport={capabilities ? capabilities.export : false} />}
              {one === "app" && (
                <AppPanel target={target} canExport={capabilities ? capabilities.export : false}
                          canMark={capabilities ? capabilities.marks : false} />
              )}
              {one === "run" && (
                <RunPanel target={target} runs={runs} events={events} canMark={Boolean(capabilities?.marks && capabilities?.export)}
                          runError={run.error} />
              )}
            </div>
          ))}
        </div>
      </aside>
    </HintRegion.Provider>
  ) : null;

  return (
    <>
      {bar}
      {column && createPortal(column, document.body)}
    </>
  );
}
