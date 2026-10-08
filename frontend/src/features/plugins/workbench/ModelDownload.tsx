import React from "react";
import { FailureCard, failureFields } from "@/components/failure/FailureCard";
import { useMutation } from "@tanstack/react-query";
import { Download, Link2, Loader2, Search } from "lucide-react";

import {
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
import { InlineConfirm, PanelNote, useJobWatch, useOnJobDone } from "@/features/plugins/workbench/workbenchParts";
import type { WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";
import { formatBytes } from "@/lib/bytes";
import { cn } from "@/lib/utils";

const SOURCE_LABEL: Record<string, MessageKey> = {
  huggingface: "modelDownloadSourceHuggingface",
  civitai: "modelDownloadSourceCivitai",
  modelscope: "modelDownloadSourceModelscope",
};

type Candidate = NonNullable<ModelSearch["candidates"]>[number];

/**
 * 工作台里「这个模型文件这台 ComfyUI 上没有」的那一块(模型库面板选中的那一格、缺失项面板缺的每个模型共用):
 *
 * - 工作流里写了下载地址:一个醒目的「下载」;
 * - 没写:「找下载地址」—— 插件按文件名(先完整的名字,再去掉扩展名)去 Civitai、HuggingFace、ModelScope 搜,列出候选:哪家、
 *   哪个仓库 / 模型、确切的文件名、多大、什么底模;文件名一字不差的排在前面、标出来,对不上的从不替人选。点一个候选和贴链接
 *   走同一条路(认一下 → 就地确认 → 下载);没搜到就说没搜到,贴链接那一格一直在这儿,不打发人去别的页签;
 * - 确认里写明下到哪台机器的哪个目录、叫什么名字,走 ComfyUI-Manager 时那几件要先知道的事(令牌、进度、取消)和这台服务器
 *   下载走哪条路(模型库报的);下完由调用方刷新下拉、重新检查。
 */
export function ModelDownload({
  target,
  folder,
  wanted,
  url = "",
  doneLabel,
  onDone,
}: {
  target: WorkbenchTarget;
  folder: string;
  /** 工作流要的那个文件(可能带子目录) */
  wanted: string;
  /** 工作流里写着的下载地址(没有是空串) */
  url?: string;
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
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJobWatch(jobId);
  useOnJobDone(job.data, (done) => {
    if (done.status === "succeeded") onDone();
  });
  //: 这台服务器下载走哪条路(ComfyUI-Manager / 本机 / 下不了)和那句说明:模型库报的,和模型库面板同一份缓存
  const library = useModelLibrary(target.instanceId, { staleTime: 30_000 });
  const route = library.data?.download?.route ?? "";
  const search = useMutation({ mutationFn: () => searchModelSources(target.instanceId, filename, folder) });
  const resolve = useMutation({
    mutationFn: (pick: { address: string; name?: string }) => resolveModelLink(target.instanceId, pick.address),
    onSuccess: (found, pick) => {
      setResolved(found);
      setSaveAs(pick.name || found.filename || filename);
    },
  });
  const start = useMutation({
    mutationFn: () =>
      startModelDownload(target.instanceId, {
        workspace_id: target.workspaceId,
        url: resolved!.url,
        folder,
        filename: saveAs,
      }),
    onSuccess: (created) => {
      setResolved(null);
      setJobId(created.id);
    },
  });

  if (jobId) {
    const status = job.data?.status ?? "queued";
    if (status === "failed" && job.data) {
      return <FailureCard size="inline" lines={2} title={t("workbenchDownloadFailed")} {...failureFields(job.data, t("workbenchDownloadFailed"))} />;
    }
    return (
      <PanelNote>
        {status === "succeeded" ? doneLabel : `${t("workbenchDownloading")} ${job.data?.message ?? ""}`}
      </PanelNote>
    );
  }

  const candidates = search.data?.candidates ?? [];
  const failedSources = search.data?.failed ?? [];
  const sourceName = (source: string) => (SOURCE_LABEL[source] ? t(SOURCE_LABEL[source]) : source);
  return (
    <div data-model-download="" className="grid gap-2 rounded-lg border border-dashed border-border p-2.5">
      {url ? (
        <div className="flex min-w-0 items-center gap-2">
          <p className="m-0 min-w-0 flex-1 text-ui-xs leading-relaxed text-muted-foreground">{t("workbenchDownloadHasUrl")}</p>
          <Button size="xs" className="shrink-0" loading={resolve.isPending} onClick={() => resolve.mutate({ address: url })}
                  aria-label={t("workbenchMissingDownloadLabel").replace("{name}", filename)}>
            <Download size={12} />
            {t("workbenchMissingDownload")}
          </Button>
        </div>
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
      {search.isError && <PanelNote tone="error">{errorText(search.error)}</PanelNote>}
      {search.data && (
        candidates.length === 0 ? (
          <PanelNote>{t("workbenchSearchNothing").replace("{name}", filename)}</PanelNote>
        ) : (
          <ul aria-label={t("workbenchSearchResults").replace("{name}", filename)} className="m-0 grid list-none gap-1 p-0">
            {candidates.map((one) => (
              <li key={`${one.source}:${one.url}`}>
                <CandidateRow candidate={one} pending={resolve.isPending && resolve.variables?.address === one.url}
                              onPick={() => resolve.mutate({ address: one.url, name: one.filename })} />
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
                               wanted={filename} />}
          confirmLabel={t("workbenchDownloadStart")}
          pending={start.isPending}
          onCancel={() => setResolved(null)}
          onConfirm={() => start.mutate()}
        />
      )}
    </div>
  );
}

/** 一个候选:哪家、哪个仓库 / 模型、确切的文件名(一字不差的标出来)、多大、什么底模。点它 = 认这个链接。 */
function CandidateRow({ candidate, pending, onPick }: { candidate: Candidate; pending: boolean; onPick: () => void }) {
  const t = useI18n();
  const facts = [
    SOURCE_LABEL[candidate.source] ? t(SOURCE_LABEL[candidate.source]) : candidate.source,
    candidate.size ? formatBytes(candidate.size) : "",
    candidate.base_model,
  ].filter(Boolean);
  return (
    <button
      type="button"
      data-candidate={candidate.exact ? "exact" : "similar"}
      disabled={pending}
      aria-busy={pending || undefined}
      aria-label={t("workbenchSearchPick").replace("{name}", candidate.filename).replace("{repo}", candidate.repo || candidate.title)}
      className={cn(
        "grid w-full min-w-0 cursor-pointer gap-0.5 rounded-md border p-1.5 text-left text-ui-xs",
        candidate.exact ? "border-primary/40 bg-accent/40 hover:bg-accent" : "border-border bg-transparent hover:bg-secondary",
      )}
      onClick={onPick}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        {pending && <Loader2 size={12} className="shrink-0 animate-mosael-spin" />}
        <Truncate className="min-w-0 flex-1 font-medium text-foreground">{candidate.filename}</Truncate>
        {candidate.exact
          ? <CatalogBadge tone="success">{t("workbenchSearchExact")}</CatalogBadge>
          : <CatalogBadge tone="muted">{t("workbenchSearchSimilar")}</CatalogBadge>}
      </span>
      <Truncate className="text-muted-foreground">{candidate.title || candidate.repo}</Truncate>
      <span className="text-ui-2xs text-muted-foreground">{facts.join(" · ")}</span>
    </button>
  );
}

/** 确认里要先知道的事:同名已在、走 ComfyUI-Manager 时令牌 / 进度 / 取消、这台服务器下载走哪条路。 */
function DownloadNotes({ resolved, saveAs, route, note, wanted }: {
  resolved: ModelResolved;
  saveAs: string;
  route: string;
  note: string;
  wanted: string;
}) {
  const t = useI18n();
  const renamed = saveAs !== wanted;
  return (
    <>
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
