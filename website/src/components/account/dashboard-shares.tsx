"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Bookmark, Download, ExternalLink, Heart, MessageSquare, PackageOpen, Trash2, Upload } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages, type Messages } from "@/i18n/messages";
import { CloudApiError, cloudShares, type CloudShare } from "@/lib/cloud";
import { shareKindLabel } from "@/lib/shareKind";
import { invalidateAfterShareChange } from "@/lib/query-invalidation";

import { formatShareDate } from "@/components/community/share-utils";

import { NamePrompt } from "./dashboard-name-prompt";

/**
 * 我的分享:管理台里的一张表 —— 分享、数据、发布时间、操作各一列。
 *
 * 删除仍是**先确认再发请求**:`DELETE /shares/{id}` 在云端是软删(作者以外一律 404),
 * 删错了没有后悔药。成功后就地移除(父组件持有的列表跟着变,概览的数字也一起变);失败
 * 把后端那句话原样放在表上方,不清空列表、不假装成功。
 *
 * 视觉沿用管理台的用户表:白底 `Card` + 36px 操作 + 分隔线，不再是一叠圆角卡片。
 */
function Stat({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Download }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" title={label}>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="sr-only">{label}</span>
      <span className="font-mono tabular-nums text-foreground">{value}</span>
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
  const queryClient = useQueryClient();
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
      // 就地移除 + 让缓存失效:我的分享、概览统计(两者同一份 sharesByMe)、
      // 以及该 kind 的公开列表里那张卡片。只改本地 state 的话,切个分区回来它又出现了。
      onRemoved(share.id);
      void invalidateAfterShareChange(queryClient, share.kind);
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
          className="flex flex-wrap items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">{error || loadError}</span>
        </div>
      )}

      <Card className="bg-card/60 ring-border">
        <CardContent className="grid gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="m-0 text-sm text-muted-foreground">
              <span className="font-mono text-foreground tabular-nums">{shares.length}</span> {copy.sharesCount}
            </p>
            <Button asChild size="sm">
              <Link href={localePath(locale, "/community/upload")}>
                <Upload className="size-3.5" aria-hidden />
                {copy.goUpload}
              </Link>
            </Button>
          </div>

          {shares.length === 0 ? (
            <div className="grid place-items-center rounded-xl border border-dashed border-border px-6 py-16 text-center">
              <PackageOpen className="size-6 text-muted-foreground" aria-hidden />
              <p className="mt-4 mb-0 font-semibold">{copy.noShares}</p>
              <p className="mt-1 mb-0 max-w-sm text-sm leading-6 text-muted-foreground">{copy.noSharesHint}</p>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{copy.columnShare}</TableHead>
                    <TableHead>{copy.columnStats}</TableHead>
                    <TableHead>{copy.columnPublished}</TableHead>
                    <TableHead className="text-right">{copy.columnActions}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {shares.map((share) => (
                    <TableRow key={share.id}>
                      <TableCell className="max-w-[22rem] min-w-[14rem]">
                        <div className="grid gap-1">
                          <span className="truncate font-medium [overflow-wrap:anywhere]">{share.title}</span>
                          <Badge variant="outline" className="w-fit">{shareKindLabel(share.kind, t)}</Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                          <Stat label={t.downloads} value={share.stats.downloads} icon={Download} />
                          <Stat label={t.likes} value={share.stats.likes} icon={Heart} />
                          <Stat label={t.favorites} value={share.stats.favorites} icon={Bookmark} />
                          <Stat label={t.comments} value={share.stats.comments} icon={MessageSquare} />
                        </div>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                        <time dateTime={share.created_at}>{formatShareDate(share.created_at, locale)}</time>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-1.5">
                          <Button asChild variant="ghost" size="sm">
                            <Link href={localePath(locale, `/community/${share.id}`)}>
                              <ExternalLink className="size-3.5" aria-hidden />
                              {copy.view}
                            </Link>
                          </Button>
                          {confirming === share.id ? (
                            <>
                              <Button
                                variant="destructive"
                                size="sm"
                                disabled={busy === share.id}
                                aria-busy={busy === share.id}
                                onClick={() => void remove(share)}
                              >
                                <Trash2 className="size-3.5" aria-hidden />
                                {busy === share.id ? copy.deleting : copy.confirmDelete}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={busy === share.id}
                                onClick={() => setConfirming("")}
                              >
                                {copy.cancel}
                              </Button>
                            </>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setConfirming(share.id)}
                              className="text-destructive hover:text-destructive"
                            >
                              <Trash2 className="size-3.5" aria-hidden />
                              {copy.delete}
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
