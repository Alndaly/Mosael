/**
 * 让 Mosael 装的那一份换版本(ADR 0041 §4「更新、回滚」):连接页「本机服务」里的「版本」一行。
 *
 * - 装着哪个版本;插件钉死了更新的就有「更新到 x」,更新过的有「回到上一版 y」(上一版留一步,下一次更新时换掉);
 * - 上一次换版本被强行打断(半新半旧,起不来):说清楚,「换回 y」把它收拾好;
 * - 两样都先确认(会停下它、正在跑的任务会中断;更新还会下载新代码并运行),之后的进度和安装是同一块(第几步、字节、取消、日志);
 * - 做完了在这一行下面说结果:换好了、没成(原因 —— 试起没通过时已经换回去了 —— 和日志)、取消了。
 *
 * 只给部署管理员(后端也拦);别人看不到这一行。
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleArrowUp, CircleCheck, FileText, TriangleAlert, Undo2 } from "lucide-react";
import { toast } from "sonner";

import { getLocalServiceVersions, rollbackLocalService, updateLocalService, type LocalService } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog } from "@/components/app/modals";
import { SettingsRow } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { LocalServiceLogDialog, localServiceKey, machineKey } from "@/features/plugins/localServiceStatus";

export const versionsKey = (instanceId: string) => ["local-service-versions", instanceId] as const;

type Change = "update" | "rollback";

export function ManagedVersion({ instanceId, service }: { instanceId: string; service: LocalService }) {
  const t = useI18n();
  const qc = useQueryClient();
  const run = service.install ?? null;
  const versions = useQuery({
    queryKey: versionsKey(instanceId),
    queryFn: () => getLocalServiceVersions(instanceId),
    enabled: service.can_manage,
    retry: false,
  });
  //: 一次装 / 换版本落定了:重读版本(换好了、换回去了、半截停下了)
  const settledAt = run && run.state !== "installing" ? run.finished_at : null;
  React.useEffect(() => {
    if (settledAt) void qc.invalidateQueries({ queryKey: versionsKey(instanceId) });
  }, [settledAt, qc, instanceId]);
  const [confirming, setConfirming] = React.useState<Change | null>(null);
  const [logsOpen, setLogsOpen] = React.useState(false);
  const found = versions.data;
  const change = useMutation({
    mutationFn: (kind: Change) => (kind === "update" ? updateLocalService(instanceId, found?.update ?? "") : rollbackLocalService(instanceId)),
    onSuccess: (next) => {
      setConfirming(null);
      qc.setQueryData(localServiceKey(instanceId), next);
    },
    onError: (error: Error) => {
      setConfirming(null);
      toast.error(error.message);
    },
  });
  if (!service.can_manage) return null;

  const where = t(machineKey());
  const description = versions.isPending
    ? t("localServiceVersionChecking")
    : versions.error
      ? (versions.error as Error).message
      : found?.current
        ? t(found.update ? "localServiceVersionDesc" : "localServiceVersionLatest").replace("{current}", found.current)
        : "";
  const lastChange = run && run.kind !== "install" && run.state !== "installing" ? run : null;
  return (
    <>
      <SettingsRow label={t("localServiceVersion")} description={description}>
        {found?.update && (
          <Button size="sm" loading={change.isPending && change.variables === "update"} onClick={() => setConfirming("update")}>
            <CircleArrowUp /> {t("localServiceUpdateTo").replace("{version}", found.update)}
          </Button>
        )}
        {found?.previous && (
          <Button
            variant={found.unfinished ? "default" : "outline"}
            size="sm"
            loading={change.isPending && change.variables === "rollback"}
            onClick={() => setConfirming("rollback")}
          >
            <Undo2 /> {t(found.unfinished ? "localServiceGoBackUnfinished" : "localServiceGoBack").replace("{version}", found.previous)}
          </Button>
        )}
      </SettingsRow>
      {found?.unfinished && (
        <p role="alert" className="m-0 flex items-start gap-2 pb-4 text-ui-sm text-warning">
          <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0" />
          <span className="min-w-0">{t("localServiceChangeUnfinished").replace("{version}", found.previous)}</span>
        </p>
      )}
      {lastChange && <ChangeOutcome run={lastChange} onLogs={() => setLogsOpen(true)} />}
      <ConfirmDialog
        open={confirming !== null}
        title={(confirming === "update" ? t("localServiceUpdateConfirmTitle") : t("localServiceRollbackConfirmTitle"))
          .replace("{title}", service.title)
          .replace("{version}", confirming === "update" ? found?.update ?? "" : found?.previous ?? "")
          .replace("{where}", where)}
        body={(confirming === "update" ? t("localServiceUpdateConfirmBody") : t("localServiceRollbackConfirmBody"))
          .replace(/\{title\}/g, service.title)
          .replace(/\{version\}/g, confirming === "update" ? found?.update ?? "" : found?.previous ?? "")
          .replace("{current}", found?.current ?? "")
          .replace("{directory}", service.directory)
          .replace("{where}", where)}
        confirmLabel={confirming === "update"
          ? t("localServiceUpdateTo").replace("{version}", found?.update ?? "")
          : t(found?.unfinished ? "localServiceGoBackUnfinished" : "localServiceGoBack").replace("{version}", found?.previous ?? "")}
        pending={change.isPending}
        onCancel={() => setConfirming(null)}
        onConfirm={() => confirming && change.mutate(confirming)}
      />
      {logsOpen && (
        <LocalServiceLogDialog instanceId={instanceId} title={service.title} source="install" onClose={() => setLogsOpen(false)} />
      )}
    </>
  );
}

/** 上一次换版本的结果:换好了、没成(原因和日志;试起没通过时后端已经换回去了,原因里写着)、取消了。 */
function ChangeOutcome({ run, onLogs }: { run: NonNullable<LocalService["install"]>; onLogs: () => void }) {
  const t = useI18n();
  const update = run.kind === "update";
  if (run.state === "succeeded") {
    return (
      <p role="status" className="m-0 flex items-center gap-2 pb-4 text-ui-sm">
        <CircleCheck size={14} aria-hidden className="shrink-0 text-success" />
        {t(update ? "localServiceUpdated" : "localServiceRolledBack").replace("{version}", run.target ?? "")}
      </p>
    );
  }
  if (run.state === "cancelled") {
    return (
      <p className="m-0 pb-4 text-ui-sm text-muted-foreground">
        {t(update ? "localServiceUpdateCancelled" : "localServiceRollbackCancelled")}
      </p>
    );
  }
  return (
    <div role="alert" className="grid gap-2 pb-4 text-ui-sm text-destructive">
      <span className="font-medium">
        {t(update ? "localServiceUpdateFailed" : "localServiceRollbackFailed").replace("{version}", run.target ?? "")}
      </span>
      <span className="whitespace-pre-wrap break-words">{run.error}</span>
      <div>
        <Button variant="outline" size="sm" onClick={onLogs}>
          <FileText /> {t("localServiceInstallLog")}
        </Button>
      </div>
    </div>
  );
}
