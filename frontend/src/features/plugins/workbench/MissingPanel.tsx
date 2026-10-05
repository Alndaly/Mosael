import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Boxes, CheckCircle2, CircleAlert, RefreshCcw } from "lucide-react";

import {
  inspectWorkflowImport,
  rebootWorkflowServer,
  startModelDownload,
  startNodeInstall,
  type WorkflowImport,
  type WorkflowNodePack,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { modelBaseName } from "@/components/generation/ModelThumb";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { Truncate } from "@/components/ui/truncate";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { InlineConfirm, PanelNote, useJobWatch, useOnJobDone } from "@/features/plugins/workbench/workbenchParts";
import { WorkbenchCallError, exportCanvas, workbenchCall, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";

type Missing = Pick<WorkflowImport, "missing_nodes" | "missing_models">;

/**
 * 工作台的「缺失项」面板(ADR 0038 §6):经桥导出画布上**现在**这张(含没存的),让插件认一遍(和导入同一个 `inspect`,不改那台
 * 机器)—— 缺的节点(出自哪个节点包、装没装)和缺的模型(工作流里写的下载地址)放在一张清单上。一键补:节点包经 ComfyUI-Manager
 * 装(装完要重启 ComfyUI 才加载,重启前提醒先保存),模型下到那个目录(下完刷新下拉)。每一样都先就地确认、写明哪台服务器。
 */
export function MissingPanel({ target, canExport }: { target: WorkbenchTarget; canExport: boolean }) {
  const t = useI18n();
  const qc = useQueryClient();
  const check = useMutation({
    mutationFn: async (): Promise<Missing> => {
      const exported = await exportCanvas();
      return inspectWorkflowImport(target.instanceId, { text: JSON.stringify(exported.workflow) });
    },
  });
  const run = check.mutate;
  React.useEffect(() => {
    if (canExport) run();
  }, [canExport, run]);
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
  return (
    <div className="grid gap-4">
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
      {check.isPending && !missing && <LoadingState label={t("workbenchMissingChecking")} className="h-auto py-6" />}
      {missing && nodes.length === 0 && models.length === 0 && (
        <p className="m-0 flex items-center gap-1.5 text-ui-sm text-success">
          <CheckCircle2 size={14} aria-hidden />
          {t("workbenchMissingNone")}
        </p>
      )}
      {nodes.length > 0 && (
        <section aria-label={t("workbenchMissingNodes")} className="grid gap-2">
          <h3 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
            <CircleAlert size={13} aria-hidden className="text-warning" />
            {t("workbenchMissingNodes")}
            <span className="text-ui-xs font-normal text-muted-foreground">{nodes.length}</span>
          </h3>
          <ul className="m-0 grid list-none gap-2 p-0">
            {nodes.map((node) => (
              <li key={node.type} className="grid gap-1.5 rounded-lg border border-border p-2">
                <span className="flex min-w-0 items-center gap-1.5 text-ui-xs">
                  <Truncate className="font-medium text-foreground">{node.type}</Truncate>
                  {(node.count ?? 1) > 1 && <span className="shrink-0 text-muted-foreground">×{node.count}</span>}
                </span>
                {(node.packs ?? []).length === 0 ? (
                  <span className="text-ui-xs text-muted-foreground">{t("workbenchMissingNoPack")}</span>
                ) : (
                  (node.packs ?? []).map((pack) => (
                    <PackRow key={pack.id} target={target} pack={pack} onInstalled={() => setInstalled(true)} />
                  ))
                )}
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
                        url={model.url ?? ""} onDone={() => run()} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/** 一个节点包:装没装、「装上」(就地确认)、装的进度。 */
function PackRow({ target, pack, onInstalled }: { target: WorkbenchTarget; pack: WorkflowNodePack; onInstalled: () => void }) {
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
        <Truncate className="min-w-0 flex-1">{t("workbenchMissingFromPack").replace("{name}", pack.title)}</Truncate>
        {pack.installed ? (
          <CatalogBadge tone="muted">{t("workbenchMissingInstalledNotLoaded")}</CatalogBadge>
        ) : !jobId && !asking ? (
          <Button variant="outline" size="xs" className="shrink-0" onClick={() => setAsking(true)}
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
      {jobId && (
        <PanelNote tone={status === "failed" ? "error" : "info"}>
          {status === "succeeded" ? t("workbenchInstallDone")
            : status === "failed" ? job.data?.error || t("workbenchInstallFailed")
            : `${t("workbenchInstalling")} ${job.data?.message ?? ""}`}
        </PanelNote>
      )}
    </div>
  );
}

/** 一个缺的模型:工作流里写了下载地址就「下载」(就地确认),没写就说去模型库面板贴链接。 */
function ModelRow({ target, folder, name, url, onDone }: {
  target: WorkbenchTarget;
  folder: string;
  name: string;
  url: string;
  onDone: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [asking, setAsking] = React.useState(false);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJobWatch(jobId);
  useOnJobDone(job.data, (done) => {
    if (done.status !== "succeeded") return;
    void qc.invalidateQueries({ queryKey: ["model-library", target.instanceId] });
    void workbenchCall({ op: "refreshCombos" }).finally(onDone);
  });
  const start = useMutation({
    mutationFn: () => startModelDownload(target.instanceId, { workspace_id: target.workspaceId, url, folder, filename: modelBaseName(name) }),
    onSuccess: (created) => {
      setAsking(false);
      setJobId(created.id);
    },
  });
  const status = job.data?.status;
  return (
    <li className="grid gap-1.5 rounded-lg border border-border p-2 text-ui-xs">
      <span className="flex min-w-0 items-center gap-1.5">
        <span className="grid min-w-0 flex-1 gap-0.5">
          <Truncate className="font-medium text-foreground">{modelBaseName(name)}</Truncate>
          <span className="text-muted-foreground">{folder}</span>
        </span>
        {url && !jobId && !asking && (
          <Button variant="outline" size="xs" className="shrink-0" onClick={() => setAsking(true)}
                  aria-label={t("workbenchMissingDownloadLabel").replace("{name}", modelBaseName(name))}>
            {t("workbenchMissingDownload")}
          </Button>
        )}
      </span>
      {!url && <span className="text-muted-foreground">{t("workbenchMissingNoUrl")}</span>}
      {asking && (
        <InlineConfirm
          title={t("workbenchDownloadConfirm").replace("{server}", target.instanceName).replace("{folder}", folder)
            .replace("{name}", modelBaseName(name))}
          body={url}
          confirmLabel={t("workbenchDownloadStart")}
          pending={start.isPending}
          onCancel={() => setAsking(false)}
          onConfirm={() => start.mutate()}
        />
      )}
      {start.isError && <PanelNote tone="error">{errorText(start.error)}</PanelNote>}
      {jobId && (
        <PanelNote tone={status === "failed" ? "error" : "info"}>
          {status === "succeeded" ? t("workbenchDownloadDone")
            : status === "failed" ? job.data?.error || t("workbenchDownloadFailed")
            : `${t("workbenchDownloading")} ${job.data?.message ?? ""}`}
        </PanelNote>
      )}
    </li>
  );
}
