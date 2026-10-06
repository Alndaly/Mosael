/**
 * 连接背后的本机服务(ADR 0041)**此刻怎么样** —— 连接页、模型库、工作流库、工作台都从这里读,说法只在这里定:
 *
 * - `useLocalService`:那一行的状态(按 1200 ms / 5 秒轮询);
 * - `serviceIssue`:**用不了的时候按它的状态说**(后端 `issue`:停着、正在起、起不来、还没装好、要重建、进程在却不应答)。
 *   插件那句「连不上这台 ComfyUI,确认它在运行、地址填对」只适合「连一台服务器」—— 本机服务的地址和进程都归宿主管,
 *   该说的是它此刻是什么状态、能点什么(启动、看日志、去装);
 * - `ServiceIssueNote`:那一句话和该给的那一下;
 * - `explainOpenFailure`:不在连接页上的地方(工作台、内嵌编辑器打开失败)临时问一次;
 * - `LocalServiceLogDialog`:日志窗口(连接页、出错时的「看日志」共用);
 * - `machineKey`:确认框里说「在哪台机器上运行」(装、更新都要说)。
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Info, Play, Settings2, Wrench } from "lucide-react";
import { toast } from "sonner";

import {
  getLocalService,
  getLocalServiceLogs,
  startLocalService,
  touchLocalService,
  type LocalService,
  type LocalServiceLogSource,
  type LocalServiceState,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { cn } from "@/lib/utils";

/** 确认框里说「在哪台机器上运行」:桌面版是这台电脑,网页版连的是一台服务器。 */
export function machineKey(): MessageKey {
  return typeof window !== "undefined" && window.mosaelDesktop ? "localServiceWhereDesktop" : "localServiceWhereServer";
}

/** 这个连接的本机服务在缓存里的键。 */
export const localServiceKey = (instanceId: string) => ["local-service", instanceId] as const;

/** 还在变的两种状态按 1200 ms 问(和引擎安装同一个节奏),正在装时也是;别的时候隔几秒看一眼 —— 运行中崩了要看得见它在重启。 */
const UNSETTLED: readonly LocalServiceState[] = ["starting", "restarting"];

export function useLocalService(instanceId: string, enabled: boolean) {
  return useQuery({
    queryKey: localServiceKey(instanceId),
    queryFn: () => getLocalService(instanceId),
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      return UNSETTLED.includes(data.state) || data.install?.state === "installing" ? 1200 : 5000;
    },
  });
}

/** 工作台、内嵌编辑器开着时隔多久告诉宿主一声「还在用」(闲置自动停按分钟算,这里远小于一分钟的若干倍就够)。 */
export const KEEP_AWAKE_MS = 2 * 60_000;

/**
 * ComfyUI 的视图(工作台、内嵌编辑器)亮着时:那边直接和它说话、不经插件调用,宿主看不见 —— 隔一会儿告诉宿主一声「还在用」,
 * 闲置自动停就不会在人用着画布的时候把它停掉。`instanceId` 为 null(没亮着、不是 ComfyUI 的视图)时什么都不做。不替它起。
 */
export function useKeepServiceAwake(instanceId: string | null): void {
  React.useEffect(() => {
    if (!instanceId) return;
    const tell = () => void touchLocalService(instanceId).catch(() => undefined);
    tell();
    const timer = window.setInterval(tell, KEEP_AWAKE_MS);
    return () => window.clearInterval(timer);
  }, [instanceId]);
}

/** 连接卡片里这个连接的某一格(本机服务、网络、配置……):滚到那里、把焦点交过去。 */
export function focusConnectionSection(instanceId: string, section: string): void {
  const target = document.querySelector<HTMLElement>(`[data-connection="${instanceId}"] [data-connection-section="${section}"]`);
  if (!target) return;
  target.scrollIntoView({ block: "center" });
  target.querySelector<HTMLElement>("button, input, [tabindex]:not([tabindex='-1'])")?.focus({ preventScroll: true });
}

