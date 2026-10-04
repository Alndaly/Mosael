import React from "react";
import { useQueryClient } from "@tanstack/react-query";

import { assetKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { restartForStaleMain, staleMainRestartable } from "@/features/desktop/mainStale";
import { gotoRecord } from "@/lib/deepLink";

import { listenDownloadNotices } from "./downloadActions";
import { pageToolErrorCode } from "./pageActions";

/** 顶栏状态条上的一句话:做到哪了 / 做好了(可点过去)/ 没做成。 */
export interface Notice {
  tone: "busy" | "done" | "error";
  text: string;
  action?: { label: string; run: () => void };
}

const NOTICE_MS = 6_000;

/** 去素材库看:收起内嵌浏览器,跳过去并打开那一份(一次存了好几份时只到素材库)。 */
export function showSavedAsset(assetId: string | null): void {
  void window.mosaelPublish?.hideView();
  gotoRecord("/media", assetId ? "mosael:open-asset" : undefined, assetId ?? undefined);
}

/**
 * 页面工具的「toast」。**说在顶栏里**,不交给应用的 Toaster:内嵌浏览器亮着时网页盖住了窗口的其余部分,
 * 右下角弹出来的提示正好在网页底下,谁也看不见。做好了的那句可以点过去(去素材库看那一份、打开那篇笔记)。
 */
export function useToolNotice() {
  const t = useI18n();
  const qc = useQueryClient();
  const [notice, setNotice] = React.useState<Notice | null>(null);
  const timer = React.useRef<number | undefined>(undefined);

  const say = React.useCallback((next: Notice | null) => {
    window.clearTimeout(timer.current);
    setNotice(next);
    if (next && next.tone !== "busy") timer.current = window.setTimeout(() => setNotice(null), NOTICE_MS);
  }, []);
  React.useEffect(() => () => window.clearTimeout(timer.current), []);
  // 网页里点的下载(存进素材库由应用最外层的 BrowserDownloads 做):顶栏挂着时由这里说。
  React.useEffect(() => listenDownloadNotices(say), [say]);

  /** 没做成:主进程的原因码翻成人话,别的错误照原文说。 */
  const failed = React.useCallback(
    (error: unknown) => {
      const code = pageToolErrorCode(error);
      const reason =
        code === "no_page"
          ? t("browserToolsNoPage")
          : code === "capture_failed"
            ? t("browserToolsCaptureFailed")
            : code === "full_page_unavailable"
              ? t("browserToolsFullPageUnavailable")
              : (error as Error)?.message || String(error);
      // 开发时主进程是旧的(渲染层热更新成了新代码,调的处理器主进程里没有)且能替用户重启:直接给「重启」。
      const restart = staleMainRestartable() ? { label: t("mainStaleRestart"), run: () => void restartForStaleMain() } : undefined;
      say({ tone: "error", text: t("browserToolsFailed").replace("{reason}", reason), action: restart });
    },
    [say, t],
  );

  /** 「已存进素材库」,带一个「查看」。 */
  const savedAsset = React.useCallback(
    (assetId: string | null, text: string = t("browserToolsSavedAsset")) => {
      void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
      say({ tone: "done", text, action: { label: t("browserToolsView"), run: () => showSavedAsset(assetId) } });
    },
    [qc, say, t],
  );

  return { notice, say, failed, savedAsset };
}

export type ToolNotice = ReturnType<typeof useToolNotice>;
