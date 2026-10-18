import React from "react";
import { FailureCard, failureFields } from "@/components/failure/FailureCard";
import { onlineManager, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, Link2, Loader2, Search, X } from "lucide-react";

import {
  cancelJob,
  getJob,
  resolveModelLink,
  searchModelSources,
  startModelDownload,
  type ModelResolved,
  type ModelSearch,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { modelBaseName } from "@/components/generation/ModelThumb";
import { useModelLibrary } from "@/components/generation/useModelLibrary";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Truncate } from "@/components/ui/truncate";
import { InlineConfirm, jobDone, PanelNote, useJobWatch, useOnJobDone } from "@/features/plugins/workbench/workbenchParts";
import type { WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";
import { formatBytes } from "@/lib/bytes";
import { cn } from "@/lib/utils";

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
  const filename = modelBaseName(wanted);
  const [link, setLink] = React.useState("");
  const [resolved, setResolved] = React.useState<ModelResolved | null>(null);
  //: 下下来叫什么。点的是搜到的候选:用候选的文件名 —— Civitai 一个版本有几个文件时,认出来的名字是「名字_文件号」,
  //: 下下来却不是工作流要的那个名字,工作流照样找不到它
  const [saveAs, setSaveAs] = React.useState("");
  //: 这一次下载要核对的 SHA256(只有「确认是同一个文件」的那几档才带):下完插件再算一遍,对不上就删掉。
  const [digest, setDigest] = React.useState("");
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJobWatch(jobId);
  useOnJobDone(job.data, (done) => {
    if (done.status === "succeeded") onDone();
  });
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
      setResolved(found);
      setSaveAs(pick.name || found.filename || filename);
      setDigest(pick.sha256 || "");
    },
  });
  const start = useMutation({
    mutationFn: () =>
      startModelDownload(target.instanceId, {
        workspace_id: target.workspaceId,
        url: resolved!.url,
        folder,
        filename: saveAs,
        ...(digest ? { sha256: digest } : {}),
      }),
    onSuccess: (created) => {
      setResolved(null);
      setDigest("");
      setJobId(created.id);
    },
  });
  const qc = useQueryClient();
  //: 取消没成功时那一句该说什么。**任务在请求到达前刚好结束不是取消失败** —— 那一下本来也没有可取消的东西,
  //: 用一句错误去吓人只会让人以为出了别的事(任务的终态由那一行自己说)。
  const [cancelNote, setCancelNote] = React.useState<"" | "failed" | "ended">("");
  const cancel = useMutation({
    mutationFn: () => cancelJob(jobId!),
    onSuccess: (stopped) => {
      setCancelNote("");
      //: 取消接口回的就是取消后的那一条:直接写进这一行盯着的那份缓存,不必等下一轮轮询。
      qc.setQueryData(["jobs", "workbench", jobId], stopped);
    },
    onError: async () => {
      try {
        const fresh = await getJob(jobId!);
        qc.setQueryData(["jobs", "workbench", jobId], fresh);
        setCancelNote(jobDone(fresh) ? "ended" : "failed");
      } catch {
        //: 连它现在是什么都读不回来:只能照实说这次取消没成。
        setCancelNote("failed");
      }
    },
  });

  if (jobId) {
    const status = job.data?.status ?? "queued";
    const stopped = status === "cancelled";
    const body = status === "failed" && job.data
      ? <FailureCard size="inline" lines={2} title={t("workbenchDownloadFailed")} {...failureFields(job.data, t("workbenchDownloadFailed"))} />
      : (
        <PanelNote
          action={stopped || status === "succeeded" ? undefined : (
            <Button variant="ghost" size="xs" className="shrink-0" loading={cancel.isPending}
                    aria-label={t("workbenchDownloadCancelLabel").replace("{name}", saveAs || filename)}
                    onClick={() => cancel.mutate()}>
              <X size={12} />
              {t("cancel")}
            </Button>
          )}
        >
          {/* 取消在两条路上不是同一件事:本机那条路半截文件当场删掉;Manager 那条路是那台机器自己在下,
              Mosael 只是不再等(插件已经说清了),不能跟着说「已删掉」。 */}
          {stopped ? t(route === "manager" ? "workbenchDownloadCancelledManager" : "workbenchDownloadCancelled")
            : status === "succeeded" ? doneLabel
            : `${t("workbenchDownloading")} ${job.data?.message ?? ""}`}
        </PanelNote>
      );
    return (
      <div className="grid gap-2">
        {body}
        {cancelNote === "ended" && <PanelNote>{t("workbenchDownloadCancelEnded")}</PanelNote>}
        {cancelNote === "failed" && (
          <PanelNote tone="error">
            {t("workbenchDownloadCancelFailed").replace("{message}", errorText(cancel.error))}
          </PanelNote>
        )}
      </div>
    );
  }

  const candidates = search.data?.candidates ?? [];
  const failedSources = search.data?.failed ?? [];
  const sourceName = (source: string) => (SOURCE_LABEL[source] ? t(SOURCE_LABEL[source]) : source);
  return (
    <div data-model-download="" className="grid gap-2 rounded-lg border border-dashed border-border p-2.5">
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
          onConfirm={() => start.mutate()}
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
