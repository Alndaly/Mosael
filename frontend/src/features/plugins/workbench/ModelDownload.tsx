import React from "react";
import { FailureCard, failureFields } from "@/components/failure/FailureCard";
import { onlineManager, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, Link2, Loader2, Search, X } from "lucide-react";

import {
  cancelJob,
  discardModelPartial,
  getJob,
  getModelPartial,
  modelDownloadsQuery,
  resolveModelLink,
  searchModelSources,
  startModelDownload,
  type Job,
  type JobSummary,
  type ModelResolved,
  type ModelSearch,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n, usePreferences } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { modelBaseName } from "@/components/generation/ModelThumb";
import { useModelLibrary } from "@/components/generation/useModelLibrary";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Truncate } from "@/components/ui/truncate";
import { InlineConfirm, jobDone, PanelNote } from "@/features/plugins/workbench/workbenchParts";
import type { WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";
import { formatBytes, formatSpeed } from "@/lib/bytes";
import { parseServerTime, relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

/** `job.result` 里的字节数(后端从插件的结构化 step 事件记下的):认不出就是 null,不当 0。 */
function byteField(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** 任务 `payload` 里的一格(后端建下载任务时写的):不是字符串就是空串。 */
function payloadText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** 任务详情里的 `result`(列表那一份没有它);认不出就当空。 */
function jobResult(job: Job | JobSummary | null): Record<string, unknown> {
  const value = job && "result" in job ? job.result : null;
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

const SOURCE_LABEL: Record<string, MessageKey> = {
  huggingface: "modelDownloadSourceHuggingface",
  civitai: "modelDownloadSourceCivitai",
  modelscope: "modelDownloadSourceModelscope",
};

type Candidate = NonNullable<ModelSearch["candidates"]>[number];
/** 三档置信度(见插件的 model_search / ADR 0038 §9):只有「哈希确认」允许「直接下载」,相近的只给页面。 */
type Confidence = "confirmed" | "exact" | "likely";

/** 工作流声明的哈希里,能拿来**确认是同一个文件**的那一种:SHA256,且 `hash_type` 没写或者是 sha256。
 * md5 / 别的哈希对不上各平台的元数据,不算凭据 —— 没有凭据就不查、不列(见模块说明的「多平台」)。 */
const SHA256 = /^[0-9a-f]{64}$/i;
function verifiedDigest(hash: string, hashType: string): string {
  const digest = hash.trim();
  if (!SHA256.test(digest)) return "";
  const kind = hashType.trim().toLowerCase().replace("-", "");
  return kind === "" || kind === "sha256" ? digest.toLowerCase() : "";
}

/** 一个候选是哪一档:新数据看 `confidence`,老插件只有 `exact`(认不出就当 `exact`/`likely`)。 */
function confidenceOf(candidate: Candidate): Confidence {
  const said = candidate.confidence;
  if (said === "confirmed" || said === "exact" || said === "likely") return said;
  return candidate.exact ? "exact" : "likely";
}

/**
 * 工作台里「这个模型文件这台 ComfyUI 上没有」的那一块(模型库面板选中的那一格、缺失项面板缺的每个模型共用):
 *
 * - 工作流里写了下载地址:一个醒目的「下载」;
 * - 没写:「找下载地址」—— 插件按文件名(先完整的名字,再去掉扩展名)去 Civitai、HuggingFace、ModelScope 搜,列出候选:哪家、
 *   哪个仓库 / 模型、确切的文件名、多大、什么底模。候选分三档,**按档给不同的入口**(ADR 0038 §9):
 *   `confirmed`(哈希对上)才有「直接下载」;`exact`(文件名一字不差)要用户确认;`likely`(去后缀一致 / 名字里含着)
 *   **只给页面**,不主动给直链。算不出哈希时插件会给一句话说清「所以只是同名」,原样显示;
 * - 确认里写明下到哪台机器的哪个目录、叫什么名字,走 ComfyUI-Manager 时那几件要先知道的事(令牌、进度、取消)和这台服务器
 *   下载走哪条路(模型库报的);下完由调用方刷新下拉、重新检查。
 * - **正在下载时那一行上有「取消」**(走任务中心同一条 `cancelJob`):取消了就说清「已取消,没下完的部分已删掉」;
 *   任务在点下去的那一刻刚好结束的,说「已经结束了,不用取消」,不当成取消失败吓人。
 * - **工作流写了地址时**:把那个地址本身完整地摆在「下载」那一行的下面(放不下就折行;不用悬停浮层)。另外只在**能确认是同一个文件**时列别的
 *   平台:工作流声明了 SHA256,拿去问插件(搜索的 `confirmed` 只在这一条上给),平台元数据里也是这个 SHA256 的才算;
 *   没有 SHA256(也没有该平台的明确 id)就不查、不列 —— 不靠文件名相近冒充。查询失败 / 超时 / 离线只是那一块不出现,
 *   原来那个地址照样能下。只有本机那条下载路能下完核对哈希;只能经 ComfyUI-Manager 的时代替它下,核对不了,所以不列。
 *   下载时把这个 SHA256 也交给插件:下完再算一遍,对不上就删掉、说清。
 */
export function ModelDownload({
  target,
  folder,
  wanted,
  url = "",
  hash = "",
  hashType = "",
  doneLabel,
  onDone,
}: {
  target: WorkbenchTarget;
  folder: string;
  /** 工作流要的那个文件(可能带子目录) */
  wanted: string;
  /** 工作流里写着的下载地址(没有是空串) */
  url?: string;
  /** 工作流自己声明的哈希(没有是空串):交给插件去认 `confirmed` */
  hash?: string;
  hashType?: string;
  /** 下完之后那句话(刷新得了下拉 / 刷新不了) */
  doneLabel: string;
  onDone: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const filename = modelBaseName(wanted);
  const [link, setLink] = React.useState("");
  const [resolved, setResolved] = React.useState<ModelResolved | null>(null);
  //: 下下来叫什么。点的是搜到的候选:用候选的文件名 —— Civitai 一个版本有几个文件时,认出来的名字是「名字_文件号」,
  //: 下下来却不是工作流要的那个名字,工作流照样找不到它
  const [saveAs, setSaveAs] = React.useState("");
  //: 这一次下载要核对的 SHA256(只有「确认是同一个文件」的那几档才带):下完插件再算一遍,对不上就删掉。
  const [digest, setDigest] = React.useState("");
  //: 删掉没下完的部分之后的那一句(任务那一行已经不在了,得在下载框里说)。
  const [notice, setNotice] = React.useState<"" | "discarded">("");
  const qc = useQueryClient();
  //: 这一块要的那个文件,认的是任务 `payload` 里的 `instance_id + folder + filename`(后端建任务时写的,
  //: 见 domain/model_library.start_download)。**状态的家是这份任务列表,不是组件 state**:刷新、切走再切回,
  //: 「正在下载 / 已取消 / 从 N 继续」都还在。
  const downloadsQuery = React.useMemo(() => modelDownloadsQuery(target.workspaceId), [target.workspaceId]);
  const downloads = useQuery({
    ...downloadsQuery,
    //: 有没下完的就勤看一点(和任务中心同一条规矩);都结束了就慢下来。
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => !jobDone(job)) ? 1500 : 8000,
  });
  const mine = React.useMemo(
    () => (downloads.data ?? []).filter((job) => {
      const payload = job.payload ?? {};
      const name = payloadText(payload.filename);
      //: 任务可能下成别的名字(Civitai 一个版本有几个文件),工作流要的那个名字也认。
      return payload.instance_id === target.instanceId && payload.folder === folder
        && (name === filename || name === wanted);
    }),
    [downloads.data, target.instanceId, folder, filename, wanted],
  );
  //: 最新**未终态**的优先(它还在写);都结束了才取最新的一条。按 `created_at` 排,不赖接口给的顺序。
  const latest = React.useMemo(() => {
    const newestFirst = [...mine].sort((a, b) =>
      parseServerTime(b.created_at).getTime() - parseServerTime(a.created_at).getTime());
    return newestFirst.find((job) => !jobDone(job)) ?? newestFirst[0] ?? null;
  }, [mine]);
  //: 列表里不带 `result`(字节 / 速度只在详情里):盯着的那条还在跑时再问一次详情。
  const detail = useQuery({
    queryKey: ["jobs", "workbench", latest?.id],
    queryFn: () => getJob(latest!.id),
    enabled: Boolean(latest && !jobDone(latest)),
    refetchInterval: 1500,
    retry: false,
  });
  //: 这一行的状态就是任务里的那个;详情那份到了就用它(它比列表勤,取消 / 失败的最后一份字节也在里面)。
  const current: Job | JobSummary | null =
    latest && detail.data && detail.data.id === latest.id ? detail.data : latest;
  //: 「做完了」只在这个面板**看着它做**的那一次通知调用方:首次挂载时已经是终态的是历史,不触发。
  const seenActive = React.useRef<string | null>(null);
  const announcedDone = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!current) return;
    if (!jobDone(current)) {
      seenActive.current = current.id;
      return;
    }
    if (current.status !== "succeeded" || seenActive.current !== current.id || announcedDone.current === current.id) return;
    announcedDone.current = current.id;
    onDone();
  }, [current, onDone]);
  //: 取消 / 开始之后把任务写回这一份列表缓存(**不存 id**):界面仍只看任务列表。
  const writeJob = React.useCallback((job: Job) => {
    qc.setQueryData<JobSummary[]>(downloadsQuery.queryKey, (rows) => {
      if (!rows) return [job];
      return rows.some((one) => one.id === job.id)
        ? rows.map((one) => (one.id === job.id
          //: 接口有时只回「变了的那几格」:匹配用的 payload 别被空的那份盖掉。
          ? { ...one, ...job, payload: job.payload && Object.keys(job.payload).length ? job.payload : one.payload }
          : one))
        : [job, ...rows];
    });
  }, [qc, downloadsQuery.queryKey]);
  //: 续传要的那几样也从任务的 payload 里来(刷新之后照样能「从 N 继续」):URL / 文件名 / 声明哈希
  //: 都是建任务时写下的那一份。
  const source = React.useMemo(() => {
    //: 认出来的是列表里那一行(它带着匹配用的 payload);详情只补状态和字节。
    const payload: Record<string, unknown> = latest?.payload ?? current?.payload ?? {};
    return {
      url: payloadText(payload.url),
      filename: payloadText(payload.filename) || filename,
      sha256: payloadText(payload.sha256),
    };
  }, [latest, current, filename]);
  //: 这台服务器下载走哪条路(ComfyUI-Manager / 本机 / 下不了)和那句说明:模型库报的,和模型库面板同一份缓存
  const library = useModelLibrary(target.instanceId, { staleTime: 30_000 });
  const route = library.data?.download?.route ?? "";
  //: 离线时**整个多平台都不出现**(不是灰着、也不是拿缓存里的旧候选骗人):本来也连不上平台。
  const [online, setOnline] = React.useState(() => onlineManager.isOnline());
  React.useEffect(() => onlineManager.subscribe((next) => setOnline(next)), []);
  //: 工作流自己声明的 SHA256:唯一一种**不靠猜**的跨平台确认凭据。
  const declared = verifiedDigest(hash, hashType);
  //: 只有本机那条路能下完再算一遍哈希;经 ComfyUI-Manager 的下载在那台机器上,Mosael 核对不了,就不列别的来源。
  const verifiedRoute = Boolean(url) && Boolean(declared) && route === "local" && online;
  //: 另找的平台:问的是插件那套搜索(`confirmed` 只给哈希对上的),查询失败 / 超时 / 离线只是不出现,不影响原地址。
  const elsewhere = useQuery({
    queryKey: ["model-sources", target.instanceId, folder, filename, declared],
    queryFn: () => searchModelSources(target.instanceId, filename, folder, declared, "sha256"),
    enabled: verifiedRoute,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const alternates = React.useMemo(() => {
    //: 只留**三样都对上**的:置信度是 confirmed、插件给的 SHA256 就是工作流声明的那个、不是原来那个地址。
    //: 后端还会按同一份凭据再规整一遍(见 model_library.search_sources);这里是界面这一侧的守卫。
    const seen = new Set<string>();
    return (elsewhere.data?.candidates ?? []).filter((one) => {
      if (confidenceOf(one) !== "confirmed" || !one.direct) return false;
      if ((one.sha256 ?? "").toLowerCase() !== declared) return false;
      const address = one.url.toLowerCase();
      if (address === url.toLowerCase() || seen.has(address)) return false;
      seen.add(address);
      return true;
    });
  }, [elsewhere.data, declared, url]);
  const search = useMutation({
    mutationFn: () => searchModelSources(target.instanceId, filename, folder, hash, hashType),
  });
  const resolve = useMutation({
    mutationFn: (pick: { address: string; name?: string; sha256?: string }) =>
      resolveModelLink(target.instanceId, pick.address),
    onSuccess: (found, pick) => {
      setNotice("");
      setResolved(found);
      setSaveAs(pick.name || found.filename || filename);
      setDigest(pick.sha256 || "");
    },
  });
  const start = useMutation({
    mutationFn: (download: { url: string; filename: string; sha256: string }) =>
      startModelDownload(target.instanceId, {
        workspace_id: target.workspaceId,
        url: download.url,
        folder,
        filename: download.filename,
        ...(download.sha256 ? { sha256: download.sha256 } : {}),
      }),
    onSuccess: (created, download) => {
      setResolved(null);
      setDigest("");
      setNotice("");
      //: 匹配键要 payload 里的那几样(后端建的这份一定有):只回了半条时,拿刚才发出去的那一份补齐,
      //: 免得这一行当场从列表里认不出来。
      const job: Job = created.payload && Object.keys(created.payload).length ? created : {
        ...created,
        payload: {
          instance_id: target.instanceId, url: download.url, folder, filename: download.filename,
          ...(download.sha256 ? { sha256: download.sha256 } : {}),
        },
      };
      //: 刚由我们发起的这一条:哪怕它已经结束了,也是「刚做完」,该通知调用方刷新;先记成「看见过它」。
      seenActive.current = job.id;
      //: **把 POST 回来的任务写进列表缓存,不存 id** —— 后面的状态、取消、续传都从这份缓存派生。
      writeJob(job);
      qc.setQueryData(["jobs", "workbench", job.id], job);
    },
  });
  //: 取消没成功时那一句该说什么。**任务在请求到达前刚好结束不是取消失败** —— 那一下本来也没有可取消的东西,
  //: 用一句错误去吓人只会让人以为出了别的事(任务的终态由那一行自己说)。
  const [cancelNote, setCancelNote] = React.useState<"" | "failed" | "ended">("");
  const cancel = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: (stopped) => {
      setCancelNote("");
      //: 取消接口回的就是取消后的那一条:直接写进这份缓存(列表 + 详情),不必等下一轮轮询。
      writeJob(stopped);
      qc.setQueryData(["jobs", "workbench", stopped.id], stopped);
      //: 取消**不删**半截(断点续传):这一行下面马上要问它还剩多少,好让人「继续下载」。
      void qc.invalidateQueries({ queryKey: ["model-partial", target.instanceId] });
    },
    onError: async (_error, jobId) => {
      try {
        const fresh = await getJob(jobId);
        writeJob(fresh);
        qc.setQueryData(["jobs", "workbench", jobId], fresh);
        setCancelNote(jobDone(fresh) ? "ended" : "failed");
      } catch {
        //: 连它现在是什么都读不回来:只能照实说这次取消没成。
        setCancelNote("failed");
      }
    },
  });

  //: 任务停在**取消 / 失败**之后才问半截:本机那条路才有,而且这时它不再被写,「从多少继续」才作数。
  //: Manager 那条路是那台机器自己在下,Mosael 这边没有半截 —— 不问、也不给删除(那不是 Mosael 能删的东西)。
  const stoppedOrFailed = Boolean(current && (current.status === "cancelled" || current.status === "failed"));
  const partialKey = ["model-partial", target.instanceId, folder, source.filename, source.url, source.sha256] as const;
  const partial = useQuery({
    queryKey: partialKey,
    queryFn: () => getModelPartial(target.instanceId, {
      workspace_id: target.workspaceId,
      folder,
      name: source.filename,
      ...(source.url ? { url: source.url } : {}),
      ...(source.sha256 ? { sha256: source.sha256 } : {}),
    }),
    enabled: stoppedOrFailed && Boolean(source.url) && route === "local",
    retry: false,
  });
  const discard = useMutation({
    mutationFn: () => discardModelPartial(target.instanceId, {
      workspace_id: target.workspaceId, folder, name: source.filename,
    }),
    onSuccess: (left) => {
      //: 删除接口回的就是删完之后的那一份:直接写进这份缓存,那一行当场知道「没有半截了」,不必再问一遍。
      qc.setQueryData(partialKey, left);
      setNotice("discarded");
      setCancelNote("");
    },
  });

  const status = current?.status ?? "";
  const stopped = status === "cancelled";
  const failed = status === "failed" && Boolean(current);
  const running = status === "queued" || status === "running";
  const halted = stopped || failed;
  const kept = halted && Boolean(partial.data?.partial);
  const partialBytes = kept ? partial.data?.downloaded_bytes ?? null : null;
  const resumable = kept && Boolean(partial.data?.resumable) && (partialBytes ?? 0) > 0;
  //: 字节 / 速度只从**结构化字段**来(`result` 是插件 step 事件记下的);列表里不带 `result`,详情里才有。
  const result = jobResult(current);
  const gotBytes = byteField(result.downloaded_bytes);
  const gotTotal = byteField(result.total_bytes);
  const speed = byteField(result.speed_bps);
  //: 能拿到字节就按字节算;拿不到才退回任务的总进度(它也是插件按字节算出来的分数)
  const percent = Math.min(100, Math.max(0, gotBytes !== null && gotTotal
    ? Math.round((gotBytes / gotTotal) * 100)
    : Math.round((current?.progress ?? 0) * 100)));
  //: 终态那一行说「最后一次 …」:时间取这次下载最后动过的那一刻。
  const lastAt = current?.updated_at || current?.created_at || "";
  //: 上一次已经结束了(取消 / 失败)时下载框还留着 —— 半截在就接着下,不在就能从头再下;
  //: 成功的不必再摆一个「下载」。
  const showEntry = !current || (jobDone(current) && current.status !== "succeeded");
  const jobBlock = current ? (
    <div className="grid gap-2" data-model-download-job={current.id} data-model-download-status={current.status}>
      {failed
        ? <FailureCard size="inline" lines={2} title={t("workbenchDownloadFailed")} {...failureFields(current!, t("workbenchDownloadFailed"))} />
        : (
          <PanelNote
            action={running ? (
              <Button variant="ghost" size="xs" className="shrink-0" loading={cancel.isPending}
                      aria-label={t("workbenchDownloadCancelLabel").replace("{name}", source.filename || filename)}
                      onClick={() => cancel.mutate(current.id)}>
                <X size={12} />
                {t("cancel")}
              </Button>
            ) : undefined}
          >
            {/* 取消在两条路上不是同一件事:本机那条路半截**留着**供续传(这一段下面就有「继续下载」);
                Manager 那条路是那台机器自己在下,Mosael 只是不再等(插件已经说清了),不能说「留着」或「删了」。
                删掉半截之后,那一行也不能还说「留着」。 */}
            {stopped ? (notice === "discarded" ? t("workbenchDownloadDiscardDone")
              : t(route === "manager" ? "workbenchDownloadCancelledManager" : "workbenchDownloadCancelled"))
              : status === "succeeded" ? doneLabel
              : `${t("workbenchDownloading")} ${current.message ?? ""}`}
          </PanelNote>
        )}
      {running && (
        <div className="grid gap-1">
          <Progress value={percent} aria-label={t("workbenchDownloading")} />
          <p className="m-0 break-words text-ui-2xs leading-relaxed text-muted-foreground">
            {gotBytes !== null && (gotTotal !== null
              ? t("workbenchDownloadProgress").replace("{downloaded}", formatBytes(gotBytes))
                  .replace("{total}", formatBytes(gotTotal))
              : t("workbenchDownloadProgressUnknown").replace("{downloaded}", formatBytes(gotBytes)))}
            {gotBytes !== null && ` · ${percent}%`}
            {speed !== null && speed > 0 && ` · ${formatSpeed(speed)}`}
          </p>
        </div>
      )}
      {jobDone(current) && lastAt && (
        <p className="m-0 text-ui-2xs leading-relaxed text-muted-foreground">
          {t("workbenchDownloadLastAt").replace("{time}", relativeTime(lastAt, locale))}
        </p>
      )}
      {kept && (
        <PanelNote>
          {t("workbenchDownloadPartialKept").replace("{size}", formatBytes(partialBytes ?? 0))}
        </PanelNote>
      )}
      {kept && !resumable && (
        <PanelNote tone="warning">{t("workbenchDownloadNotResumable")}</PanelNote>
      )}
      {halted && (
        <div className="flex flex-wrap gap-1.5">
          {resumable && (
            <Button size="xs" loading={start.isPending} onClick={() => start.mutate(source)}>
              {partialBytes !== null
                ? t("workbenchDownloadResumeFrom").replace("{size}", formatBytes(partialBytes))
                : t("workbenchDownloadResume")}
            </Button>
          )}
          {kept && (
            <Button variant="outline" size="xs" loading={discard.isPending} onClick={() => discard.mutate()}>
              {t("workbenchDownloadDiscardPart")}
            </Button>
          )}
        </div>
      )}
      {start.isError && <PanelNote tone="error">{errorText(start.error)}</PanelNote>}
      {partial.isError && <PanelNote tone="error">{errorText(partial.error)}</PanelNote>}
      {discard.isError && (
        <PanelNote tone="error">
          {t("workbenchDownloadDiscardFailed").replace("{message}", errorText(discard.error))}
        </PanelNote>
      )}
      {cancelNote === "ended" && <PanelNote>{t("workbenchDownloadCancelEnded")}</PanelNote>}
      {cancelNote === "failed" && (
        <PanelNote tone="error">
          {t("workbenchDownloadCancelFailed").replace("{message}", errorText(cancel.error))}
        </PanelNote>
      )}
    </div>
  ) : null;

  const candidates = search.data?.candidates ?? [];
  const failedSources = search.data?.failed ?? [];
  const sourceName = (source: string) => (SOURCE_LABEL[source] ? t(SOURCE_LABEL[source]) : source);
  if (!showEntry) {
    return <div data-model-download="" className="grid gap-2">{jobBlock}</div>;
  }
  return (
    <div data-model-download="" className="grid gap-2 rounded-lg border border-dashed border-border p-2.5">
      {jobBlock}
      {!current && notice === "discarded" && <PanelNote>{t("workbenchDownloadDiscardDone")}</PanelNote>}
      {url ? (
        <>
          <div className="flex min-w-0 items-center gap-2">
            <p className="m-0 min-w-0 flex-1 text-ui-xs leading-relaxed text-muted-foreground">{t("workbenchDownloadHasUrl")}</p>
            <Button size="xs" className="shrink-0" loading={resolve.isPending} onClick={() => resolve.mutate({ address: url })}
                    aria-label={t("workbenchMissingDownloadLabel").replace("{name}", filename)}>
              <Download size={12} />
              {t("workbenchMissingDownload")}
            </Button>
          </div>
          {/* 那个地址本身:完整地摆在「下载」那一行的下面,放不下就在任意处折行 —— **不套悬停浮层**:
              工作台那一列的说明默认朝左(见 ComfyWorkbench 的 COLUMN_REGION),长地址会撑满一条飘到画布上。
              点它在新窗口打开;文字本身可选中、可复制。没写地址时整行都不出现。 */}
          <a href={url} target="_blank" rel="noreferrer noopener" data-declared-url=""
             className="flex min-w-0 items-start gap-1.5 text-ui-2xs leading-relaxed text-muted-foreground hover:text-foreground hover:underline">
            <span className="min-w-0 flex-1 break-all">{url}</span>
            <ExternalLink size={11} aria-hidden className="mt-0.5 shrink-0" />
          </a>
        </>
      ) : (
        <div className="flex min-w-0 items-center gap-2">
          <p className="m-0 min-w-0 flex-1 text-ui-xs leading-relaxed text-muted-foreground">
            {t("workbenchDownloadNoUrl").replace("{name}", filename).replace("{folder}", folder)}
          </p>
          <Button variant="outline" size="xs" className="shrink-0" loading={search.isPending} onClick={() => search.mutate()}
                  aria-label={t("workbenchSearchSourcesLabel").replace("{name}", filename)}>
            <Search size={12} />
            {t("workbenchSearchSources")}
          </Button>
        </div>
      )}
      {online && alternates.length > 0 && (
        <section aria-label={t("workbenchDownloadOtherSources")} data-other-sources="" className="grid gap-1">
          <p className="m-0 text-ui-2xs leading-relaxed text-muted-foreground">{t("workbenchDownloadOtherSources")}</p>
          <ul className="m-0 grid list-none gap-1 p-0">
            {alternates.map((one) => (
              <li key={`${one.source}:${one.url}`} data-alternate-source={one.source}
                  className="grid gap-0.5 rounded-md border border-border p-1.5">
                <span className="flex min-w-0 items-center gap-1.5">
                  <Truncate className="min-w-0 flex-1 font-medium text-foreground">{one.filename}</Truncate>
                  <CatalogBadge tone="success">{t("workbenchSearchConfirmed")}</CatalogBadge>
                  <Button size="xs" className="shrink-0" loading={resolve.isPending && resolve.variables?.address === one.url}
                          onClick={() => resolve.mutate({ address: one.url, name: filename, sha256: one.sha256 ?? "" })}
                          aria-label={t("workbenchDownloadFromSource").replace("{source}", sourceName(one.source))
                            .replace("{name}", one.filename)}>
                    <Download size={12} />
                    {t("workbenchMissingDownload")}
                  </Button>
                </span>
                <span className="flex min-w-0 items-center gap-1.5 text-ui-2xs text-muted-foreground">
                  <span className="shrink-0">{sourceName(one.source)}</span>
                  <Truncate className="min-w-0 flex-1">{one.title || one.repo}</Truncate>
                  {one.page && (
                    <a href={one.page} target="_blank" rel="noreferrer noopener" data-alternate-page=""
                       aria-label={t("workbenchDownloadSourcePage").replace("{source}", sourceName(one.source))
                         .replace("{name}", one.filename)}
                       className="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground">
                      <ExternalLink size={11} aria-hidden />
                    </a>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {search.isError && <PanelNote tone="error">{errorText(search.error)}</PanelNote>}
      {/* 哈希这一项:确认到哪一个了,或者为什么没得算 —— 插件的原话(它按界面语言写好了),原样说给用户 */}
      {search.data?.hash?.note && (
        <PanelNote tone={search.data.hash.state === "matched" ? "info" : "warning"}>{search.data.hash.note}</PanelNote>
      )}
      {search.data && (
        candidates.length === 0 ? (
          <PanelNote>{t("workbenchSearchNothing").replace("{name}", filename)}</PanelNote>
        ) : (
          <ul aria-label={t("workbenchSearchResults").replace("{name}", filename)} className="m-0 grid list-none gap-1 p-0">
            {candidates.map((one) => (
              <li key={`${one.source}:${one.url}`}>
                <CandidateRow candidate={one} pending={resolve.isPending && resolve.variables?.address === one.url}
                              onPick={() => resolve.mutate({
                                address: one.url, name: one.filename,
                                //: 这套搜索里 `confirmed` 才是哈希对上的;本机那条路下完能再核对一遍,别的不带哈希。
                                sha256: route === "local" && confidenceOf(one) === "confirmed" ? one.sha256 ?? "" : "",
                              })} />
              </li>
            ))}
          </ul>
        )
      )}
      {failedSources.length > 0 && (
        <p className="m-0 text-ui-2xs text-muted-foreground">
          {t("workbenchSearchFailed").replace("{sources}", failedSources.map((one) => sourceName(one.source)).join("、"))}
        </p>
      )}
      {/* 贴链接一直在(工作流写了地址、那个地址也认得出时不用):搜不到、搜到的不对,都在这里接着办 */}
      {(!url || resolve.isError) && <div className="flex min-w-0 gap-1.5">
        <Input size="xs" className="min-w-0 flex-1" value={link} placeholder={t("workbenchDownloadLink")}
               aria-label={t("workbenchDownloadLink")} onChange={(event) => setLink(event.target.value)} />
        <Button variant="outline" size="xs" disabled={!/^https?:\/\//i.test(link.trim())}
                loading={resolve.isPending && resolve.variables?.address === link.trim()}
                onClick={() => resolve.mutate({ address: link.trim() })}>
          <Link2 size={12} />
          {t("workbenchDownloadResolve")}
        </Button>
      </div>}
      {resolve.isError && <PanelNote tone="error">{errorText(resolve.error)}</PanelNote>}
      {start.isError && <PanelNote tone="error">{errorText(start.error)}</PanelNote>}
      {resolved && (
        <InlineConfirm
          title={t("workbenchDownloadConfirm").replace("{server}", target.instanceName).replace("{folder}", folder)
            .replace("{name}", saveAs)}
          body={<DownloadNotes resolved={resolved} saveAs={saveAs} route={route} note={library.data?.download?.note ?? ""}
                               wanted={filename} sha256={digest} />}
          confirmLabel={t("workbenchDownloadStart")}
          pending={start.isPending}
          onCancel={() => {
            setResolved(null);
            setDigest("");
          }}
          onConfirm={() => start.mutate({ url: resolved!.url, filename: saveAs, sha256: digest })}
        />
      )}
    </div>
  );
}

/**
 * 一个候选:哪家、哪个仓库 / 模型、确切的文件名、多大、什么底模;按置信度给不同的入口(见模块说明)。
 *
 * - `confirmed`(哈希对上):**直接下载** —— 唯一允许这样的一档;
 * - `exact`(文件名一字不差):**确认后下载**(走同一个「认一下 → 就地确认」),文案里写明还没算过哈希;
 * - `likely`(去后缀一致 / 名字里含着):**只有页面**,不主动给直链。
 */
function CandidateRow({ candidate, pending, onPick }: { candidate: Candidate; pending: boolean; onPick: () => void }) {
  const t = useI18n();
  const confidence = confidenceOf(candidate);
  const facts = [
    SOURCE_LABEL[candidate.source] ? t(SOURCE_LABEL[candidate.source]) : candidate.source,
    candidate.size ? formatBytes(candidate.size) : "",
    candidate.base_model,
  ].filter(Boolean);
  const badge = confidence === "confirmed"
    ? <CatalogBadge tone="success">{t("workbenchSearchConfirmed")}</CatalogBadge>
    : confidence === "exact"
      ? <CatalogBadge tone="muted">{t("workbenchSearchExact")}</CatalogBadge>
      : <CatalogBadge tone="muted">{t("workbenchSearchSimilar")}</CatalogBadge>;
  const name = <Truncate className="min-w-0 flex-1 font-medium text-foreground">{candidate.filename}</Truncate>;
  const title = <Truncate className="text-muted-foreground">{candidate.title || candidate.repo}</Truncate>;
  const meta = <span className="text-ui-2xs text-muted-foreground">{facts.join(" · ")}</span>;
  const shape = cn(
    "grid w-full min-w-0 gap-0.5 rounded-md border p-1.5 text-left text-ui-xs",
    confidence === "confirmed" ? "border-primary/40 bg-accent/40 hover:bg-accent" : "border-border bg-transparent",
    confidence === "likely" ? "" : "cursor-pointer hover:bg-secondary",
  );
  //: 相近的(去后缀一致、名字里含着)只给页面:没有「直接下载」这个入口,连直链都不主动摆出来。
  if (confidence === "likely") {
    return (
      <a href={candidate.page || candidate.url} target="_blank" rel="noreferrer noopener" data-candidate="likely"
         aria-label={t("workbenchSearchOpenPage").replace("{name}", candidate.filename)}
         className={cn(shape, "hover:bg-secondary")}>
        <span className="flex min-w-0 items-center gap-1.5">{name}{badge}</span>
        {title}
        {meta}
      </a>
    );
  }
  return (
    <button type="button" data-candidate={confidence} disabled={pending} aria-busy={pending || undefined}
            aria-label={(confidence === "confirmed" ? t("workbenchSearchDirectDownload") : t("workbenchSearchConfirmDownload"))
              .replace("{name}", candidate.filename).replace("{repo}", candidate.repo || candidate.title)}
            className={shape}
            onClick={onPick}>
      <span className="flex min-w-0 items-center gap-1.5">
        {pending && <Loader2 size={12} className="shrink-0 animate-mosael-spin" />}
        {name}
        {badge}
      </span>
      {title}
      {meta}
    </button>
  );
}

/** 确认里要先知道的事:同名已在、走 ComfyUI-Manager 时令牌 / 进度 / 取消、这台服务器下载走哪条路。 */
function DownloadNotes({ resolved, saveAs, route, note, wanted, sha256 }: {
  resolved: ModelResolved;
  saveAs: string;
  route: string;
  note: string;
  wanted: string;
  /** 这一次下载要核对的 SHA256(没有是空串):确认里先说清下完还会核对 */
  sha256: string;
}) {
  const t = useI18n();
  const renamed = saveAs !== wanted;
  return (
    <>
      {sha256 && <span data-download-verified="">{t("workbenchDownloadVerifiedHint")}</span>}
      {renamed && <span>{t("workbenchDownloadOtherName").replace("{name}", saveAs).replace("{wanted}", wanted)}</span>}
      {resolved.exists && <span className="text-warning">{t("workbenchDownloadExists")}</span>}
      {route === "manager" && (
        <ul className="m-0 grid list-disc gap-0.5 pl-4">
          {resolved.source === "civitai" && resolved.uses_token && <li>{t("modelDownloadCivitaiTokenInUrl")}</li>}
          {resolved.source === "huggingface" && resolved.uses_token && <li>{t("modelDownloadHfTokenUnsupported")}</li>}
          {resolved.source === "modelscope" && resolved.uses_token && <li>{t("modelDownloadModelscopeTokenUnsupported")}</li>}
          <li>{t("modelDownloadManagerNoProgress")}</li>
          <li>{t("modelDownloadManagerCancel")}</li>
        </ul>
      )}
      {note && <span className={route === "none" ? "text-destructive" : undefined}>{note}</span>}
    </>
  );
}
