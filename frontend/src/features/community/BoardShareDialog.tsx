import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, Globe, Link2, Lock, RefreshCw, Undo2 } from "lucide-react";
import { toast } from "sonner";

import {
  cancelJob,
  getBoardShare,
  getJob,
  shareBoard,
  updateBoardShare,
  withdrawBoardShare,
  type BoardShareVisibility,
} from "@/api/client";
import { usePreferences } from "@/app/preferences";
import { ConfirmDialog, DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { gotoSettings } from "@/lib/deepLink";
import { relativeTime } from "@/lib/time";
import { COMMUNITY_STATUS_KEY, fill, openInBrowser } from "@/features/community/communityShared";

const TERMINAL = new Set(["succeeded", "failed"]);

/**
 * 画板的「分享」面板(ADR 0026 §5):把这张画板做成一份快照传到社区,拿回一个只读链接。
 *
 * - 没分享过:标题 + 可见性(默认「知道链接的人」)+「生成链接」;
 * - 分享过:链接(复制、打开)、第几版,「更新分享」发一个新版本 —— **链接不变**;可见性改了当场存;「撤回」让链接立刻失效。
 *
 * 生成 / 更新是后台任务(快照 + 逐个上传文件),这里显示它的进度,也能取消;任务中心里同样看得到。
 */
export function BoardShareDialog({
  open,
  onOpenChange,
  boardId,
  boardName,
  workspaceId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  boardId: string;
  boardName: string;
  workspaceId: string;
}) {
  const { t, locale } = usePreferences();
  const qc = useQueryClient();
  const stateKey = ["board-share", boardId] as const;
  const state = useQuery({ queryKey: stateKey, queryFn: () => getBoardShare(boardId, workspaceId), enabled: open });
  const share = state.data?.share ?? null;
  const status = state.data?.status;
  const [title, setTitle] = React.useState("");
  const [visibility, setVisibility] = React.useState<BoardShareVisibility>("unlisted");
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [confirmWithdraw, setConfirmWithdraw] = React.useState(false);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: stateKey });
    void qc.invalidateQueries({ queryKey: COMMUNITY_STATUS_KEY });
  };

  //: 打开时(以及分享换了一版时)从记着的那条填表;没分享过就用画板名。
  React.useEffect(() => {
    if (!open || !state.data) return;
    setTitle(share?.title || boardName);
    setVisibility((share?.visibility as BoardShareVisibility | undefined) ?? "unlisted");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, state.data, share?.version]);

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query) => (query.state.data && TERMINAL.has(query.state.data.status) ? false : 1000),
  });
  const running = jobId !== null && !(job.data && TERMINAL.has(job.data.status));
  React.useEffect(() => {
    if (!job.data || !TERMINAL.has(job.data.status)) return;
    if (job.data.status === "succeeded") toast.success(t("boardShareDone"));
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.data?.status]);
  const failure = job.data?.status === "failed" ? job.data.error || job.data.message : "";

  const start = useMutation({
    mutationFn: () => shareBoard(boardId, { workspace_id: workspaceId, title: title.trim() || share?.title || boardName, visibility }),
    onSuccess: (created) => setJobId(created.id),
    onError: (error: Error) => {
      toast.error(error.message);
      refresh();
    },
  });
  const stop = useMutation({ mutationFn: () => cancelJob(jobId as string), onSettled: () => void job.refetch() });
  const changeVisibility = useMutation({
    mutationFn: (next: BoardShareVisibility) => updateBoardShare(boardId, { workspace_id: workspaceId, visibility: next }),
    onSuccess: refresh,
    onError: (error: Error, _next) => {
      toast.error(error.message);
      setVisibility((share?.visibility as BoardShareVisibility | undefined) ?? "unlisted");
    },
  });
  const withdraw = useMutation({
    mutationFn: () => withdrawBoardShare(boardId, workspaceId),
    onSuccess: () => {
      setConfirmWithdraw(false);
      setJobId(null);
      toast.success(t("boardShareWithdrawn"));
      refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const pickVisibility = (next: BoardShareVisibility) => {
    setVisibility(next);
    //: 分享过的:可见性是链接的属性,当场存,不必再传一遍快照。
    if (share && next !== share.visibility) changeVisibility.mutate(next);
  };
  const copy = () => {
    if (!share) return;
    void navigator.clipboard?.writeText(share.url);
    toast.success(t("boardShareCopied"));
  };

  const connected = status?.connected === true;
  const footer = connected ? (
    share ? (
      <>
        <Button variant="ghost" className="mr-auto text-muted-foreground hover:text-destructive" disabled={running} onClick={() => setConfirmWithdraw(true)}>
          <Undo2 /> {t("boardShareWithdraw")}
        </Button>
        <Button loading={start.isPending || running} onClick={() => start.mutate()}>
          <RefreshCw /> {t("boardShareUpdate")}
        </Button>
      </>
    ) : (
      <Button loading={start.isPending || running} disabled={!state.data} onClick={() => start.mutate()}>
        <Link2 /> {t("boardShareCreate")}
      </Button>
    )
  ) : undefined;

  return (
    <ModalShell open={open} onOpenChange={onOpenChange} title={t("boardShareTitle")} className="w-[480px]" footer={footer}>
      <div className="grid gap-5" data-testid="board-share-panel">
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{t("boardShareIntro")}</p>
        {state.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : !status?.configured ? (
          <p className="m-0 text-ui-sm text-muted-foreground">{t("communityNotConfiguredBody")}</p>
        ) : !connected ? (
          <div className="grid gap-3">
            <p className="m-0 text-ui-sm text-muted-foreground">{t("boardShareNeedsAccount")}</p>
            <Button
              variant="outline"
              className="w-fit"
              onClick={() => {
                onOpenChange(false);
                gotoSettings("community");
              }}
            >
              <Globe /> {t("communityGoConnect")}
            </Button>
          </div>
        ) : (
          <>
            {share && (
              <div className="grid gap-2">
                <span className="text-ui-sm font-medium text-foreground">{t("boardShareLink")}</span>
                <span className="flex min-w-0 items-center gap-2">
                  <Input size="sm" readOnly value={share.url} aria-label={t("boardShareLink")} className="min-w-0 flex-1" onFocus={(event) => event.currentTarget.select()} />
                  <Button variant="outline" size="icon-sm" title={t("boardShareCopy")} aria-label={t("boardShareCopy")} onClick={copy}>
                    <Copy />
                  </Button>
                  <Button variant="outline" size="icon-sm" title={t("boardShareOpen")} aria-label={t("boardShareOpen")} onClick={() => openInBrowser(share.url)}>
                    <ExternalLink />
                  </Button>
                </span>
                <small className="text-ui-xs text-muted-foreground">
                  {fill(t("boardShareVersion"), { version: share.version, when: relativeTime(share.updated_at, locale) })}
                </small>
              </div>
            )}
            <label className={DIALOG_FIELD}>
              <span>{t("boardShareTitleField")}</span>
              <Input value={title} maxLength={180} placeholder={boardName} onChange={(event) => setTitle(event.currentTarget.value)} />
              {share && <small>{t("boardShareTitleHint")}</small>}
            </label>
            <div className="grid gap-2">
              <span className="text-ui-sm font-medium text-foreground">{t("boardShareVisibility")}</span>
              <div role="radiogroup" aria-label={t("boardShareVisibility")} className={SEGMENTED_LIST}>
                {(["unlisted", "public"] as const).map((one) => (
                  <button
                    key={one}
                    type="button"
                    role="radio"
                    aria-checked={visibility === one}
                    disabled={changeVisibility.isPending}
                    className={segmentedTriggerClass(visibility === one)}
                    onClick={() => pickVisibility(one)}
                  >
                    {one === "unlisted" ? <Lock size={13} /> : <Globe size={13} />}
                    {one === "unlisted" ? t("boardShareUnlisted") : t("boardSharePublic")}
                  </button>
                ))}
              </div>
              <small className="text-ui-xs text-muted-foreground">
                {visibility === "unlisted" ? t("boardShareUnlistedHint") : t("boardSharePublicHint")}
              </small>
            </div>
            {running && (
              <div className="grid gap-2" data-testid="board-share-progress">
                <span className="flex items-center justify-between gap-2 text-ui-xs text-muted-foreground">
                  <span>{job.data?.message || t("boardShareUploading")}</span>
                  <Button variant="ghost" size="sm" loading={stop.isPending} onClick={() => stop.mutate()}>
                    {t("cancel")}
                  </Button>
                </span>
                <Progress value={Math.round((job.data?.progress ?? 0) * 100)} />
              </div>
            )}
            {failure && <p className="m-0 text-ui-xs text-destructive">{failure}</p>}
          </>
        )}
      </div>
      <ConfirmDialog
        open={confirmWithdraw}
        title={t("boardShareWithdrawTitle")}
        body={t("boardShareWithdrawBody")}
        confirmLabel={t("boardShareWithdraw")}
        pending={withdraw.isPending}
        onCancel={() => setConfirmWithdraw(false)}
        onConfirm={() => withdraw.mutate()}
      />
    </ModalShell>
  );
}
