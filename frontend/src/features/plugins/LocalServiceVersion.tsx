/**
 * 让 Mosael 装的那一份换版本(ADR 0041 §4「更新、回滚」):连接页「本机服务」里的「版本」一行。
 *
 * - 当前版本、**上游最新**(联网查,查不到就说查不到)、上次检查、能不能升;能升就有「更新到 x」,
 *   更新过的有「回到上一版 y」(上一版留一步,下一次更新时换掉);
 * - **「已经是最新的」只在当前 == 上游最新时说**;查不到(离线 / 限流 / 404)时说明原因,内置表里还有更新就照给按钮;
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
import { useI18n, usePreferences } from "@/app/preferences";
import { ConfirmDialog } from "@/components/app/modals";
import { SettingsRow } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { LocalServiceLogDialog, localServiceKey, machineKey } from "@/features/plugins/localServiceStatus";

export const versionsKey = (instanceId: string) => ["local-service-versions", instanceId] as const;

/**
 * 这一份本机服务装着的版本(以及上游最新、能不能升)。连接页那一整行和插件页页头那一行
 * **读的是同一份缓存**(同一个 key、同一趟请求):插件页上多看一眼版本不该再多问一次上游。
 */
export function useLocalServiceVersions(instanceId: string, enabled = true) {
  return useQuery({
    queryKey: versionsKey(instanceId),
    queryFn: () => getLocalServiceVersions(instanceId),
    enabled,
    retry: false,
  });
}

/** 版本号按数字段比(`0.41.0` > `0.39.0`);认不出的按 0 算,只用来决定这句话怎么说。 */
function newer(first: string, second: string): boolean {
  const left = first.split(/[^0-9]+/).filter(Boolean).map(Number);
  const right = second.split(/[^0-9]+/).filter(Boolean).map(Number);
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const one = left[index] ?? 0;
    const other = right[index] ?? 0;
    if (one !== other) return one > other;
  }
  return false;
}

type Change = "update" | "rollback";