export type ServiceIssueKind = NonNullable<LocalService["issue"]>["kind"];
/** 语气:停着、正在起不是错 —— 用到时会起、马上就好。 */
export type ServiceIssueTone = "muted" | "primary" | "warning";

export interface ServiceIssue {
  kind: ServiceIssueKind;
  text: string;
  tone: ServiceIssueTone;
  /** 连接卡片标题行上那一格的说法。 */
  label: MessageKey;
  /** 该给的那一下:启动(停着、管理员)、看日志(起不来、不应答)、去装(还没装好、要重建)。 */
  action: "start" | "logs" | "install" | null;
}

const ISSUE: Record<ServiceIssueKind, { tone: ServiceIssueTone; label: MessageKey; action: ServiceIssue["action"] }> = {
  stopped: { tone: "muted", label: "localServiceStateStopped", action: "start" },
  starting: { tone: "primary", label: "localServiceStateStarting", action: null },
  installing: { tone: "primary", label: "localServiceIssueInstalling", action: null },
  updating: { tone: "primary", label: "localServiceIssueUpdating", action: null },
  failed: { tone: "warning", label: "localServiceStateFailed", action: "logs" },
  unresponsive: { tone: "warning", label: "localServiceIssueUnresponsive", action: "logs" },
  not_installed: { tone: "warning", label: "localServiceIssueNotInstalled", action: "install" },
  rebuild: { tone: "warning", label: "localServiceRebuildTitle", action: "install" },
};

/** 不等出错也该说的那几种:起不来、不应答、还没装好、要重建、正在装、正在换版本。停着、正在起只在真有一次失败时才替掉原因 ——
 * 平时它们就是常态。 */
const ALWAYS: readonly ServiceIssueKind[] = ["failed", "unresponsive", "not_installed", "rebuild", "installing", "updating"];

/**
 * 这个连接此刻该怎么说:背后的本机服务用不了时按它的状态说(`failing`:这个连接上有一次失败 —— 目录没刷出来、模型库读不出来;
 * 那时停着、正在起也替掉插件那句「检查地址」)。没有本机服务、它好好的、或者停着而没出过错,是 null —— 照原来的说。
 */
export function serviceIssue(service: LocalService | null | undefined, failing: boolean): ServiceIssue | null {
  const issue = service?.issue;
  if (!issue) return null;
  if (!failing && !ALWAYS.includes(issue.kind)) return null;
  return { kind: issue.kind, text: issue.text, ...ISSUE[issue.kind] };
}

/**
 * 不在连接页上的地方(打开工作台、内嵌编辑器没成)临时问一次:背后的本机服务此刻用不了,就说它那一句(停着、起不来、不应答……);
 * 没有本机服务、它好好的、问不到,照原来那句 `fallback` 说。
 */
export async function explainOpenFailure(instanceId: string, fallback: string): Promise<string> {
  try {
    return (await getLocalService(instanceId))?.issue?.text || fallback;
  } catch {
    return fallback;
  }
}

const TONE_CLASS: Record<ServiceIssueTone, string> = {
  muted: "text-muted-foreground",
  primary: "text-primary",
  warning: "text-warning",
};

/**
 * 那一句话和该给的那一下。`onInstall`:「去装」怎么去(连接卡上滚到本机服务那一块,模型库里先关掉弹窗再去);不给就不摆。
 * 启动只给部署管理员(后端也拦),别人看到的是「用到时会自动启动」那一句。
 */
export function ServiceIssueNote({
  instanceId,
  service,
  issue,
  onInstall,
  className,
}: {
  instanceId: string;
  service: LocalService;
  issue: ServiceIssue;
  onInstall?: () => void;
  className?: string;
}) {
  const lastLine = issue.kind === "failed" ? (service.failure_lines ?? []).at(-1) ?? "" : "";
  return (
    <div className={cn("grid min-w-0 gap-1.5", className)} data-service-issue={issue.kind}>
      <span role={issue.tone === "warning" ? "alert" : "status"} className={cn("min-w-0 whitespace-pre-wrap break-words text-ui-sm", TONE_CLASS[issue.tone])}>
        {issue.text}
      </span>
      {lastLine && <code className="timecode min-w-0 break-all text-ui-xs text-muted-foreground">{lastLine}</code>}
      <div className="flex flex-wrap items-center gap-2 empty:hidden">
        <ServiceIssueActions instanceId={instanceId} service={service} issue={issue} onInstall={onInstall} />
      </div>
    </div>
  );
}

