import React from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { ChevronRight, CircleAlert, FileText, Info, Play, RotateCw, Square, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import {
  addLocalServiceNodes,
  createPluginInstance,
  detectLocalService,
  discoverLocalServices,
  getLocalService,
  getLocalServiceLogs,
  putLocalService,
  removeLocalService,
  restartLocalService,
  startLocalService,
  stopLocalService,
  type LocalService,
  type LocalServiceDetection,
  type LocalServiceState,
  type LocalServiceUpdate,
  type PluginInstance,
  type PluginPackage,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { CatalogBadge, type CatalogTone } from "@/components/app/CatalogDialog";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { SETTINGS_FIELD_WIDTH, SettingsRow } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { useDraftText } from "@/components/ui/draft-text";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { Hint } from "@/components/ui/tooltip";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { cn } from "@/lib/utils";

/** 本机服务的地址写进连接配置的这一格(清单格式的约定,见 mosael_formats.plugin_manifest.SERVICE_ADDRESS_FIELD)。 */
export const SERVICE_ADDRESS_FIELD = "server_url";

/** 这个连接的本机服务在缓存里的键(连接卡上的「服务器地址」也读它:本机服务的地址由宿主填,不让手改)。 */
export const localServiceKey = (instanceId: string) => ["local-service", instanceId] as const;
const detectionKey = (instanceId: string) => ["local-service-detection", instanceId] as const;

/** 还在变的两种状态按 1200 ms 问(和引擎安装同一个节奏);别的时候隔几秒看一眼 —— 运行中崩了要看得见它在重启。 */
const UNSETTLED: readonly LocalServiceState[] = ["starting", "restarting"];

export function useLocalService(instanceId: string, enabled: boolean) {
  return useQuery({
    queryKey: localServiceKey(instanceId),
    queryFn: () => getLocalService(instanceId),
    enabled,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      if (!state) return false;
      return UNSETTLED.includes(state) ? 1200 : 5000;
    },
  });
}

/**
 * 本机服务刚就绪:宿主在它停着时没刷新目录(用到时才起,见后端 host_capabilities.notify),就绪时自己刷了一遍(模型、工具)——
 * 跟着连接走的那些缓存(连接卡上的「出错了」、模型选择器)要重读。刷新在宿主那边要一点时间,过一会儿再重读一次。
 */
export function useRefreshWhenRunning(state: LocalServiceState | undefined) {
  const qc = useQueryClient();
  const previous = React.useRef(state);
  React.useEffect(() => {
    const before = previous.current;
    previous.current = state;
    if (state !== "running" || before === undefined || before === "running") return;
    invalidatePluginDependents(qc);
    const again = window.setTimeout(() => invalidatePluginDependents(qc), 3000);
    return () => window.clearTimeout(again);
  }, [state, qc]);
}

const STATE_LABEL: Record<LocalServiceState, MessageKey> = {
  stopped: "localServiceStateStopped",
  starting: "localServiceStateStarting",
  running: "localServiceStateRunning",
  restarting: "localServiceStateRestarting",
  failed: "localServiceStateFailed",
};
const STATE_TONE: Record<LocalServiceState, CatalogTone> = {
  stopped: "muted",
  starting: "primary",
  running: "success",
  restarting: "warning",
  failed: "warning",
};

/** 「附加参数」一项一个 → 一行字(带空格的一项用双引号括起来;和后端 records.split_args 是一对)。 */
export function joinArgs(args: readonly string[]): string {
  return args.map((one) => (/\s/.test(one) ? `"${one}"` : one)).join(" ");
}

/** 确认框里说「在哪台机器上运行」:桌面版是这台电脑,网页版连的是一台服务器。 */
function machineKey(): MessageKey {
  return typeof window !== "undefined" && window.mosaelDesktop ? "localServiceWhereDesktop" : "localServiceWhereServer";
}

function settle(qc: QueryClient, instanceId: string, next: LocalService | null | undefined) {
  if (next !== undefined) qc.setQueryData(localServiceKey(instanceId), next);
  // 地址(server_url)跟着变,连接卡和替宿主做事的那一侧(模型、工具)都要重读
  invalidatePluginDependents(qc);
}

/**
 * 连接页上的「本机服务」(ADR 0041):插件声明了一种本机服务(清单的 `services`)就有这一块,和是哪个插件无关。
 *
 * - 「在哪跑」:连一台服务器(只连,不管进程)/ 用我自己装的(选目录,由 Mosael 起停)/ 让 Mosael 装(下一步提供);
 * - 选目录:先确认「会在这台机器上运行这个目录里的代码」,再让插件认一遍(试跑一次),认出来、能起才存;
 * - 存好之后:状态(已停止 / 启动中 / 运行中 / 重启中 / 起不来)、启动 / 停止 / 重启、日志、端口、补装、保持运行、局域网,
 *   附加参数和端口在「高级」里。
 *
 * 建、改、起、停都要部署管理员(后端拦);别人看得到状态,控件是灰的、说明为什么。
 */
export function ConnectionLocalService({ pkg, instance }: { pkg: PluginPackage; instance: PluginInstance }) {
  const t = useI18n();
  const qc = useQueryClient();
  const declared = (pkg.services ?? [])[0];
  const query = useLocalService(instance.id, Boolean(declared));
  const service = query.data ?? null;
  const [choosing, setChoosing] = React.useState(false);
  const [confirmServer, setConfirmServer] = React.useState(false);
  const remove = useMutation({
    mutationFn: () => removeLocalService(instance.id),
    onSuccess: () => {
      setConfirmServer(false);
      setChoosing(false);
      qc.removeQueries({ queryKey: detectionKey(instance.id) });
      settle(qc, instance.id, null);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  if (!declared || query.isPending) return null;
  const title = service?.title ?? declared.title;
  const mode: "server" | "directory" = service || choosing ? "directory" : "server";
  const canManage = service?.can_manage ?? true;

  const choose = (next: "server" | "directory") => {
    if (next === mode) return;
    if (next === "directory") setChoosing(true);
    else if (service) setConfirmServer(true);
    else setChoosing(false);
  };

  return (
    <div data-connection-section="local-service" className="grid [&>*+*]:border-t [&>*+*]:border-divider">
      <SettingsRow label={t("localServiceWhere")} description={t("localServiceWhereDesc").replace("{title}", title)}>
        <WhereChoice mode={mode} disabled={Boolean(service) && !canManage} onChoose={choose} />
      </SettingsRow>
      <ConfirmDialog
        open={confirmServer}
        title={t("localServiceBackToServerTitle")}
        body={t("localServiceBackToServerBody").replace("{title}", title)}
        confirmLabel={t("localServiceBackToServerRun")}
        pending={remove.isPending}
        onCancel={() => setConfirmServer(false)}
        onConfirm={() => remove.mutate()}
      />
      {mode === "directory" && (!service || choosing) && (
        <DirectorySetup
          instanceId={instance.id}
          title={title}
          service={service}
          onDone={() => setChoosing(false)}
          onCancel={service ? () => setChoosing(false) : undefined}
        />
      )}
      {service && !choosing && <ServiceRows instanceId={instance.id} service={service} onChangeFolder={() => setChoosing(true)} />}
    </div>
  );
}

function WhereChoice({
  mode,
  disabled,
  onChoose,
}: {
  mode: "server" | "directory";
  disabled: boolean;
  onChoose: (mode: "server" | "directory") => void;
}) {
  const t = useI18n();
  const options: { value: "server" | "directory"; label: MessageKey }[] = [
    { value: "server", label: "localServiceModeServer" },
    { value: "directory", label: "localServiceModeDirectory" },
  ];
  return (
    <div role="radiogroup" aria-label={t("localServiceWhere")} className={cn(SEGMENTED_LIST, "flex-wrap")}>
      {options.map((one) => (
        <button
          key={one.value}
          type="button"
          role="radio"
          aria-checked={mode === one.value}
          disabled={disabled}
          className={segmentedTriggerClass(mode === one.value)}
          onClick={() => onChoose(one.value)}
        >
          {t(one.label)}
        </button>
      ))}
      {/* 第三种(让 Mosael 装)看得见、点不了:写明下一步提供,免得以为只能自己装 */}
      <Hint label={t("localServiceManagedSoon")}>
        <span tabIndex={0} aria-disabled className={cn(segmentedTriggerClass(false), "cursor-not-allowed opacity-50")}>
          {t("localServiceModeManaged")}
        </span>
      </Hint>
    </div>
  );
}

/**
 * 选目录:目录、可选的解释器、「检查并使用」。点了先确认(会在哪台机器上运行哪个目录里的代码),再让插件认一遍;
 * 认出来、能起就存下(第一次存时宿主选端口、写进连接的服务器地址),认不出就把问题摆出来、不存。
 */
function DirectorySetup({
  instanceId,
  title,
  service,
  onDone,
  onCancel,
}: {
  instanceId: string;
  title: string;
  service: LocalService | null;
  onDone: () => void;
  onCancel?: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [directory, setDirectory] = React.useState(service?.directory ?? "");
  const [python, setPython] = React.useState(service?.python ?? "");
  const [confirming, setConfirming] = React.useState(false);
  const [found, setFound] = React.useState<LocalServiceDetection | null>(null);
  const check = useMutation({
    mutationFn: async () => {
      const detection = await detectLocalService(instanceId, directory.trim(), python.trim());
      if (!detection.ok) return { detection, saved: null };
      const body: LocalServiceUpdate = { mode: "directory", directory: directory.trim(), python: python.trim(), confirm_run_code: true };
      return { detection, saved: await putLocalService(instanceId, body) };
    },
    onSuccess: ({ detection, saved }) => {
      setConfirming(false);
      setFound(detection);
      qc.setQueryData(detectionKey(instanceId), detection);
      if (saved) {
        settle(qc, instanceId, saved);
        onDone();
      }
    },
    onError: (error: Error) => {
      setConfirming(false);
      toast.error(error.message);
    },
  });
  const ready = directory.trim().length > 0;

  return (
    <>
      <SettingsRow label={t("localServiceDirectory")} description={t("localServiceDirectoryDesc").replace("{title}", title)}>
        <Input
          className={SETTINGS_FIELD_WIDTH}
          aria-label={t("localServiceDirectory")}
          placeholder={t("localServiceDirectoryPlaceholder")}
          value={directory}
          onChange={(event) => setDirectory(event.target.value)}
          spellCheck={false}
          autoFocus={!service}
        />
      </SettingsRow>
      <SettingsRow label={t("localServicePython")} description={t("localServicePythonDesc")}>
        <Input
          className={SETTINGS_FIELD_WIDTH}
          aria-label={t("localServicePython")}
          value={python}
          onChange={(event) => setPython(event.target.value)}
          spellCheck={false}
        />
      </SettingsRow>
      <SettingsRow label={check.isPending ? t("localServiceChecking") : t("localServiceFacts")}>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={check.isPending}>
            {t("cancel")}
          </Button>
        )}
        <Button disabled={!ready} loading={check.isPending} onClick={() => setConfirming(true)}>
          {t("localServiceCheck")}
        </Button>
      </SettingsRow>
      {found && !found.ok && (
        <div className="grid gap-3 py-4">
          <p role="alert" className="m-0 text-ui-sm text-destructive">{t("localServiceNotUsable")}</p>
          <DetectionFacts detection={found} />
        </div>
      )}
      <ConfirmDialog
        open={confirming}
        title={t("localServiceConfirmTitle").replace("{where}", t(machineKey()))}
        body={t("localServiceConfirmBody").replace("{directory}", directory.trim()).replace("{title}", title)}
        confirmLabel={t("localServiceConfirmRun")}
        pending={check.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={() => check.mutate()}
      />
    </>
  );
}

/** 插件认目录时交回的事实和问题:一行一条,问题按轻重标色。 */
function DetectionFacts({ detection }: { detection: LocalServiceDetection }) {
  return (
    <div className="grid gap-2">
      {(detection.problems ?? []).map((problem, index) => (
        <p
          key={`p${index}`}
          className={cn(
            "m-0 flex items-start gap-2 whitespace-pre-wrap break-words text-ui-sm",
            problem.level === "error" ? "text-destructive" : "text-warning",
          )}
        >
          {problem.level === "error" ? (
            <CircleAlert size={14} aria-hidden className="mt-0.5 shrink-0" />
          ) : (
            <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0" />
          )}
          <span className="min-w-0">{problem.text}</span>
        </p>
      ))}
      {(detection.facts ?? []).length > 0 && (
        <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-ui-sm">
          {(detection.facts ?? []).map((fact) => (
            <React.Fragment key={fact.label}>
              <dt className="text-muted-foreground">{fact.label}</dt>
              <dd className="m-0 min-w-0 break-words">{fact.value}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
    </div>
  );
}

function ServiceRows({
  instanceId,
  service,
  onChangeFolder,
}: {
  instanceId: string;
  service: LocalService;
  onChangeFolder: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const detection = useQuery({
    queryKey: detectionKey(instanceId),
    queryFn: () => detectLocalService(instanceId, service.directory, service.python),
    // 存下来的目录是确认过的:打开连接卡时不再自动试跑,要看就点「重新检查」
    enabled: false,
    staleTime: Infinity,
  });
  const recheck = () => void detection.refetch();
  const act = useMutation({
    mutationFn: (action: "start" | "stop" | "restart") =>
      action === "start" ? startLocalService(instanceId) : action === "stop" ? stopLocalService(instanceId) : restartLocalService(instanceId),
    onSuccess: (next) => settle(qc, instanceId, next),
    onError: (error: Error) => {
      toast.error(error.message);
      void qc.invalidateQueries({ queryKey: localServiceKey(instanceId) });
    },
  });
  const save = useMutation({
    mutationFn: (body: LocalServiceUpdate) => putLocalService(instanceId, body),
    onSuccess: (next) => settle(qc, instanceId, next),
    onError: (error: Error) => toast.error(error.message),
  });
  const [logsOpen, setLogsOpen] = React.useState(false);
  const [confirmLan, setConfirmLan] = React.useState(false);
  const [advanced, setAdvanced] = React.useState(false);
  const busy = act.isPending ? act.variables : null;
  const manage = service.can_manage;
  const denied = manage ? undefined : t("localServiceAdminOnly");
  const active = service.state === "starting" || service.state === "running" || service.state === "restarting";
  const meta = [
    t("localServicePort").replace("{port}", String(service.port)),
    service.pid ? t("localServicePid").replace("{pid}", String(service.pid)) : "",
    service.started_at ? t("localServiceStartedAt").replace("{time}", new Date(service.started_at).toLocaleTimeString()) : "",
    service.state === "running" && service.ready_seconds != null && !service.adopted
      ? t("localServiceReadyIn").replace("{s}", String(service.ready_seconds))
      : "",
    service.restarts > 0 ? t("localServiceRestarts").replace("{n}", String(service.restarts)) : "",
  ].filter(Boolean);

  return (
    <>
      <div className="grid gap-3 py-5">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <div className="grid min-w-0 gap-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-ui-md font-medium">{t("localServiceState").replace("{title}", service.title)}</span>
              <CatalogBadge tone={STATE_TONE[service.state]}>{t(STATE_LABEL[service.state])}</CatalogBadge>
              {service.adopted && (
                <Hint label={t("localServiceAdoptedHint")}>
                  <span className="text-ui-xs text-muted-foreground">{t("localServiceAdopted")}</span>
                </Hint>
              )}
            </div>
            <span className="timecode text-ui-xs text-muted-foreground">{meta.join(" · ")}</span>
            {service.state === "stopped" && <small className="text-ui-sm text-muted-foreground">{t("localServiceStoppedDesc")}</small>}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {active ? (
              <>
                <Hint disabledReason={denied}>
                  <Button variant="outline" size="sm" disabled={!manage} loading={busy === "restart"} onClick={() => act.mutate("restart")}>
                    <RotateCw /> {t("localServiceRestart")}
                  </Button>
                </Hint>
                <Hint disabledReason={denied}>
                  <Button variant="outline" size="sm" disabled={!manage} loading={busy === "stop"} onClick={() => act.mutate("stop")}>
                    <Square /> {t("localServiceStop")}
                  </Button>
                </Hint>
              </>
            ) : (
              <Hint disabledReason={denied}>
                <Button size="sm" disabled={!manage} loading={busy === "start"} onClick={() => act.mutate("start")}>
                  <Play /> {t("localServiceStart")}
                </Button>
              </Hint>
            )}
            <Button variant="outline" size="sm" onClick={() => setLogsOpen(true)}>
              <FileText /> {t("localServiceLogs")}
            </Button>
          </div>
        </div>
        {service.state === "failed" && (
          <div className="grid gap-2">
            <p role="alert" className="m-0 whitespace-pre-wrap break-words text-ui-sm text-destructive">{service.error}</p>
            {(service.failure_lines ?? []).length > 0 && (
              <details className="text-ui-xs">
                <summary className="cursor-pointer text-muted-foreground">{t("localServiceFailureLog")}</summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-panel-subtle p-3 font-mono text-ui-xs">
                  {(service.failure_lines ?? []).join("\n")}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>

      <SettingsRow label={t("localServiceFolder")} description={<code className="timecode break-all">{service.directory}</code>}>
        <Button variant="outline" size="sm" loading={detection.isFetching} disabled={!manage} onClick={recheck}>
          {t("localServiceRecheck")}
        </Button>
        <Hint disabledReason={denied}>
          <Button variant="outline" size="sm" disabled={!manage} onClick={onChangeFolder}>
            {t("localServiceChangeFolder")}
          </Button>
        </Hint>
      </SettingsRow>
      {detection.error && <p role="alert" className="m-0 py-3 text-ui-sm text-destructive">{(detection.error as Error).message}</p>}
      {detection.data && (
        <div className="grid gap-3 py-4">
          <DetectionFacts detection={detection.data} />
        </div>
      )}
      {detection.data?.add_nodes && (
        <AddNodesRow instanceId={instanceId} offer={detection.data.add_nodes} running={service.state === "running"} disabled={!manage}
                     onInstalled={recheck} />
      )}

      <SettingsRow label={t("localServiceKeepRunning")} description={t("localServiceKeepRunningDesc")}>
        <Switch
          aria-label={t("localServiceKeepRunning")}
          checked={service.keep_running}
          disabled={!manage || save.isPending}
          onCheckedChange={(keep_running) => save.mutate({ keep_running })}
        />
      </SettingsRow>
      <SettingsRow label={t("localServiceLan")} description={t("localServiceLanDesc").replace("{title}", service.title)}>
        <Switch
          aria-label={t("localServiceLan")}
          checked={service.listen_lan}
          disabled={!manage || save.isPending}
          onCheckedChange={(next) => (next ? setConfirmLan(true) : save.mutate({ listen_lan: false }))}
        />
      </SettingsRow>
      <ConfirmDialog
        open={confirmLan}
        title={t("localServiceLanConfirmTitle")}
        body={t("localServiceLanDesc").replace("{title}", service.title)}
        confirmLabel={t("localServiceLanConfirmRun")}
        pending={save.isPending}
        onCancel={() => setConfirmLan(false)}
        onConfirm={() => save.mutate({ listen_lan: true }, { onSettled: () => setConfirmLan(false) })}
      />

      <div className="py-3">
        <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>
          <ChevronRight className={cn("transition-transform duration-100", advanced && "rotate-90")} />
          {t("localServiceAdvanced")}
        </Button>
      </div>
      {advanced && (
        <>
          <SettingsRow label={t("localServicePortLabel")} description={t("localServicePortDesc")}>
            <DraftField
              label={t("localServicePortLabel")}
              value={String(service.port)}
              disabled={!manage || active}
              inputMode="numeric"
              onCommit={(text) => {
                const port = Number.parseInt(text, 10);
                if (Number.isFinite(port) && port !== service.port) save.mutate({ port });
              }}
            />
          </SettingsRow>
          <SettingsRow label={t("localServiceExtraArgs")} description={t("localServiceExtraArgsDesc")}>
            <DraftField
              label={t("localServiceExtraArgs")}
              value={joinArgs(service.extra_args ?? [])}
              disabled={!manage}
              onCommit={(text) => {
                if (text.trim() !== joinArgs(service.extra_args ?? [])) save.mutate({ extra_args: text });
              }}
            />
          </SettingsRow>
        </>
      )}
      {logsOpen && <LogDialog instanceId={instanceId} title={service.title} onClose={() => setLogsOpen(false)} />}
    </>
  );
}

/** 一个离开时才存的输入框(端口、附加参数):值住在服务端,每敲一个字发一次请求会把字吞掉。 */
function DraftField({
  label,
  value,
  disabled,
  inputMode,
  onCommit,
}: {
  label: string;
  value: string;
  disabled: boolean;
  inputMode?: "numeric";
  onCommit: (value: string) => void;
}) {
  const draft = useDraftText<HTMLInputElement>({ value, onValueChange: onCommit, commit: "blur" });
  return <Input className={SETTINGS_FIELD_WIDTH} aria-label={label} disabled={disabled} inputMode={inputMode} spellCheck={false} {...draft} />;
}

/** 插件说可以补装的(ComfyUI:模型库要的 pysssss)。确认框里写明装什么、装到哪儿;在跑的话装完提示重启。 */
function AddNodesRow({
  instanceId,
  offer,
  running,
  disabled,
  onInstalled,
}: {
  instanceId: string;
  offer: NonNullable<LocalServiceDetection["add_nodes"]>;
  running: boolean;
  disabled: boolean;
  onInstalled: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [confirming, setConfirming] = React.useState(false);
  const install = useMutation({
    mutationFn: () => addLocalServiceNodes(instanceId),
    onSuccess: (done) => {
      setConfirming(false);
      toast.success(done.message || done.path, running ? {
        description: t("localServiceRestartToLoad"),
        action: { label: t("localServiceRestart"), onClick: () => void restartLocalService(instanceId).then((next) => settle(qc, instanceId, next)) },
      } : undefined);
      onInstalled();
    },
    onError: (error: Error) => {
      setConfirming(false);
      toast.error(error.message);
    },
  });
  return (
    <SettingsRow label={offer.title} description={<InlineMarkdown text={offer.description ?? ""} />}>
      <Button variant="outline" size="sm" disabled={disabled} loading={install.isPending} onClick={() => setConfirming(true)}>
        {t("localServiceAddNodesRun")}
      </Button>
      <ConfirmDialog
        open={confirming}
        title={offer.title}
        body={t("localServiceAddNodesConfirmBody").replace("{description}", toPlainText(offer.description ?? ""))}
        confirmLabel={t("localServiceAddNodesRun")}
        pending={install.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={() => install.mutate()}
      />
    </SettingsRow>
  );
}

/** 日志:它自己说的话原样摆出来,开着的时候每 1.5 秒拉一次,停在最底下;完整日志在哪个文件写明。 */
function LogDialog({ instanceId, title, onClose }: { instanceId: string; title: string; onClose: () => void }) {
  const t = useI18n();
  const logs = useQuery({
    queryKey: ["local-service-logs", instanceId],
    queryFn: () => getLocalServiceLogs(instanceId, 2000),
    refetchInterval: 1500,
  });
  const bottom = React.useRef<HTMLPreElement>(null);
  const lines = logs.data?.lines ?? [];
  React.useEffect(() => {
    const element = bottom.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lines.length]);
  return (
    <ModalShell open onOpenChange={(open) => !open && onClose()} title={t("localServiceLogTitle").replace("{title}", title)}
                className="w-[min(960px,calc(100vw-2rem))]">
      <div className="grid gap-2">
        <pre
          ref={bottom}
          className="m-0 h-[min(60vh,560px)] overflow-auto whitespace-pre-wrap break-words rounded-md bg-panel-subtle p-3 font-mono text-ui-xs"
        >
          {lines.length > 0 ? lines.join("\n") : t("localServiceLogEmpty")}
        </pre>
        {logs.data?.path && (
          <small className="flex items-center gap-1.5 text-ui-xs text-muted-foreground">
            <Info size={12} aria-hidden />
            <span className="break-all">{t("localServiceLogPath").replace("{path}", logs.data.path)}</span>
          </small>
        )}
      </div>
    </ModalShell>
  );
}

const DISMISSED_KEY = "mosael.plugins.discoveryDismissed";

function readDismissed(): string[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(DISMISSED_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((one): one is string => typeof one === "string") : [];
  } catch {
    return [];
  }
}

/**
 * 插件页上的「本机发现一个,要连上吗」(ADR 0041 §3):插件知道去哪几个端口问(ComfyUI:8188、Desktop 的 8000)。
 * 连上建的是「连一台服务器」那一种 —— 它自己管自己的进程,Mosael 不去起停它。已经连着的、点过「不用了」的不再提。
 * 只给部署管理员(那是这台机器上的事);别人问到 403,这一条就不出现。
 */
export function LocalServiceDiscovery({ pkg, onConnected }: { pkg: PluginPackage; onConnected: (instanceId: string) => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const found = useQuery({
    queryKey: ["local-service-discovery", pkg.id],
    queryFn: () => discoverLocalServices(pkg.id),
    retry: false,
    staleTime: 60_000,
  });
  const [dismissed, setDismissed] = React.useState<string[]>(readDismissed);
  const connect = useMutation({
    mutationFn: (url: string) => createPluginInstance(pkg.id, { config: { [SERVICE_ADDRESS_FIELD]: url } }),
    onSuccess: (created) => {
      invalidatePluginDependents(qc);
      if (created?.id) onConnected(created.id);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const connected = new Set(
    (pkg.instances ?? []).map((one) => String((one.config as Record<string, unknown>)[SERVICE_ADDRESS_FIELD] ?? "").replace(/\/+$/, "")),
  );
  const servers = (found.data?.servers ?? []).filter((one) => !connected.has(one.url) && !dismissed.includes(one.url));
  if (servers.length === 0) return null;
  const dismiss = (url: string) => {
    const next = [...dismissed, url];
    setDismissed(next);
    try {
      window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(next));
    } catch {
      // 存不下就只在这一次打开里不提
    }
  };
  return (
    <>
      {servers.map((server) => (
        <div key={server.url} role="status" className="flex min-w-0 flex-wrap items-center gap-3 rounded-xl border border-border bg-panel px-4 py-3">
          <Info size={15} aria-hidden className="shrink-0 text-primary" />
          <div className="grid min-w-0 flex-1 basis-[280px] gap-0.5">
            <span className="text-ui-sm font-medium">{t("localServiceDiscovered").replace("{label}", server.label)}</span>
            <small className="text-ui-xs text-muted-foreground">{t("localServiceDiscoveredBody")}</small>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => dismiss(server.url)}>
              {t("localServiceDismiss")}
            </Button>
            <Button size="sm" loading={connect.isPending && connect.variables === server.url} onClick={() => connect.mutate(server.url)}>
              {t("localServiceConnect")}
            </Button>
          </div>
        </div>
      ))}
    </>
  );
}
