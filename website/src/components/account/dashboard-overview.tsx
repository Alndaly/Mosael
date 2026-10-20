import Link from "next/link";
import { AlertCircle, ArrowRight, Bookmark, Download, Heart, MessageSquare, PackageOpen, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages, type Messages } from "@/i18n/messages";
import type { CloudShare, CloudShareStats } from "@/lib/cloud";

import { formatShareDate } from "@/components/community/share-utils";

import { NamePrompt } from "./dashboard-name-prompt";
import type { DashboardTab } from "./dashboard-utils";

/**
 * 概览:五个数字 + 最近 3 条分享。
 *
 * 数字只有一个来源 —— 服务端已经取回的那批分享(见 `loadUserShares`),这里对每条 `stats`
 * 求和。没有分享时五个数字就是 0(那是真的),再给一条去上传的路;**没有 handle 时不画统计**,
 * 换成「先起个名字」—— 否则一屏 0 看起来像坏了。
 */
function StatCard({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Download }) {
  return (
    <div className="rounded-2xl border border-border bg-card p-4">
      <p className="m-0 flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
        <Icon className="size-3.5 shrink-0" aria-hidden />
        {label}
      </p>
      <p className="mt-2 mb-0 font-display text-2xl font-semibold tabular-nums tracking-[-0.03em]">{value}</p>
    </div>
  );
}

export function DashboardOverview({
  locale,
  copy,
  shares,
  totals,
  hasHandle,
  loadError,
  onGoToProfile,
  onSelect,
}: {
  locale: Locale;
  copy: Messages["dashboard"];
  shares: CloudShare[];
  totals: CloudShareStats;
  hasHandle: boolean;
  loadError: string;
  onGoToProfile: () => void;
  onSelect: (tab: DashboardTab) => void;
}) {
  const t = getMessages(locale).community;

  if (!hasHandle) {
    return <NamePrompt copy={copy} onGoToProfile={onGoToProfile} />;
  }

  const recent = shares.slice(0, 3);

  return (
    <div className="grid gap-6">
      {loadError && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">{loadError}</span>
        </div>
      )}

      <section aria-label={copy.tabOverview}>
        <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-3 lg:grid-cols-5">
          <li>
            <StatCard label={copy.sharesCount} value={shares.length} icon={PackageOpen} />
          </li>
          <li>
            <StatCard label={copy.totalDownloads} value={totals.downloads} icon={Download} />
          </li>
          <li>
            <StatCard label={copy.totalLikes} value={totals.likes} icon={Heart} />
          </li>
          <li>
            <StatCard label={copy.totalFavorites} value={totals.favorites} icon={Bookmark} />
          </li>
          <li>
            <StatCard label={copy.totalComments} value={totals.comments} icon={MessageSquare} />
          </li>
        </ul>
      </section>

      <section aria-labelledby="dashboard-recent" className="rounded-3xl border border-border bg-card p-5 sm:p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <div className="min-w-0">
            <h2 id="dashboard-recent" className="m-0 font-display text-xl font-semibold tracking-[-0.03em]">
              {copy.recentShares}
            </h2>
            <p className="mt-1 mb-0 text-[13px] leading-6 text-muted-foreground">{copy.recentSharesHint}</p>
          </div>
          {shares.length > 0 && (
            <Button
              variant="ghost"
              onClick={() => onSelect("shares")}
              className="min-h-9 rounded-full px-3.5 text-[13px] font-semibold"
            >
              {copy.viewAll}
              <ArrowRight className="size-3.5" aria-hidden />
            </Button>
          )}
        </div>

        {recent.length === 0 ? (
          <div className="mt-5 rounded-2xl border border-dashed border-border bg-paper/60 px-5 py-10 text-center">
            <PackageOpen className="mx-auto size-5 text-muted-foreground" aria-hidden />
            <p className="mt-3 mb-0 text-sm font-medium">{copy.noShares}</p>
            <p className="mt-1 mb-0 text-sm text-muted-foreground">{copy.noSharesHint}</p>
            <Button asChild className="mt-4 min-h-10 rounded-full px-4 text-sm font-semibold">
              <Link href={localePath(locale, "/community/upload")}>
                <Upload className="size-4" aria-hidden />
                {copy.goUpload}
              </Link>
            </Button>
          </div>
        ) : (
          <ul className="m-0 mt-5 grid list-none gap-2.5 p-0">
            {recent.map((share) => (
              <li key={share.id} className="min-w-0">
                <Link
                  href={localePath(locale, `/community/${share.id}`)}
                  className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 rounded-2xl border border-border bg-paper/50 px-4 py-3 transition-colors hover:border-primary/40 hover:bg-paper focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  <span className="min-w-0 flex-1 text-sm font-semibold [overflow-wrap:anywhere]">{share.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {share.kind === "board" ? t.kindBoard : t.kindWorkflow}
                    <span aria-hidden> · </span>
                    {formatShareDate(share.created_at, locale)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