export function ManagedVersion({ instanceId, service }: { instanceId: string; service: LocalService }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const run = service.install ?? null;
  const versions = useLocalServiceVersions(instanceId, service.can_manage);
  //: 一次装 / 换版本落定了:重读版本(换好了、换回去了、半截停下了)
  const settledAt = run && run.state !== "installing" ? run.finished_at : null;
  React.useEffect(() => {
    if (settledAt) void qc.invalidateQueries({ queryKey: versionsKey(instanceId) });
  }, [settledAt, qc, instanceId]);
  const [confirming, setConfirming] = React.useState<Change | null>(null);
  const [logsOpen, setLogsOpen] = React.useState(false);
  const found = versions.data;
  const change = useMutation({
    mutationFn: (kind: Change) => (kind === "update"
      ? updateLocalService(instanceId, found?.update ?? "", found?.source === "upstream" ? found.upstream?.tag ?? "" : "")
      : rollbackLocalService(instanceId)),
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
  const up = found?.upstream;
  const unknown = !!up && up.status !== "ok";
  const upToDate = !!found?.current && up?.status === "ok" && up.version === found.current;
  const ahead = !!found?.current && up?.status === "ok" && !upToDate && !found.update && !!up.version && newer(found.current, up.version);
  const behind = !!found?.current && up?.status === "ok" && !upToDate && !found.update && !!up.version && newer(up.version, found.current);
  const reason = up?.message || t("localServiceVersionReasonUnknown");
  const describe = (): string => {
    if (versions.isPending) return t("localServiceVersionChecking");
    if (versions.error) return (versions.error as Error).message;
    if (!found?.current) return "";
    if (found.update && found.source === "upstream") {
      return t("localServiceVersionAvailable").replace("{current}", found.current).replace("{latest}", found.update);
    }
    if (found.update && up?.status === "ok") {
      return t("localServiceVersionOtherUpdate").replace("{current}", found.current).replace("{latest}", up.version)
        .replace("{version}", found.update);
    }
    if (found.update) {
      return t("localServiceVersionPinned").replace("{current}", found.current).replace("{version}", found.update);
    }
    if (unknown) return t("localServiceVersionUnknown").replace("{current}", found.current);
    if (upToDate) return t("localServiceVersionLatest").replace("{current}", found.current);
    if (ahead) {
      return t("localServiceVersionAhead").replace("{current}", found.current).replace("{latest}", up?.version ?? "");
    }
    if (behind) {
      return t("localServiceVersionUpstreamNewer").replace("{current}", found.current).replace("{latest}", up?.version ?? "");
    }
    return t("localServiceVersionUnknown").replace("{current}", found.current);
  };
  const description = describe();
  const facts = found?.current ? (
    <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1" data-testid="localServiceVersionFacts">
      <span>{t("localServiceVersionFactCurrent").replace("{version}", found.current)}</span>
      <span>
        {up?.status === "ok" && up.version
          ? t("localServiceVersionFactUpstream").replace("{version}", up.version)
          : t("localServiceVersionFactUpstreamUnknown")}
      </span>
      <span>
        {up?.checked_at
          ? t("localServiceVersionFactChecked").replace("{time}", new Date(up.checked_at).toLocaleString(locale))
          : t("localServiceVersionNotChecked")}
      </span>
      <span>
        {found.update
          ? t("localServiceVersionFactUpdate").replace("{version}", found.update)
          : t("localServiceVersionFactNoUpdate")}
      </span>
    </span>
  ) : null;
  const notesText = up?.status === "ok" && up.notes
    ? t("localServiceVersionReleaseNotes").replace("{notes}", up.notes)
    : "";
  const notes = notesText ? (
    <Truncate text={notesText} lines={2} className="mt-1" data-testid="localServiceVersionNotes">
      {notesText}
    </Truncate>
  ) : null;
  const lastChange = run && run.kind !== "install" && run.state !== "installing" ? run : null;
  return (
    <>
      <SettingsRow
        id={`local-service-version-${instanceId}`}
        label={t("localServiceVersion")}
        description={<>{description}{facts}{notes}</>}
      >
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
      {unknown && (
        <p role="status" className="m-0 flex items-start gap-2 pb-4 text-ui-sm text-warning">
          <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0" />
          <span className="min-w-0">{t("localServiceVersionCheckFailed").replace("{reason}", reason)}</span>
        </p>
      )}
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

/**
 * 插件页页头那一行轻量版本(「更新、回滚」的摘要,ADR 0041 §4)。
 *
 * 整块 {@link ManagedVersion}(更新 / 回到上一版 / 先确认 / 发布说明 / 日志)在连接里展开才有地方摆;
 * 插件页上看一眼版本不该先展开连接。这一行读的是**同一个查询**(见 {@link useLocalServiceVersions}):
 * 当前版本 + 能升到哪一版;点「有新版本」去连接里那一行 —— 真正的动作(和它需要的确认)只有那一个控件。
 *
 * `readable` 由调用方按本机服务那一行定(让 Mosael 装的、装好了、当前账号能读,才有版本可读)。
 * 读不到时说「不是 Mosael 装的这一份」,**不留空白、不写 0**;上游查不到时说查不到和原因,
 * **绝不说「已经是最新的」**(ADR 0073)。
 */
export function PluginServiceVersionFact({
  instanceId,
  title,
  readable,
  onOpen,
}: {
  instanceId: string;
  title: string;
  /** 这一份是不是读得出「装着哪个版本」。 */
  readable: boolean;
  /** 点「有新版本」:去连接里那一行(展开、滚到「版本」)。 */
  onOpen: () => void;
}) {
  const t = useI18n();
  const versions = useLocalServiceVersions(instanceId, readable);
  if (!readable) {
    return <span data-service-version="">{t("pluginServiceVersionNotManaged")}</span>;
  }
  if (versions.isPending) return null;
  if (versions.error) {
    return (
      <span data-service-version="" className="text-warning">
        {t("pluginServiceVersionUnreadable").replace("{reason}", versions.error.message)}
      </span>
    );
  }
  const found = versions.data;
  if (!found?.current) {
    return <span data-service-version="">{t("pluginServiceVersionNotManaged")}</span>;
  }
  const upstream = found.upstream;
  return (
    <span data-service-version="" className="inline-flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="tabular-nums">
        {t("pluginServiceVersionCurrent").replace("{title}", title).replace("{version}", found.current)}
      </span>
      {upstream && upstream.status !== "ok" ? (
        <span className="text-warning">
          {t("pluginServiceVersionUnknown").replace("{reason}", upstream.message || t("localServiceVersionReasonUnknown"))}
        </span>
      ) : found.update ? (
        <Hint label={t("pluginServiceVersionJump")}>
          <Button variant="inline" className="text-warning" onClick={onOpen}>
            {t("pluginServiceVersionUpdate").replace("{version}", found.update)}
          </Button>
        </Hint>
      ) : null}
    </span>
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
