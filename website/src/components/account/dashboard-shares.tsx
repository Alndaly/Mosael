"use client";

import Link from "next/link";
import { AlertCircle, Bookmark, Download, ExternalLink, Heart, MessageSquare, PackageOpen, Trash2, Upload } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages, type Messages } from "@/i18n/messages";
import { CloudApiError, cloudShares, type CloudShare } from "@/lib/cloud";

import { formatShareDate } from "@/components/community/share-utils";

import { NamePrompt } from "./dashboard-name-prompt";

/**
 * 我的分享:一条一行,带四项统计和两个操作。
 *
 * 删除是**先确认再发请求**:`DELETE /shares/{id}` 在云端是软删(作者以外一律 404),删错了
 * 没有后悔药。成功后就地移除(父组件持有的列表跟着变,概览的数字也一起变);失败把后端
 * 那句话原样放在行上方,不清空列表、不假装成功。
 */
function Stat({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Download }) {
  return (
    <span className="inline-flex items-center gap-1" title={label}>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="sr-only">{label}</span>
      <span className="font-mono tabular-nums">{value}</span>
    </span>
  );
}

export function DashboardShares({
  locale,
  copy,
  shares,
  hasHandle,
  loadError,
  onRemoved,
  onGoToProfile,
}: {
  locale: Locale;
  copy: Messages["dashboard"];
  shares: CloudShare[];
  hasHandle: boolean;
  loadError: string;
  onRemoved: (id: string) => void;
  onGoToProfile: () => void;
}) {
  const t = getMessages(locale).community;
  // 删除失败时的兜底：后端总有一句话；只有网络/未知错误才用它。
  const genericFailure = getMessages(locale).account.actionFailed;
  const [confirming, setConfirming] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  if (!hasHandle) {
    return <NamePrompt copy={copy} onGoToProfile={onGoToProfile} />;
  }

  const remove = async (share: CloudShare) => {
    setError("");
    setBusy(share.id);
    try {
      await cloudShares.remove(share.id);
      onRemoved(share.id);
      setConfirming("");
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : genericFailure);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="grid gap-4">
      {(error || loadError) && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">{error || loadError}</span>
        </div>
      )}

      {shares.length === 0 ? (
        <div className="rounded-3xl border border-dashed border-border bg-card px-6 py-16 text-center">
          <PackageOpen className="mx-auto size-6 text-muted-foreground" aria-hidden />
          <p className="mt-4 mb-0 font-semibold">{copy.noShares}</p>
          <p className="mt-1 mb-0 text-sm leading-6 text-muted-foreground">{copy.noSharesHint}</p>
          <Button asChild className="mt-5 min-h-10 rounded-full px-4 text-sm font-semibold">
            <Link href={localePath(locale, "/community/upload")}>
              <Upload className="size-4" aria-hidden />
              {copy.goUpload}
            </Link>
          </Button>
        </div>
      ) : (
        <ul className="m-0 grid list-none gap-3 p-0">
          {shares.map((share) => (
            <li key={share.id} className="min-w-0 rounded-2xl border border-border bg-card p-4 sm:p-5">
              <div className="flex min-w-0 flex-wrap items-start gap-x-4 gap-y-3">
                <div className="min-w-0 flex-1">
                  <h2 className="m-0 text-base font-semibold tracking-tight [overflow-wrap:anywhere]">{share.title}</h2>
                  <p className="mt-1 mb-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                    <span>{share.kind === "board" ? t.kindBoard : t.kindWorkflow}</span>
                    <span aria-hidden>·</span>
                    <time dateTime={share.created_at}>{formatShareDate(share.created_at, locale)}</time>
                  </p>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border pt-3 text-xs text-muted-foreground">
                    <Stat label={t.downloads} value={share.stats.downloads} icon={Download} />
                    <Stat label={t.likes} value={share.stats.likes} icon={Heart} />
                    <Stat label={t.favorites} value={share.stats.favorites} icon={Bookmark} />
                    <Stat label={t.comments} value={share.stats.comments} icon={MessageSquare} />
                  </div>
                </div>

                <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
                  <Button asChild variant="outline" className="min-h-9 rounded-full px-3.5 text-[13px] font-semibold">
                    <Link href={localePath(locale, `/community/${share.id}`)}>
                      <ExternalLink className="size-3.5" aria-hidden />
                      {copy.view}
                    </Link>
                  </Button>
                  {confirming === share.id ? (
                    <>
                      <Button
                        variant="destructive"
                        disabled={busy === share.id}
                        aria-busy={busy === share.id}
                        onClick={() => void remove(share)}
                        className="min-h-9 rounded-full px-3.5 text-[13px] font-semibold"
                      >
                        <Trash2 className="size-3.5" aria-hidden />
                        {busy === share.id ? copy.deleting : copy.confirmDelete}
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={busy === share.id}
                        onClick={() => setConfirming("")}
                        className="min-h-9 rounded-full px-3 text-[13px]"
                      >
                        {copy.cancel}
                      </Button>
                    </>
                  ) : (
                    <Button
                      variant="outline"
                      onClick={() => setConfirming(share.id)}
                      className="min-h-9 rounded-full px-3.5 text-[13px] font-semibold text-destructive"
                    >
                      <Trash2 className="size-3.5" aria-hidden />
                      {copy.delete}
                    </Button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