/**
 * 只有那一下(原因已经摆在别处的地方用:模型库、工作流库读不出来时,那句话是后端按状态说好的)。
 * 停着:「启动」(部署管理员);起不来、不应答:「日志」;还没装好、要重建:「去本机服务那里」。
 */
export function ServiceIssueActions({
  instanceId,
  service,
  issue,
  onInstall,
}: {
  instanceId: string;
  service: LocalService;
  issue: ServiceIssue;
  onInstall?: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [logs, setLogs] = React.useState(false);
  const start = useMutation({
    mutationFn: () => startLocalService(instanceId),
    onSuccess: (next) => {
      qc.setQueryData(localServiceKey(instanceId), next);
      invalidatePluginDependents(qc);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  return (
    <>
      {issue.action === "start" && service.can_manage && (
        <Button size="sm" variant="outline" loading={start.isPending} onClick={() => start.mutate()}>
          <Play /> {t("localServiceStart")}
        </Button>
      )}
      {issue.action === "logs" && (
        <Button size="sm" variant="outline" onClick={() => setLogs(true)}>
          <FileText /> {t("localServiceLogs")}
        </Button>
      )}
      {issue.action === "install" && onInstall && (
        <Button size="sm" variant="outline" onClick={onInstall}>
          <Wrench /> {t("localServiceIssueGoInstall")}
        </Button>
      )}
      {logs && <LocalServiceLogDialog instanceId={instanceId} title={service.title} onClose={() => setLogs(false)} />}
    </>
  );
}

/**
 * 模型库、工作流库读不出来时该给的那几下。背后的本机服务此刻用不了:按它的状态给(启动、看日志、去本机服务那里 —— 后者走
 * `onCheckSettings`:连接卡上本机服务那一块带着服务器地址那一格的标记);「连一台服务器」照旧是「检查连接设置」。
 */
export function ConnectionFailureActions({ instanceId, onCheckSettings }: { instanceId: string; onCheckSettings?: () => void }) {
  const t = useI18n();
  const service = useLocalService(instanceId, true).data;
  const issue = serviceIssue(service, true);
  if (issue && service) return <ServiceIssueActions instanceId={instanceId} service={service} issue={issue} onInstall={onCheckSettings} />;
  if (!onCheckSettings) return null;
  return (
    <Button variant="outline" onClick={onCheckSettings}>
      <Settings2 size={13} />
      {t("modelLibraryCheckSettings")}
    </Button>
  );
}

/** 日志:它自己说的话(或「让 Mosael 装」那几步的输出)原样摆出来,开着的时候每 1.5 秒拉一次,停在最底下;完整日志在哪个文件写明。 */
export function LocalServiceLogDialog({
  instanceId,
  title,
  source = "service",
  onClose,
}: {
  instanceId: string;
  title: string;
  source?: LocalServiceLogSource;
  onClose: () => void;
}) {
  const t = useI18n();
  const logs = useQuery({
    queryKey: ["local-service-logs", instanceId, source],
    queryFn: () => getLocalServiceLogs(instanceId, 2000, source),
    refetchInterval: 1500,
  });
  const bottom = React.useRef<HTMLPreElement>(null);
  const lines = logs.data?.lines ?? [];
  React.useEffect(() => {
    const element = bottom.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lines.length]);
  return (
    <ModalShell open onOpenChange={(open) => !open && onClose()}
                title={t(source === "install" ? "localServiceInstallLogTitle" : "localServiceLogTitle").replace("{title}", title)}
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
