import React from "react";
import { FailureCard, failureFields } from "@/components/failure/FailureCard";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, CheckCircle2, CircleAlert, Crosshair, ExternalLink, RefreshCcw } from "lucide-react";

import {
  getWorkflowLibrary,
  inspectWorkflowImport,
  rebootWorkflowServer,
  startNodeInstall,
  type WorkflowImport,
  type WorkflowNodePack,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { modelBaseName } from "@/components/generation/ModelThumb";
import { Button } from "@/components/ui/button";
import { Truncate } from "@/components/ui/truncate";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { ModelDownload } from "@/features/plugins/workbench/ModelDownload";
import {
  missingByPack,
  nodesOfType,
  nodesUsingModel,
  packPage,
  type CanvasSpot,
} from "@/features/plugins/workbench/workbenchLogic";
import { InlineConfirm, PANEL_ROOT, PanelEmpty, PanelLoading, PanelNote, useJobWatch, useOnJobDone } from "@/features/plugins/workbench/workbenchParts";
import { WorkbenchCallError, exportCanvas, workbenchCall, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";
import { cn } from "@/lib/utils";

type Missing = Pick<WorkflowImport, "missing_nodes" | "missing_models"> & { workflow: Record<string, unknown> };
type MissingNode = NonNullable<WorkflowImport["missing_nodes"]>[number];

/** 图改了之后等多久再重新检查(最后一下改动之后):连着拖、连着改值时不一下一问。 */
export const RECHECK_DELAY_MS = 800;

/**
 * 工作台的「缺失项」面板(ADR 0038 §6):经桥导出画布上**现在**这张(含没存的),让插件认一遍(和导入同一个 `inspect`,不改那台
 * 机器)—— 缺的节点(出自哪个节点包、装没装)和缺的模型放在一张清单上。
 *
 * - **跟着画布走**:换了一张工作流(面板按 `workflow.key` 重挂)就从头检查;同一张里改了图(`revision` 变了),最后一下改动
 *   之后 `RECHECK_DELAY_MS` 自己重新检查一次(只在这个页签开着时;切回来时图改过也查)。「重新检查」照样在。
 * - **定位**:每一项都能在画布上找到用它的那个节点(选中、移到中间;在子图里的先进子图,这版前端进不了就说在哪张子图里);
 *   好几个节点都用着同一个,点一下换下一个。
 * - **补**:节点包按包分组、一组一个「安装」(经 ComfyUI-Manager,装完要重启才加载,重启前提醒先保存);模型写了下载地址就
 *   一键下载,没写就「找下载地址」(见 ModelDownload)。每一样都先就地确认、写明哪台服务器;下完、装完自己重新检查。
 */
export function MissingPanel({
  target,
  capabilities,
  active,
  revision,
}: {
  target: WorkbenchTarget;
  capabilities: ComfyWorkbenchState["capabilities"] | null;
  active: boolean;
  revision: number;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const canExport = capabilities ? capabilities.export : false;
  const canLocate = Boolean(capabilities?.locate);
  const followsEdits = Boolean(capabilities?.changes);
  const check = useMutation({
    mutationFn: async (): Promise<Missing> => {
      const exported = await exportCanvas();
      const found = await inspectWorkflowImport(target.instanceId, { text: JSON.stringify(exported.workflow) });
      return { missing_nodes: found.missing_nodes, missing_models: found.missing_models, workflow: exported.workflow };
    },
  });
  const mutate = check.mutate;
  //: 上一次检查时图是第几回的样子;图又改了(而且停下来了)才再查
  const latest = React.useRef(revision);
  const checkedAt = React.useRef<number | null>(null);
  React.useEffect(() => {
    latest.current = revision;
  }, [revision]);
  const run = React.useCallback(() => {
    checkedAt.current = latest.current;
    mutate();
  }, [mutate]);
  React.useEffect(() => {
    if (canExport) run();
  }, [canExport, run]);
  React.useEffect(() => {
    if (!canExport || !followsEdits || !active || checkedAt.current === null || checkedAt.current === revision) return;
    const timer = setTimeout(run, RECHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [canExport, followsEdits, active, revision, run]);
  //: 这台 ComfyUI 有没有 ComfyUI-Manager(没有就认不出节点包、也装不了):工作流库报的,和工作流库同一份缓存
  const library = useQuery({
    queryKey: ["workflow-library", target.instanceId, target.workspaceId],
    queryFn: () => getWorkflowLibrary(target.instanceId, target.workspaceId),
    staleTime: 60_000,
    retry: false,
  });
  const noManager = library.data ? !library.data.manager?.version : false;
  const [installed, setInstalled] = React.useState(false);
  const [restartAsk, setRestartAsk] = React.useState(false);
  const restart = useMutation({
    mutationFn: () => rebootWorkflowServer(target.instanceId),
    onSuccess: () => {
      setRestartAsk(false);
      setInstalled(false);
      invalidatePluginDependents(qc);
      void qc.invalidateQueries({ queryKey: ["workflow-library", target.instanceId] });
      void qc.invalidateQueries({ queryKey: ["model-library", target.instanceId] });
      run();
    },
  });

  if (!canExport) return <PanelNote tone="warning">{t("workbenchUnsupported").replace("{what}", t("workbenchCapExport"))}</PanelNote>;
  const missing = check.data;
  const nodes = missing?.missing_nodes ?? [];
  const models = missing?.missing_models ?? [];
  const groups = missingByPack(nodes);
  const workflow = missing?.workflow;
  return (
    <div className={cn(PANEL_ROOT, "gap-4")}>
      <div className="flex items-center justify-between gap-2">
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workbenchMissingHint")}</p>
        <Button variant="outline" size="xs" className="shrink-0" loading={check.isPending} onClick={() => run()}>
          <RefreshCcw size={12} />
          {t("workbenchMissingCheck")}
        </Button>
      </div>
      {check.isError && (
        <PanelNote tone="error">
          {check.error instanceof WorkbenchCallError ? t("workbenchCallFailed").replace("{why}", check.error.message) : errorText(check.error)}
        </PanelNote>
      )}
      {check.isPending && !missing && <PanelLoading label={t("workbenchMissingChecking")} />}
      {missing && nodes.length === 0 && models.length === 0 && (
        <PanelEmpty icon={CheckCircle2} tone="success">{t("workbenchMissingNone")}</PanelEmpty>
      )}
      {nodes.length > 0 && (
        <section aria-label={t("workbenchMissingNodes")} className="grid gap-2">
          <h3 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
            <CircleAlert size={13} aria-hidden className="text-warning" />
            {t("workbenchMissingNodes")}
            <span className="text-ui-xs font-normal text-muted-foreground">{nodes.length}</span>
          </h3>
          {noManager && <PanelNote tone="warning">{t("workbenchMissingNoManager")}</PanelNote>}
          <ul className="m-0 grid list-none gap-2 p-0">
            {groups.map((group) => (
              <li key={group.key} data-pack-group={group.packs.map((one) => one.id).join(" ") || "none"}
                  className="grid gap-2 rounded-lg border border-border p-2">
                {group.packs.length === 0 ? (
                  <span className="text-ui-xs text-muted-foreground">{t("workbenchMissingNoPack")}</span>
                ) : (
                  group.packs.map((pack) => (
                    <PackRow key={pack.id} target={target} pack={pack} alternatives={group.packs.length > 1}
                             onInstalled={() => {
                               setInstalled(true);
                               run();
                             }} />
                  ))
                )}
                <ul aria-label={t("workbenchMissingTypes")} className="m-0 grid list-none gap-1 p-0">
                  {group.nodes.map((node) => (
                    <NodeTypeRow key={node.type} node={node} spots={workflow ? nodesOfType(workflow, node.type) : []}
                                 canLocate={canLocate} />
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </section>
      )}
      {installed && (
        restartAsk ? (
          <InlineConfirm
            title={t("workbenchRestartTitle").replace("{server}", target.instanceName)}
            body={t("workbenchRestartBody")}
            confirmLabel={t("workbenchRestartConfirm")}
            pending={restart.isPending}
            onCancel={() => setRestartAsk(false)}
            onConfirm={() => restart.mutate()}
          />
        ) : (
          <PanelNote tone="warning" action={
            <Button variant="outline" size="xs" className="shrink-0" onClick={() => setRestartAsk(true)}>{t("workbenchRestart")}</Button>
          }>
            {t("workbenchRestartNeeded")}
          </PanelNote>
        )
      )}
      {restart.isError && <PanelNote tone="error">{errorText(restart.error)}</PanelNote>}
      {models.length > 0 && (
        <section aria-label={t("workbenchMissingModels")} className="grid gap-2">
          <h3 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
            <Boxes size={13} aria-hidden className="text-warning" />
            {t("workbenchMissingModels")}
            <span className="text-ui-xs font-normal text-muted-foreground">{models.length}</span>
          </h3>
          <ul className="m-0 grid list-none gap-2 p-0">
            {models.map((model) => (
              <ModelRow key={`${model.folder}/${model.name}`} target={target} folder={model.folder} name={model.name}
                        url={model.url ?? ""} spots={workflow ? nodesUsingModel(workflow, model.name) : []} canLocate={canLocate}
                        canRefresh={capabilities?.refreshCombos !== false} onDone={run} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/**
 * 「定位」:在画布上选中用它的那个节点、移到中间;好几个节点都用着它,点一下换下一个(写着第几处)。在子图里而这版前端进不了
 * 子图,就说在哪张子图里。
 */
function useLocate(spots: readonly CanvasSpot[]) {
  const t = useI18n();
  const [at, setAt] = React.useState(-1);
  const [note, setNote] = React.useState("");
  const locate = async () => {
    if (spots.length === 0) return;
    const next = (at + 1) % spots.length;
    const spot = spots[next];
    setAt(next);
    setNote("");
    const result = await workbenchCall({ op: "locate", node: spot.node, subgraph: spot.subgraph });
    if (result.ok) return;
    setNote(result.error === "inSubgraph" ? t("workbenchLocateInSubgraph").replace("{name}", spot.subgraphName)
      : result.error === "noNode" ? t("workbenchLocateGone")
      : t("workbenchCallFailed").replace("{why}", "message" in result && result.message ? result.message : result.error));
  };
  return { at, note, locate };
}

function LocateButton({ label, spots, at, onLocate }: { label: string; spots: readonly CanvasSpot[]; at: number; onLocate: () => void }) {
  const t = useI18n();
  return (
    <Button variant="ghost" size="xs" className="shrink-0" data-locate="" aria-label={t("workbenchLocateLabel").replace("{name}", label)}
            onClick={onLocate}>
      <Crosshair size={12} />
      {t("workbenchLocate")}
      {spots.length > 1 && (
        <span className="tabular-nums text-muted-foreground">
          {at < 0 ? t("workbenchLocateCount").replace("{n}", String(spots.length)) : `${at + 1}/${spots.length}`}
        </span>
      )}
    </Button>
  );
}

/** 点在卡片上(不是点在卡片里的按钮、链接、输入框上)也算「定位」。 */
const onCard = (locate: () => void) => (event: React.MouseEvent) => {
  if ((event.target as Element).closest("button, a, input, textarea, label, [role=group], [data-model-download]")) return;
  locate();
};

/** 一种缺的节点:类型、几处、定位。 */
function NodeTypeRow({ node, spots, canLocate }: { node: MissingNode; spots: CanvasSpot[]; canLocate: boolean }) {
  const { at, note, locate } = useLocate(spots);
  const can = canLocate && spots.length > 0;
  return (
    <li className={cn("grid gap-1 rounded-md px-1 py-0.5", can && "cursor-pointer hover:bg-secondary")}
        onClick={can ? onCard(() => void locate()) : undefined}>
      <span className="flex min-h-7 min-w-0 items-center gap-1.5 text-ui-xs">
        <Truncate className="min-w-0 flex-1 font-medium text-foreground">{node.type}</Truncate>
        {(node.count ?? 1) > 1 && <span className="shrink-0 text-muted-foreground">×{node.count}</span>}
        {can && <LocateButton label={node.type} spots={spots} at={at} onLocate={() => void locate()} />}
      </span>
      {note && <span role="status" className="text-ui-2xs text-muted-foreground">{note}</span>}
    </li>
  );
}

/** 一个节点包:主页、装没装、「安装」(就地确认)、装的进度。几个包都可能出这种节点时,写明「出自其中一个」。 */
function PackRow({
  target,
  pack,
  alternatives,
  onInstalled,
}: {
  target: WorkbenchTarget;
  pack: WorkflowNodePack;
  alternatives: boolean;
  onInstalled: () => void;
}) {
  const t = useI18n();
  const [asking, setAsking] = React.useState(false);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJobWatch(jobId);
  useOnJobDone(job.data, (done) => {
    if (done.status === "succeeded") onInstalled();
  });
  const start = useMutation({
    mutationFn: () => startNodeInstall(target.instanceId, { workspace_id: target.workspaceId, packs: [pack.id] }),
    onSuccess: (created) => {
      setAsking(false);
      setJobId(created.id);
    },
  });
  const status = job.data?.status;
  return (
    <div className="grid gap-1.5">
      <span className="flex min-w-0 items-center gap-1.5 text-ui-xs text-muted-foreground">
        <Truncate className="min-w-0 flex-1">
          {t(alternatives ? "workbenchMissingFromOneOf" : "workbenchMissingFromPack").replace("{name}", pack.title)}
        </Truncate>
        <a href={packPage(pack.id)} target="_blank" rel="noreferrer noopener" aria-label={t("workbenchMissingPackPage").replace("{name}", pack.title)}
           className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground">
          <ExternalLink size={12} aria-hidden />
        </a>
        {pack.installed ? (
          <CatalogBadge tone="muted">{t("workbenchMissingInstalledNotLoaded")}</CatalogBadge>
        ) : !jobId && !asking ? (
          <Button size="xs" className="shrink-0" onClick={() => setAsking(true)}
                  aria-label={t("workbenchMissingInstallLabel").replace("{name}", pack.title)}>
            {t("workbenchMissingInstall")}
          </Button>
        ) : null}
      </span>
      {asking && (
        <InlineConfirm
          title={t("workbenchInstallTitle").replace("{server}", target.instanceName).replace("{name}", pack.title)}
          body={t("workbenchInstallBody")}
          confirmLabel={t("workbenchMissingInstall")}
          pending={start.isPending}
          onCancel={() => setAsking(false)}
          onConfirm={() => start.mutate()}
        />
      )}
      {start.isError && <PanelNote tone="error">{errorText(start.error)}</PanelNote>}
      {jobId && status === "failed" && job.data ? (
        <FailureCard size="inline" lines={2} title={t("workbenchInstallFailed")} {...failureFields(job.data, t("workbenchInstallFailed"))} />
      ) : jobId ? (
        <PanelNote>
          {status === "succeeded" ? t("workbenchInstallDone") : `${t("workbenchInstalling")} ${job.data?.message ?? ""}`}
        </PanelNote>
      ) : null}
    </div>
  );
}

/** 一个缺的模型:名字、目录、定位;下载(工作流写了地址就一键,没写就找、或者贴链接)。下完刷新下拉、重新检查。 */
function ModelRow({ target, folder, name, url, spots, canLocate, canRefresh, onDone }: {
  target: WorkbenchTarget;
  folder: string;
  name: string;
  url: string;
  spots: CanvasSpot[];
  canLocate: boolean;
  canRefresh: boolean;
  onDone: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const { at, note, locate } = useLocate(spots);
  const can = canLocate && spots.length > 0;
  return (
    <li className={cn("grid gap-1.5 rounded-lg border border-border p-2 text-ui-xs", can && "cursor-pointer hover:border-primary/40")}
        onClick={can ? onCard(() => void locate()) : undefined}>
      <span className="flex min-w-0 items-center gap-1.5">
        <span className="grid min-w-0 flex-1 gap-0.5">
          <Truncate className="font-medium text-foreground">{modelBaseName(name)}</Truncate>
          <span className="text-muted-foreground">{folder}</span>
        </span>
        {can && <LocateButton label={modelBaseName(name)} spots={spots} at={at} onLocate={() => void locate()} />}
      </span>
      {note && <span role="status" className="text-ui-2xs text-muted-foreground">{note}</span>}
      <ModelDownload target={target} folder={folder} wanted={name} url={url}
                     doneLabel={t(canRefresh ? "workbenchDownloadDone" : "workbenchDownloadDoneManual")}
                     onDone={() => {
                       void qc.invalidateQueries({ queryKey: ["model-library", target.instanceId] });
                       void (canRefresh ? workbenchCall({ op: "refreshCombos" }) : Promise.resolve()).finally(onDone);
                     }} />
    </li>
  );
}
