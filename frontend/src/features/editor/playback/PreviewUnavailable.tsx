import React from "react";
import { Loader2, RefreshCw, TriangleAlert } from "lucide-react";

import { api, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import type { AssetPreviewState } from "@/features/editor/playback/previewReadiness";

/**
 * 画面画不出来时铺在监视器上的说明层。
 *
 * 预览只走 WebCodecs + 代理一条路(没有 `<video>` 元素兜底),所以「暂时画不出来」必须**说清楚**:
 * 一块空白黑屏会被当成 bug 反复报,而这几种情况里有两种是用户点一下就能自救的。
 *
 * 只在**当前播放头下真正要画的**素材有问题时出现——按整条序列判定的话,末尾一个还在转码的片段
 * 会把开头已经能放的部分一起挡住。
 */
export function PreviewUnavailable({
  state,
  assets,
  onRetried,
}: {
  state: Exclude<AssetPreviewState, "ready"> | "unsupported";
  /** 处于该状态的素材;`unsupported` 时为空(问题不在素材上)。 */
  assets: Asset[];
  /** 重新生成代理已提交:调用方据此立刻刷新素材,别等下一轮轮询。 */
  onRetried?: () => void;
}) {
  const t = useI18n();
  const [retrying, setRetrying] = React.useState(false);
  const [retryError, setRetryError] = React.useState(false);

  // 只有「代理有问题」的两种状态能靠重新生成自救;转码中只需要等,不支持则与素材无关。
  const canRetry = state === "failed" || state === "undecodable";

  const retry = async () => {
    setRetrying(true);
    setRetryError(false);
    try {
      await Promise.all(assets.map((asset) => api(`/api/assets/${asset.id}/proxy`, { method: "POST" })));
      onRetried?.();
    } catch {
      setRetryError(true);
    } finally {
      setRetrying(false);
    }
  };

  const copy = {
    transcoding: { title: t("previewTranscoding"), hint: t("previewTranscodingHint") },
    failed: { title: t("previewFailed"), hint: t("previewFailedHint") },
    undecodable: { title: t("previewUndecodable"), hint: t("previewUndecodableHint") },
    unsupported: { title: t("previewUnsupported"), hint: t("previewUnsupportedHint") },
  }[state];

  return (
    <div className="absolute inset-0 z-[3] grid place-items-center bg-black/85 px-6">
      <div className="grid max-w-[380px] justify-items-center gap-2 text-center">
        {state === "transcoding" ? (
          <Loader2 className="animate-spin text-[rgb(255_255_255/0.55)]" size={20} />
        ) : (
          <TriangleAlert className="text-[rgb(255_255_255/0.55)]" size={20} />
        )}
        <span className="text-ui-md font-medium text-[rgb(255_255_255/0.9)]">{copy.title}</span>
        <span className="text-ui-sm leading-relaxed text-[rgb(255_255_255/0.5)]">{copy.hint}</span>
        {/* 点名是哪个素材:一条时间线上几十个片段,不说名字用户无从下手。 */}
        {assets.length > 0 && (
          <span className="max-w-full truncate text-ui-xs text-[rgb(255_255_255/0.38)]" title={assets.map((a) => a.name).join("、")}>
            {assets.map((asset) => asset.name).join("、")}
          </span>
        )}
        {canRetry && (
          <Button className="mt-1" size="sm" variant="secondary" disabled={retrying} onClick={() => void retry()}>
            <RefreshCw className={retrying ? "animate-spin" : undefined} size={13} />
            {retrying ? t("previewRetrying") : t("previewRetryProxy")}
          </Button>
        )}
        {retryError && <span className="text-ui-xs text-destructive">{t("previewRetryFailed")}</span>}
      </div>
    </div>
  );
}
