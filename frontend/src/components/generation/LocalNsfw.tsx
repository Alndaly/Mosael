import React from "react";
import { useIsFetching, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Repeat, ScanEye } from "lucide-react";

import { getLocalNsfw, installLocalNsfw, type ModelLocalNsfw } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useIsDeploymentAdmin } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/bytes";
import { gotoAdmin } from "@/lib/deepLink";

export const LOCAL_NSFW_KEY = ["model-local-nsfw"] as const;

/** 在下、在识别的时候隔多久问一次进度。 */
const POLL_MS = 2000;

//: 同一次状态变化只作废一次(几颗按钮各挂着一个 useLocalNsfw)
let handled = 0;

const busy = (status: ModelLocalNsfw | undefined) => status?.status === "installing" || (status?.pending ?? 0) > 0;

/**
 * 本机识别的状态(ADR 0038 §9):权重下了没有、识别排着几张。**列模型库不等识别**(没结果的排进队,下次列出就有),所以
 * 这里把「下次」接上:每列完一次模型库问一次进度;在下、在识别时每两秒问一次;下好了、排着的识别完了,让模型库重新列一遍
 * —— 结果就出现在卡片上。几处同时挂着时(工作台每一格一颗)只有一处去作废。
 */
export function useLocalNsfw() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: LOCAL_NSFW_KEY,
    queryFn: () => getLocalNsfw(),
    staleTime: 30_000,
    refetchInterval: (query) => (busy(query.state.data) ? POLL_MS : false),
  });
  //: 列完一次模型库(在列的从有到无),问一次 —— 那一次列可能刚排进去一批
  const listing = useIsFetching({ queryKey: ["model-library"] });
  const wasListing = React.useRef(listing);
  React.useEffect(() => {
    if (wasListing.current > 0 && listing === 0) void qc.invalidateQueries({ queryKey: LOCAL_NSFW_KEY });
    wasListing.current = listing;
  }, [listing, qc]);
  //: 下好了 / 排着的识别完了:模型库重新列一遍
  const previous = React.useRef(status.data);
  React.useEffect(() => {
    const before = previous.current;
    previous.current = status.data;
    if (!before || !status.data || handled === status.dataUpdatedAt) return;
    const installed = before.status === "installing" && status.data.status === "installed";
    const drained = before.pending > 0 && status.data.pending === 0;
    if (installed || drained) {
      handled = status.dataUpdatedAt;
      void qc.invalidateQueries({ queryKey: ["model-library"] });
    }
  }, [status.data, status.dataUpdatedAt, qc]);
  return status;
}

/** 「预览图」设置面板里的那一行:没下就写多大、点了才下(只给部署管理员);下好了说识别到哪儿了。 */
export function LocalNsfwRow() {
  const t = useI18n();
  const qc = useQueryClient();
  const admin = useIsDeploymentAdmin();
  const status = useLocalNsfw();
  const install = useMutation({
    mutationFn: () => installLocalNsfw(),
    onSuccess: (next) => qc.setQueryData(LOCAL_NSFW_KEY, next),
  });
  const data = status.data;
  if (!data) return null;
  const size = formatBytes(data.size_bytes);
  const downloadable = data.status === "missing" || data.status === "failed";
  return (
    <section aria-label={t("modelLocalNsfw")} data-local-nsfw={data.status} className="grid gap-1.5 border-t border-border pt-3">
      <span className="flex items-center gap-1.5 text-ui-xs font-medium text-foreground">
        <ScanEye size={13} aria-hidden className="text-muted-foreground" />
        {t("modelLocalNsfw")}
        {data.status === "installed" && (
          <span className="font-normal text-muted-foreground">
            {data.pending > 0 ? t("modelLocalNsfwPending").replace("{n}", String(data.pending))
              : t("modelLocalNsfwReady").replace("{n}", String(data.scored))}
          </span>
        )}
      </span>
      <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("modelLocalNsfwHint").replace("{size}", size)}</p>
      {data.status === "failed" && (
        <p role="alert" className="m-0 text-ui-xs text-destructive">
          {t("modelLocalNsfwFailed").replace("{why}", data.message)}
        </p>
      )}
      {install.isError && <p role="alert" className="m-0 text-ui-xs text-destructive">{errorText(install.error)}</p>}
      {data.status === "installing" ? (
        <Button variant="outline" size="xs" className="justify-self-start" loading disabled>
          {t("modelLocalNsfwInstalling")}
        </Button>
      ) : downloadable && admin ? (
        <span className="flex flex-wrap items-center gap-1.5">
          <Button variant="outline" size="xs" loading={install.isPending} onClick={() => install.mutate()}>
            <Download size={12} />
            {data.status === "failed" ? t("modelLocalNsfwRetry") : t("modelLocalNsfwDownload").replace("{size}", size)}
          </Button>
          {/* 下不下来多半是网络:权重从「模型下载源」那一行拉(管理 → 引擎 → 下载源),此前失败只写原因,想不到能换源(体检 UM-16)。 */}
          {data.status === "failed" && (
            <Button variant="ghost" size="xs" onClick={() => gotoAdmin("engines")}>
              <Repeat size={12} />
              {t("modelLocalNsfwChangeSource")}
            </Button>
          )}
        </span>
      ) : downloadable ? (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("modelLocalNsfwAdminOnly")}</p>
      ) : null}
    </section>
  );
}
