import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RotateCcw, X } from "lucide-react";

import { importAsset, type Asset } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { assetKeys } from "@/api/queryKeys";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * 在挑素材的地方**直接传一个本地文件**:挑素材的弹窗(按钮、拖进弹窗)、生成面板上的「+」槽(拖上去、面板里 ⌘V)。
 *
 * 此前「+」只能从素材库里选 —— 本机刚截的图、刚导出的一段视频,得先去素材页导入、再回来挑(用户原话「这个交互非常
 * 不方便」)。传走的是素材库同一个导入接口(importAsset,和拖进画板、素材页的导入一样),传完素材库跟着刷新;这里多的
 * 只是一格进度、停得下来、没传上说为什么并能再来一次 —— 一次只传一个(一个槽挂一份)。
 */

export type UploadKind = "image" | "video" | "audio";

/** 拖进来的文件有时没有 MIME(从终端、某些编辑器拖出来):按扩展名再认一次。 */
const EXTENSIONS: Record<UploadKind, RegExp> = {
  image: /\.(png|jpe?g|webp|gif|bmp|tiff?|heic|avif)$/i,
  video: /\.(mp4|mov|m4v|webm|mkv|avi)$/i,
  audio: /\.(mp3|wav|m4a|aac|flac|ogg|opus)$/i,
};

/** 这个文件是哪一种媒体;都不是回 null。 */
export function fileKind(file: File): UploadKind | null {
  const major = file.type.split("/")[0];
  if (major === "image" || major === "video" || major === "audio") return major;
  return (Object.keys(EXTENSIONS) as UploadKind[]).find((kind) => EXTENSIONS[kind].test(file.name)) ?? null;
}

/** 文件选择框的 `accept`。 */
export function acceptFor(kind: UploadKind | "media"): string {
  return kind === "media" ? "image/*,video/*,audio/*" : `${kind}/*`;
}

/** 「这里只收图片」那句:`kind` 是这一格要的那一种(三种都收的是 `media`)。 */
export function wrongKindText(t: (key: MessageKey) => string, file: File, kind: UploadKind | "media"): string {
  const noun = t(`assetUploadKind_${kind}` as MessageKey);
  return t("assetUploadWrongKind").replace("{name}", file.name || "?").replaceAll("{kind}", noun);
}

/** 截图粘进来的文件没有名字:给它一个,否则素材库里多一个无名素材(和对话框粘贴附件同一条)。 */
export function namedFile(file: File): File {
  return file.name ? file : new File([file], `pasted-${Date.now()}.${file.type.split("/")[1] || "png"}`, { type: file.type });
}

export type AssetUploadState =
  | { status: "idle" }
  | { status: "uploading"; name: string; progress: number }
  | { status: "failed"; name: string; reason: string }
  | { status: "rejected"; message: string };

export interface AssetUpload {
  state: AssetUploadState;
  /** 传这一个,传完交给 `done`(把它挂进槽里、交回弹窗)。在传的那一个先停掉。 */
  start: (file: File, done: (asset: Asset) => void) => void;
  /** 收不了(种类不对):就地说一句,不传。 */
  reject: (message: string) => void;
  retry: () => void;
  cancel: () => void;
  dismiss: () => void;
}

export function useAssetUpload(workspaceId: string): AssetUpload {
  const queryClient = useQueryClient();
  const [state, setState] = React.useState<AssetUploadState>({ status: "idle" });
  //: 这一次传的是哪个文件、传完交给谁、怎么停 —— 没传上时留着,「重试」照它再来一次。
  const current = React.useRef<{ file: File; done: (asset: Asset) => void; controller: AbortController } | null>(null);

  const start = React.useCallback(
    (file: File, done: (asset: Asset) => void) => {
      current.current?.controller.abort();
      const controller = new AbortController();
      current.current = { file, done, controller };
      const mine = () => current.current?.controller === controller;
      setState({ status: "uploading", name: file.name, progress: 0 });
      importAsset({
        workspaceId,
        file,
        signal: controller.signal,
        onProgress: (progress) => {
          if (mine()) setState({ status: "uploading", name: file.name, progress });
        },
      }).then(
        (asset) => {
          if (!mine()) return;
          current.current = null;
          setState({ status: "idle" });
          void queryClient.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
          done(asset);
        },
        (error: unknown) => {
          //: 自己停下的(取消、换了一个文件、面板关了)不是失败。
          if (controller.signal.aborted || !mine()) return;
          setState({ status: "failed", name: file.name, reason: errorText(error) });
        },
      );
    },
    [workspaceId, queryClient],
  );
  const retry = React.useCallback(() => {
    const last = current.current;
    if (last) start(last.file, last.done);
  }, [start]);
  const cancel = React.useCallback(() => {
    current.current?.controller.abort();
    current.current = null;
    setState({ status: "idle" });
  }, []);
  const reject = React.useCallback((message: string) => {
    current.current?.controller.abort();
    current.current = null;
    setState({ status: "rejected", message });
  }, []);
  //: 弹窗关了、面板收起了:还在传的停掉 —— 传完也没有地方可挂了。
  React.useEffect(() => () => current.current?.controller.abort(), []);
  return { state, start, reject, retry, cancel, dismiss: cancel };
}

/** 传的那一行:在传(名字、进度、取消)、没传上(原因、重试)、收不了(为什么)。闲着什么都不画。 */
export function AssetUploadStatus({ upload, className }: { upload: AssetUpload; className?: string }) {
  const t = useI18n();
  const { state } = upload;
  if (state.status === "idle") return null;
  const percent = state.status === "uploading" ? Math.round(state.progress * 100) : 0;
  return (
    <div
      role={state.status === "uploading" ? "status" : "alert"}
      data-asset-upload={state.status}
      className={cn(
        "flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-ui-xs",
        state.status === "uploading" ? "bg-secondary text-foreground" : "bg-destructive/10 text-destructive",
        className,
      )}
    >
      <span className="min-w-0 flex-1 truncate">
        {state.status === "uploading"
          ? t("assetUploading").replace("{name}", state.name)
          : state.status === "failed"
            ? t("assetUploadFailed").replace("{name}", state.name).replace("{reason}", state.reason)
            : state.message}
      </span>
      {state.status === "uploading" && (
        <>
          <span
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-label={t("assetUploading").replace("{name}", state.name)}
            className="h-1 w-16 shrink-0 overflow-hidden rounded-full bg-border"
          >
            <span className="block h-full bg-primary transition-[width]" style={{ width: `${percent}%` }} />
          </span>
          <span className="w-8 shrink-0 text-right tabular-nums text-muted-foreground">{percent}%</span>
        </>
      )}
      {state.status === "failed" && (
        <Button type="button" size="xs" variant="ghost" className="shrink-0 gap-1" onClick={upload.retry}>
          <RotateCcw size={12} />
          {t("retry")}
        </Button>
      )}
      <Button
        type="button"
        size="icon-xs"
        variant="ghost"
        aria-label={state.status === "uploading" ? t("assetUploadCancel") : t("close")}
        title={state.status === "uploading" ? t("assetUploadCancel") : t("close")}
        onClick={upload.cancel}
        className="shrink-0 text-muted-foreground"
      >
        <X size={12} />
      </Button>
    </div>
  );
}
