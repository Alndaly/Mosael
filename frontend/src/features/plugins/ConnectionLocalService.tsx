import React from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { Check, ChevronRight, CircleAlert, CircleCheck, FileText, Info, Library, Play, RotateCw, Square, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import {
  addLocalServiceNodes,
  cancelLocalServiceInstall,
  createPluginInstance,
  detectLocalService,
  discoverLocalServices,
  getLocalServiceModelFolders,
  getLocalServicePlan,
  installLocalService,
  putLocalService,
  removeLocalService,
  restartLocalService,
  startLocalService,
  stopLocalService,
  type LocalService,
  type LocalServiceDetection,
  type LocalServiceInstall,
  type LocalServicePlan,
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
import { ConfirmDialog } from "@/components/app/modals";
import { PathField } from "@/components/settings/PathField";
import { SETTINGS_FIELD_WIDTH, SettingsRow } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { useDraftText } from "@/components/ui/draft-text";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { Hint } from "@/components/ui/tooltip";
import { LocalServiceLogDialog, focusConnectionSection, localServiceKey, useLocalService } from "@/features/plugins/localServiceStatus";
import { ModelLibraryDialog } from "@/features/plugins/ModelLibrary";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { formatBytes, formatSpeed } from "@/lib/bytes";
import { gotoAdmin } from "@/lib/deepLink";
import { cn } from "@/lib/utils";

/** 本机服务的地址写进连接配置的这一格(清单格式的约定,见 mosael_formats.plugin_manifest.SERVICE_ADDRESS_FIELD)。 */
export const SERVICE_ADDRESS_FIELD = "server_url";

const detectionKey = (instanceId: string) => ["local-service-detection", instanceId] as const;
const planKey = (instanceId: string) => ["local-service-plan", instanceId] as const;

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

/** 「在哪跑」的三种。 */
type Where = "server" | "directory" | "managed";

/**
 * 连接页上的「本机服务」(ADR 0041):插件声明了一种本机服务(清单的 `services`)就有这一块,和是哪个插件无关。
 *
 * - 「在哪跑」:连一台服务器(只连,不管进程)/ 用我自己装的(选目录,由 Mosael 起停)/ 让 Mosael 装(装在 Mosael 的数据目录里);
 * - 选目录:先确认「会在这台机器上运行这个目录里的代码」,再让插件认一遍(试跑一次),认出来、能起才存;
 * - 让 Mosael 装:先看安装计划(这台机器能不能装、装哪种 PyTorch、要多少空间、分几步、从哪儿下),确认写明在哪台机器上装;
 *   装的时候看得到第几步、多少字节、多快,能取消;没装成说人话、给日志,「接着装」从没做完的那一步来;装好了链到模型库(不替你下模型);
 *   Mosael 换了 Python 小版本时说「运行环境要重建」,一键重装依赖,源码和模型不动;
 * - 存好之后:状态(已停止 / 启动中 / 运行中 / 重启中 / 起不来)、启动 / 停止 / 重启、日志、端口、补装、保持运行、局域网,
 *   附加参数和端口在「高级」里。
 *
 * 建、改、起、停、装都要部署管理员(后端拦);别人看得到状态,控件是灰的、说明为什么。
 */
export function ConnectionLocalService({
  pkg,
  instance,
  workspaceId,
  serverAddress,
}: {
  pkg: PluginPackage;
  instance: PluginInstance;
  workspaceId: string;
  /**
   * 「连一台服务器」时的那一格服务器地址(清单里 SERVICE_ADDRESS_FIELD 那一格,连接页照常画好交进来)。本机的两种一选上
   * 就不摆它 —— 地址由 Mosael 分端口、写进去,这里换成只读的那一行。
   */
  serverAddress?: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const declared = (pkg.services ?? [])[0];
  const query = useLocalService(instance.id, Boolean(declared));
  const service = query.data ?? null;
  //: 正在换成另一种(还没存下来);null = 照存着的那种显示
  const [choosing, setChoosing] = React.useState<"directory" | "managed" | null>(null);
  const [rebuilding, setRebuilding] = React.useState(false);
  const [confirmServer, setConfirmServer] = React.useState(false);
  const remove = useMutation({
    mutationFn: () => removeLocalService(instance.id),
    onSuccess: () => {
      setConfirmServer(false);
      setChoosing(null);
      qc.removeQueries({ queryKey: detectionKey(instance.id) });
      settle(qc, instance.id, null);
    },
    onError: (error: Error) => {
      setConfirmServer(false);
      toast.error(error.message);
    },
  });
  if (!declared || query.isPending) return null;
  const title = service?.title ?? declared.title;
  const current: Where = service ? (service.mode === "managed" ? "managed" : "directory") : "server";
  const mode: Where = choosing ?? current;
  const canManage = service?.can_manage ?? true;
  const installing = service?.install?.state === "installing";
  //: 让 Mosael 装的那一份还没装好(或正在装):这一块就是安装计划 / 进度,不是状态和起停
  const managedPending = service?.mode === "managed" && (!service.installed || installing);
  const showManaged = mode === "managed" && (choosing === "managed" || managedPending || rebuilding);
  const showDirectory = mode === "directory" && (!service || choosing === "directory");
  //: 存好了、不在换:状态、起停、「高级」里的端口
  const showRows = Boolean(service) && !choosing && !showManaged;

  const choose = (next: Where) => {
    if (next === mode) return;
    setRebuilding(false);
    if (next === "server") {
      if (service) setConfirmServer(true);
      else setChoosing(null);
      return;
    }
    setChoosing(next === current ? null : next);
  };

  return (
    <div data-connection-section="local-service" className="grid [&>*+*]:border-t [&>*+*]:border-divider">
      <SettingsRow label={t("localServiceWhere")} description={t("localServiceWhereDesc").replace("{title}", title)}>
        <WhereChoice
          mode={mode}
          disabledReason={installing ? t("localServiceInstallingLocked") : service && !canManage ? t("localServiceAdminOnly") : undefined}
          onChoose={choose}
        />
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
      {mode === "server" ? serverAddress : <ServiceAddress service={service} portBelow={showRows} />}
      {showDirectory && (
        <DirectorySetup
          instanceId={instance.id}
          title={title}
          service={service?.mode === "directory" ? service : null}
          onDone={() => setChoosing(null)}
          onCancel={service ? () => setChoosing(null) : undefined}
        />
      )}
      {showManaged && (
        <ManagedInstall
          instanceId={instance.id}
          title={title}
          service={service?.mode === "managed" ? service : null}
          rebuild={rebuilding || Boolean(service?.needs_rebuild)}
          canManage={canManage}
          onCancel={rebuilding ? () => setRebuilding(false) : choosing === "managed" && current !== "managed" ? () => setChoosing(null) : undefined}
          onStarted={() => {
            setChoosing(null);
            setRebuilding(false);
          }}
        />
      )}
      {service && showRows && (
        <>
          {service.mode === "managed" && (
            <ManagedNotices instance={instance} workspaceId={workspaceId} service={service} onRebuild={() => setRebuilding(true)} />
          )}
          <ServiceRows instanceId={instance.id} service={service} onChangeFolder={() => setChoosing("directory")} />
        </>
      )}
    </div>
  );
}

/**
 * 本机的两种「在哪跑」时,服务器地址在这里只读:还没确认(没建过这一行)时说端口确认后由 Mosael 分;建好了就是它写进连接的那个
 * 地址(在两种本机方式之间换,端口不变)。改端口在下面「高级」里(要先停,改完插件把按旧地址存的数据搬过去)。
 *
 * 外面那一层带着 `config:<SERVICE_ADDRESS_FIELD>` 的标记:模型库读不出来时「去检查连接设置」定位到的就是这一行。
 */
function ServiceAddress({ service, portBelow }: { service: LocalService | null; portBelow: boolean }) {
  const t = useI18n();
  return (
    <div data-connection-section={`config:${SERVICE_ADDRESS_FIELD}`}>
      <SettingsRow label={t("localServiceAddress")} description={service && portBelow ? t("localServiceAddressManaged") : undefined}>
        {service ? (
          <code className="timecode text-ui-sm">{service.url}</code>
        ) : (
          <span className="text-ui-sm text-muted-foreground">{t("localServiceAddressPending")}</span>
        )}
      </SettingsRow>
    </div>
  );
}

function WhereChoice({
  mode,
  disabledReason,
  onChoose,
}: {
  mode: Where;
  /** 换不了(不是部署管理员、正在装)时说为什么;给了就整组变灰。 */
  disabledReason?: string;
  onChoose: (mode: Where) => void;
}) {
  const t = useI18n();
  const options: { value: Where; label: MessageKey }[] = [
    { value: "server", label: "localServiceModeServer" },
    { value: "directory", label: "localServiceModeDirectory" },
    { value: "managed", label: "localServiceModeManaged" },
  ];
  return (
    <Hint disabledReason={disabledReason}>
      <div role="radiogroup" aria-label={t("localServiceWhere")} className={cn(SEGMENTED_LIST, "flex-wrap")}>
        {options.map((one) => (
          <button
            key={one.value}
            type="button"
            role="radio"
            aria-checked={mode === one.value}
            disabled={Boolean(disabledReason)}
            className={segmentedTriggerClass(mode === one.value)}
            onClick={() => onChoose(one.value)}
          >
            {t(one.label)}
          </button>
        ))}
      </div>
    </Hint>
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
        <PathField
          kind="directory"
          label={t("localServiceDirectory")}
          placeholder={t("localServiceDirectoryPlaceholder")}
          value={directory}
          onChange={setDirectory}
          autoFocus={!service}
        />
      </SettingsRow>
      <SettingsRow label={t("localServicePython")} description={t("localServicePythonDesc")}>
        <PathField kind="file" label={t("localServicePython")} value={python} onChange={setPython} />
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

/**
 * 让 Mosael 装:还没装好(或正在装、要重建)时这一块就是它。
 *
 * - 没在装:安装计划(这台机器能不能装、装哪种 PyTorch、空间、装在哪、分几步 —— 接着装时做完的打勾 —— 从哪儿下),上一次
 *   没装成就把原因和「安装日志」摆在最上面;「开始安装 / 接着装 / 重建运行环境」先确认,写明在哪台机器上运行下载来的代码;
 * - 在装:第几步、这一步手上那个文件下了多少、多快,「取消安装」「安装日志」。
 */
function ManagedInstall({
  instanceId,
  title,
  service,
  rebuild,
  canManage,
  onCancel,
  onStarted,
}: {
  instanceId: string;
  title: string;
  /** 已经是「让 Mosael 装」的那一行(还没装好、正在装、要重建);从别的方式换过来时是 null。 */
  service: LocalService | null;
  rebuild: boolean;
  canManage: boolean;
  onCancel?: () => void;
  onStarted: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const run = service?.install ?? null;
  const installing = run?.state === "installing";
  const plan = useQuery({
    queryKey: planKey(instanceId),
    queryFn: () => getLocalServicePlan(instanceId),
    enabled: !installing && canManage,
    retry: false,
  });
  //: 一次安装落定了(没装成、取消了):重读安装计划,做完的那几步打上勾
  const settledAt = run && !installing ? run.finished_at : null;
  React.useEffect(() => {
    if (settledAt) void qc.invalidateQueries({ queryKey: planKey(instanceId) });
  }, [settledAt, qc, instanceId]);
  const [confirming, setConfirming] = React.useState(false);
  const [logsOpen, setLogsOpen] = React.useState(false);
  const start = useMutation({
    mutationFn: (flavour: string) => installLocalService(instanceId, flavour),
    onSuccess: (next) => {
      setConfirming(false);
      settle(qc, instanceId, next);
      onStarted();
    },
    onError: (error: Error) => {
      setConfirming(false);
      toast.error(error.message);
    },
  });
  const cancel = useMutation({
    mutationFn: () => cancelLocalServiceInstall(instanceId),
    onSuccess: (next) => settle(qc, instanceId, next),
    onError: (error: Error) => toast.error(error.message),
  });
  const logs = logsOpen && <LocalServiceLogDialog instanceId={instanceId} title={title} source="install" onClose={() => setLogsOpen(false)} />;

  if (run && installing) {
    return (
      <>
        <InstallProgress title={title} run={run} canManage={canManage} cancelling={cancel.isPending} onCancel={() => cancel.mutate()}
                         onLogs={() => setLogsOpen(true)} />
        {logs}
      </>
    );
  }
  const found = plan.data;
  const stopped = run ? (run.steps ?? []).find((one) => one.key === run.step)?.title ?? run.step : "";
  const resumable = Boolean(found?.steps?.some((one) => one.done && one.key !== "disk")) || run?.state === "failed" || run?.state === "cancelled";
  const action: MessageKey = rebuild ? "localServiceInstallRebuild" : resumable ? "localServiceInstallResume" : "localServiceInstallStart";
  const where = t(machineKey());
  return (
    <div className="grid gap-4 py-5">
      {run?.state === "failed" && (
        <div role="alert" className="grid gap-1 text-ui-sm text-destructive">
          <span className="font-medium">{t("localServiceInstallFailed").replace("{step}", stopped ?? "")}</span>
          <span className="whitespace-pre-wrap break-words">{run.error}</span>
        </div>
      )}
      {run?.state === "cancelled" && (
        <p className="m-0 text-ui-sm text-muted-foreground">{t("localServiceInstallCancelled").replace("{step}", stopped ?? "")}</p>
      )}
      {rebuild && service && <RebuildNote title={title} service={service} />}
      {!canManage ? (
        <p className="m-0 text-ui-sm text-muted-foreground">{t("localServiceAdminOnly")}</p>
      ) : plan.isPending ? (
        <p className="m-0 text-ui-sm text-muted-foreground">{t("localServicePlanChecking")}</p>
      ) : plan.error ? (
        <p role="alert" className="m-0 text-ui-sm text-destructive">{(plan.error as Error).message}</p>
      ) : found ? (
        <PlanFacts instanceId={instanceId} plan={found} />
      ) : null}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={start.isPending}>
            {t("cancel")}
          </Button>
        )}
        {run && (
          <Button variant="outline" onClick={() => setLogsOpen(true)}>
            <FileText /> {t("localServiceInstallLog")}
          </Button>
        )}
        {plan.error && (
          <Button variant="outline" onClick={() => void plan.refetch()}>
            {t("localServicePlanRetry")}
          </Button>
        )}
        <Button disabled={!canManage || !found?.ok} loading={start.isPending} onClick={() => setConfirming(true)}>
          {t(action)}
        </Button>
      </div>
      <ConfirmDialog
        open={confirming}
        title={t(rebuild ? "localServiceRebuildConfirmTitle" : "localServiceInstallConfirmTitle").replace("{where}", where).replace("{title}", title)}
        body={t(rebuild ? "localServiceRebuildConfirmBody" : "localServiceInstallConfirmBody")
          .replace("{title}", title)
          .replace("{version}", found?.version ?? "")
          .replace("{directory}", found?.directory ?? "")
          .replace("{where}", where)}
        confirmLabel={t(action)}
        pending={start.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={() => found && start.mutate(found.flavour ?? "")}
      />
      {logs}
    </div>
  );
}

const ROUTE_TEXT: Record<LocalServicePlan["route"]["kind"], MessageKey> = {
  global: "localServicePlanRouteGlobal",
  own: "localServicePlanRouteOwn",
  direct: "localServicePlanRouteDirect",
  system: "localServicePlanRouteSystem",
};

const SETTING_LABEL: Record<string, MessageKey> = {
  github: "localServicePlanSettingGithub",
  pytorch: "localServicePlanSettingPytorch",
  pip: "localServicePlanSettingPip",
};

/** 一个下载地址被「管理 → 下载源」里的哪一项改写了、那一项现在是什么(GitHub 镜像前缀没设时说直连 GitHub)。 */
function SettingNote({ source, setting }: { source: string; setting: string }) {
  const t = useI18n();
  const label = SETTING_LABEL[source];
  if (!label) return null;
  if (source === "github" && !setting) return <span>{t("localServicePlanSettingGithubNone")}</span>;
  return (
    <span>
      {t(label)}
      <span className="ml-1 break-all" data-setting-value>{setting}</span>
    </span>
  );
}


/**
 * 会从这几处下载,以及**怎么连过去**:插件进程拿到的出站代理(跟随全局 / 这个连接自己的 / 直连,宿主按 egress 算的那一份),
 * 绕过列表里的地址标出来;每个地址旁边写明它被下载源里的哪一项改写(GitHub 镜像前缀、PyTorch 源、pip 源)。改的地方链过去:
 * 这个连接的「网络」、管理页的全局网络和下载源。
 */
function PlanDownloads({ instanceId, plan }: { instanceId: string; plan: LocalServicePlan }) {
  const t = useI18n();
  const route = plan.route;
  return (
    <div className="grid gap-2 text-ui-sm">
      <p className="m-0" data-plan-route={route.kind}>
        <span className="text-muted-foreground">{t("localServicePlanRoute")}</span>{" "}
        <span>{t(ROUTE_TEXT[route.kind])}</span>
        {route.proxy && <code className="timecode ml-1 break-all" data-plan-proxy>{route.proxy}</code>}
      </p>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-ui-xs">
        <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-primary underline-offset-2 hover:underline"
                onClick={() => focusConnectionSection(instanceId, "network")}>
          {t("localServicePlanChangeNetwork")}
        </button>
        <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-primary underline-offset-2 hover:underline"
                onClick={() => gotoAdmin("deployment")}>
          {t("localServicePlanChangeGlobalNetwork")}
        </button>
        <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-primary underline-offset-2 hover:underline"
                onClick={() => gotoAdmin("engines")}>
          {t("localServicePlanChangeSources")}
        </button>
      </div>
      <details>
        <summary className="cursor-pointer text-muted-foreground">{t("localServicePlanDownloads")}</summary>
        <ul className="m-0 mt-2 grid gap-1.5 pl-4">
          {(plan.downloads ?? []).map((one) => (
            <li key={one.label} data-download-source={one.source || undefined}>
              {one.label}
              {one.url && <code className="timecode ml-2 break-all text-ui-xs text-muted-foreground">{one.url}</code>}
              {(one.source || one.bypass) && (
                <span className="flex flex-wrap gap-x-2 text-ui-xs text-muted-foreground">
                  <SettingNote source={one.source ?? ""} setting={one.setting ?? ""} />
                  {one.bypass && <span className="text-warning" data-bypass>{t("localServicePlanBypass")}</span>}
                </span>
              )}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

/** 安装计划:这台机器(能不能装、为什么)、问题、PyTorch、空间、装在哪、分几步、从哪儿下、怎么连过去;不下模型。 */
function PlanFacts({ instanceId, plan }: { instanceId: string; plan: LocalServicePlan }) {
  const t = useI18n();
  //: 这台机器本身能不能装(平台);能装但这一次开始不了(空间、路径)的原因在下面的问题里
  const supported = plan.supported ?? false;
  return (
    <div className="grid gap-3">
      <p className={cn("m-0 flex items-start gap-2 text-ui-sm", supported ? "text-foreground" : "text-destructive")}>
        {supported ? (
          <CircleCheck size={15} aria-hidden className="mt-0.5 shrink-0 text-success" />
        ) : (
          <CircleAlert size={15} aria-hidden className="mt-0.5 shrink-0" />
        )}
        <span className="min-w-0 whitespace-pre-wrap break-words">
          <span className="font-medium">{plan.platform}</span>
          {plan.verdict && <span className={supported ? "text-muted-foreground" : undefined}>{` · ${plan.verdict}`}</span>}
        </span>
      </p>
      {!supported && <p className="m-0 text-ui-sm text-destructive">{t("localServicePlanUnsupported")}</p>}
      <Problems problems={plan.problems ?? []} />
      <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-ui-sm">
        {plan.torch && (
          <>
            <dt className="text-muted-foreground">{t("localServicePlanTorch")}</dt>
            <dd className="m-0 min-w-0 break-words">{plan.torch}</dd>
          </>
        )}
        {(plan.disk_bytes ?? 0) > 0 && (
          <>
            <dt className="text-muted-foreground">{t("localServicePlanDisk")}</dt>
            <dd className="m-0 min-w-0 break-words">
              {t("localServicePlanDiskValue").replace("{need}", formatBytes(plan.disk_bytes ?? 0)).replace("{free}", formatBytes(plan.free_bytes ?? 0))}
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">{t("localServicePlanWhere")}</dt>
        <dd className="m-0 min-w-0"><code className="timecode break-all">{plan.directory}</code></dd>
      </dl>
      {supported && (
        <div className="grid gap-1.5">
          <span className="text-ui-sm text-muted-foreground">{t("localServicePlanSteps")}</span>
          <StepList steps={plan.steps ?? []} />
        </div>
      )}
      {(plan.downloads ?? []).length > 0 && <PlanDownloads instanceId={instanceId} plan={plan} />}
      {supported && <small className="text-ui-sm text-muted-foreground">{t("localServicePlanNoModels")}</small>}
    </div>
  );
}

/** 一步一行:做完的打勾,正在做的标出来,别的标序号。 */
function StepList({ steps, current }: { steps: readonly { key: string; title: string; done?: boolean }[]; current?: string }) {
  return (
    <ol className="m-0 grid list-none gap-1 p-0 text-ui-sm">
      {steps.map((one, index) => {
        const active = one.key === current && !one.done;
        return (
          <li
            key={one.key}
            data-step={one.key}
            aria-current={active ? "step" : undefined}
            className={cn("flex items-start gap-2", one.done ? "text-muted-foreground" : active ? "font-medium text-foreground" : "text-foreground")}
          >
            <span className="mt-0.5 inline-flex w-4 shrink-0 justify-center tabular-nums">
              {one.done ? <Check size={14} aria-label="✓" className="text-success" /> : <span className="text-ui-xs">{index + 1}</span>}
            </span>
            <span className="min-w-0 break-words">{one.title}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** 正在装:第几步、整体进度、每一步、这一步手上那个文件(下了多少 / 一共多少 · 多快),取消和安装日志。 */
function InstallProgress({
  title,
  run,
  canManage,
  cancelling,
  onCancel,
  onLogs,
}: {
  title: string;
  run: LocalServiceInstall;
  canManage: boolean;
  cancelling: boolean;
  onCancel: () => void;
  onLogs: () => void;
}) {
  const t = useI18n();
  const steps = run.steps ?? [];
  const index = steps.findIndex((one) => one.key === run.step);
  const finished = steps.filter((one) => one.done).length;
  const within = run.total_bytes ? Math.min(1, (run.done_bytes ?? 0) / run.total_bytes) : 0;
  const overall = steps.length ? Math.round(((finished + within) / steps.length) * 100) : 0;
  const detail = [
    run.item,
    run.total_bytes ? `${formatBytes(run.done_bytes ?? 0)} / ${formatBytes(run.total_bytes)}` : "",
    run.speed ? formatSpeed(run.speed) : "",
  ].filter(Boolean);
  const label = t("localServiceInstalling").replace("{title}", title);
  return (
    <div className="grid gap-3 py-5" role="status" aria-live="polite">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <span className="text-ui-md font-medium">{label}</span>
        {index >= 0 && (
          <span className="text-ui-xs tabular-nums text-muted-foreground">
            {t("localServiceInstallStepOf").replace("{n}", String(index + 1)).replace("{total}", String(steps.length))}
          </span>
        )}
      </div>
      <Progress value={overall} aria-label={label} className="h-1.5" />
      <StepList steps={steps} current={run.step} />
      {detail.length > 0 && <p className="timecode m-0 break-all text-ui-xs text-muted-foreground">{detail.join(" · ")}</p>}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onLogs}>
          <FileText /> {t("localServiceInstallLog")}
        </Button>
        <Hint disabledReason={canManage ? undefined : t("localServiceAdminOnly")}>
          <Button variant="outline" size="sm" disabled={!canManage} loading={cancelling} onClick={onCancel}>
            <Square /> {t("localServiceInstallCancel")}
          </Button>
        </Hint>
      </div>
    </div>
  );
}

/** 运行环境要重建:哪个 Python 装的、现在是哪个,源码和模型不动。 */
function RebuildNote({ title, service }: { title: string; service: LocalService }) {
  const t = useI18n();
  return (
    <div role="alert" className="grid gap-1 text-ui-sm text-warning">
      <span className="flex items-center gap-2 font-medium">
        <TriangleAlert size={14} aria-hidden /> {t("localServiceRebuildTitle")}
      </span>
      <span>
        {t("localServiceRebuildBody")
          .replace("{title}", title)
          .replace("{have}", service.python_minor ?? "")
          .replace("{want}", service.base_python_minor ?? "")}
      </span>
    </div>
  );
}

/**
 * 让 Mosael 装的那一份装好以后,状态上面的那一条:要重建运行环境(一键重建),或者刚装好(去模型库挑模型 —— 不替你下,拍板 7)。
 */
function ManagedNotices({
  instance,
  workspaceId,
  service,
  onRebuild,
}: {
  instance: PluginInstance;
  workspaceId: string;
  service: LocalService;
  onRebuild: () => void;
}) {
  const t = useI18n();
  const [library, setLibrary] = React.useState(false);
  if (service.needs_rebuild) {
    return (
      <div className="grid gap-3 py-4">
        <RebuildNote title={service.title} service={service} />
        <div className="flex justify-end">
          <Hint disabledReason={service.can_manage ? undefined : t("localServiceAdminOnly")}>
            <Button size="sm" disabled={!service.can_manage} onClick={onRebuild}>
              <RotateCw /> {t("localServiceInstallRebuild")}
            </Button>
          </Hint>
        </div>
      </div>
    );
  }
  if (service.install?.state !== "succeeded") return null;
  return (
    <div role="status" className="flex min-w-0 flex-wrap items-center gap-3 py-4">
      <CircleCheck size={16} aria-hidden className="shrink-0 text-success" />
      <div className="grid min-w-0 flex-1 basis-[280px] gap-0.5">
        <span className="text-ui-sm font-medium">{t("localServiceInstalledTitle").replace("{title}", service.title)}</span>
        <small className="text-ui-xs text-muted-foreground">{t("localServiceInstalledBody")}</small>
      </div>
      {/* 和标题行上那颗一样:连接停用、缺授权时点不了,说为什么 */}
      <Hint disabledReason={instance.blocked_reason || undefined}>
        <Button size="sm" disabled={Boolean(instance.blocked_reason)} onClick={() => setLibrary(true)}>
          <Library /> {t("localServiceOpenModelLibrary")}
        </Button>
      </Hint>
      {library && (
        <ModelLibraryDialog open onOpenChange={(open) => !open && setLibrary(false)} instance={instance} workspaceId={workspaceId}
                            focus={null} />
      )}
    </div>
  );
}

/** 一条一行的问题,按轻重标色(认目录、安装计划共用)。 */
function Problems({ problems }: { problems: readonly { level: "error" | "warning"; text: string }[] }) {
  return (
    <>
      {problems.map((problem, index) => (
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
    </>
  );
}

/** 插件认目录时交回的事实和问题:一行一条,问题按轻重标色。 */
function DetectionFacts({ detection }: { detection: LocalServiceDetection }) {
  return (
    <div className="grid gap-2">
      <Problems problems={detection.problems ?? []} />
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
  const managed = service.mode === "managed";
  const denied = manage ? undefined : t("localServiceAdminOnly");
  //: 运行环境要重建的那一份起不来(后端也会拦):启动按钮灰着,说为什么
  const startDenied = denied ?? (service.needs_rebuild ? t("localServiceRebuildTitle") : undefined);
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
            {service.state === "stopped" && (
              <small className="text-ui-sm text-muted-foreground">
                {service.idle_stopped ? service.issue?.text ?? t("localServiceStoppedDesc") : t("localServiceStoppedDesc")}
              </small>
            )}
            {/* 闲置自动停(释放显存):不是「保持运行」的才有 */}
            {!service.keep_running && (service.idle_stop_minutes ?? 0) > 0 && service.state !== "stopped" && (
              <small className="text-ui-sm text-muted-foreground" data-idle-stop>
                {t("localServiceIdleStop").replace("{minutes}", String(service.idle_stop_minutes))}
              </small>
            )}
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
              <Hint disabledReason={startDenied}>
                <Button size="sm" disabled={Boolean(startDenied)} loading={busy === "start"} onClick={() => act.mutate("start")}>
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

      <SettingsRow
        label={t(managed ? "localServiceInstallLocation" : "localServiceFolder")}
        description={<code className="timecode break-all">{service.directory}</code>}
      >
        <Button variant="outline" size="sm" loading={detection.isFetching} disabled={!manage} onClick={recheck}>
          {t("localServiceRecheck")}
        </Button>
        {/* 让 Mosael 装的那一份装在宿主分的目录里,不换;要用自己的,「在哪跑」选「用我自己装的」 */}
        {!managed && (
          <Hint disabledReason={denied}>
            <Button variant="outline" size="sm" disabled={!manage} onClick={onChangeFolder}>
              {t("localServiceChangeFolder")}
            </Button>
          </Hint>
        )}
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
      {manage && <SharedModelFolders instanceId={instanceId} service={service} />}

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
          <SettingsRow label={t("localServiceIdleLabel")} description={t("localServiceIdleDesc")}>
            <DraftField
              label={t("localServiceIdleLabel")}
              value={String(service.idle_stop_minutes ?? 0)}
              disabled={!manage}
              inputMode="numeric"
              onCommit={(text) => {
                const minutes = Number.parseInt(text, 10);
                if (Number.isFinite(minutes) && minutes !== service.idle_stop_minutes) save.mutate({ idle_stop_minutes: minutes });
              }}
            />
          </SettingsRow>
        </>
      )}
      {logsOpen && <LocalServiceLogDialog instanceId={instanceId} title={service.title} onClose={() => setLogsOpen(false)} />}
    </>
  );
}

const modelFoldersKey = (instanceId: string) => ["local-service-model-folders", instanceId] as const;
/** 对上的模型目录最多摆几个名字(一份 ComfyUI 的 models 有二三十个子目录)。 */
const FOLDERS_SHOWN = 5;

/** 对上的模型目录:几个就全摆,多了摆前几个和一共几个。 */
function folderList(t: ReturnType<typeof useI18n>, folders: readonly string[]): string {
  if (folders.length <= FOLDERS_SHOWN + 1) return folders.join(" · ");
  return t("localServiceSharedFolders").replace("{list}", folders.slice(0, FOLDERS_SHOWN).join(" · ")).replace("{n}", String(folders.length));
}

/**
 * 共用的模型文件夹(ADR 0041 拍板 5):别处已有的模型文件夹(A1111 / Forge、另一份 ComfyUI 的 models、卸载时保留下来的)也给它用,
 * 不拷第二份。一处一行:插件认成了什么、在跑的话它加载了没有、从那里看到几个模型(刚加的要重启才加载);加的时候插件先认一遍,
 * 认不出的照它的原话说。它只读这些文件夹,模型库下载的新文件仍落在它自己的那一处。
 */
function SharedModelFolders({ instanceId, service }: { instanceId: string; service: LocalService }) {
  const t = useI18n();
  const qc = useQueryClient();
  const folders = useQuery({
    queryKey: modelFoldersKey(instanceId),
    queryFn: () => getLocalServiceModelFolders(instanceId),
    staleTime: 30_000,
  });
  //: 它刚就绪:重新问一遍加载了哪几处、几个模型
  React.useEffect(() => {
    if (service.state === "running") void qc.invalidateQueries({ queryKey: modelFoldersKey(instanceId) });
  }, [service.state, qc, instanceId]);
  const [draft, setDraft] = React.useState("");
  const save = useMutation({
    mutationFn: (next: string[]) => putLocalService(instanceId, { shared_models: next }),
    onSuccess: (next) => {
      setDraft("");
      settle(qc, instanceId, next);
      void qc.invalidateQueries({ queryKey: modelFoldersKey(instanceId) });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const current = service.shared_models ?? [];
  const add = (path: string) => {
    const trimmed = path.trim();
    if (trimmed && !current.includes(trimmed)) save.mutate([...current, trimmed]);
  };
  const shown = folders.data?.folders ?? [];
  const running = Boolean(folders.data?.running);
  return (
    <div className="grid gap-3 py-4" data-connection-section="shared-models">
      <div className="grid gap-0.5">
        <span className="text-ui-md font-medium">{t("localServiceShared")}</span>
        <small className="text-ui-sm text-muted-foreground">{t("localServiceSharedDesc").replace("{title}", service.title)}</small>
      </div>
      {current.length > 0 && (
        <ul className="m-0 grid list-none gap-2 p-0">
          {current.map((path) => {
            const one = shown.find((item) => item.path === path);
            const status = !one
              ? ""
              : !one.ok
                ? one.problem
                : running && one.loaded
                  ? t("localServiceSharedModels").replace("{n}", String(one.models ?? 0))
                  : running
                    ? t("localServiceSharedRestart")
                    : t("localServiceSharedNextStart");
            return (
              <li key={path} data-shared-folder={path} className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                <span className="grid min-w-0 flex-1 basis-[260px] gap-0.5">
                  <code className="timecode break-all text-ui-sm">{path}</code>
                  <small className={cn("text-ui-xs", one && !one.ok ? "text-warning" : "text-muted-foreground")}>
                    {[one?.layout, folderList(t, one?.folders ?? []), status].filter(Boolean).join(" — ")}
                  </small>
                </span>
                <Button variant="ghost" size="sm" aria-label={t("localServiceSharedRemove").replace("{path}", path)}
                        disabled={save.isPending} loading={save.isPending && !(save.variables ?? []).includes(path)}
                        onClick={() => save.mutate(current.filter((item) => item !== path))}>
                  {t("localServiceSharedRemoveShort")}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <PathField kind="directory" label={t("localServiceSharedPath")} value={draft} onChange={setDraft}
                   placeholder={t("localServiceSharedPlaceholder")} />
        <Button variant="outline" disabled={!draft.trim()} loading={save.isPending} onClick={() => add(draft)}>
          {t("localServiceSharedAdd")}
        </Button>
      </div>
      {(folders.data?.suggestions ?? []).length > 0 && (
        <div className="grid gap-1 text-ui-sm">
          <span className="text-muted-foreground">{t("localServiceSharedKept")}</span>
          {(folders.data?.suggestions ?? []).map((path) => (
            <span key={path} className="flex min-w-0 flex-wrap items-center gap-2">
              <code className="timecode break-all">{path}</code>
              <Button variant="outline" size="sm" disabled={save.isPending} onClick={() => add(path)}>
                {t("localServiceSharedAdd")}
              </Button>
            </span>
          ))}
        </div>
      )}
    </div>
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
