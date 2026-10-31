import Link from "next/link";
import { AlertCircle, ArrowRight, ArrowUpRight, Bookmark, Download, Heart, MessageSquare, PackageOpen, Upload } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages, type Messages } from "@/i18n/messages";
import type { CloudShare, CloudShareStats } from "@/lib/cloud";
import { shareKindLabel } from "@/lib/shareKind";

import { formatShareDate } from "@/components/community/share-utils";

import { NamePrompt } from "./dashboard-name-prompt";
import type { DashboardTab } from "./dashboard-utils";

/**
 * 概览:五个数字 + 最近 3 条分享。
 *
 * 数字只有一个来源 —— 服务端已经取回的那批分享(见 `loadUserShares`),这里对每条 `stats`
 * 求和。没有分享时五个数字就是 0(那是真的),再给一条去上传的路;**没有 handle 时不画统计**,
 * 换成「先起个名字」—— 否则一屏 0 看起来像坏了。
 *
 * 视觉沿用管理台的标准密度:`Card` + `ring-border` + 36px 操作，不再使用营销页的胶囊按钮
 * 和超大圆角。最近分享用分隔线列表，而不是一叠再叠的小卡片。
 */
function StatCard({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Download }) {
  return (
    <Card size="sm" className="gap-0 bg-card/60 py-4 ring-border">
      <CardContent className="grid gap-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
          <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground">
            <Icon className="size-3.5" aria-hidden />
          </span>
        </div>
        <p className="m-0 text-2xl font-semibold tabular-nums tracking-[-0.02em]">{value}</p>
      </CardContent>
    </Card>
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
    <div className="grid gap-4">
      {loadError && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">{loadError}</span>
        </div>
      )}

      <section aria-label={copy.tabOverview} className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatCard label={copy.sharesCount} value={shares.length} icon={PackageOpen} />
        <StatCard label={copy.totalDownloads} value={totals.downloads} icon={Download} />
        <StatCard label={copy.totalLikes} value={totals.likes} icon={Heart} />
        <StatCard label={copy.totalFavorites} value={totals.favorites} icon={Bookmark} />
        <StatCard label={copy.totalComments} value={totals.comments} icon={MessageSquare} />
      </section>

      <Card className="bg-card/60 ring-border">
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle id="dashboard-recent">{copy.recentShares}</CardTitle>
            <p className="mt-1 mb-0 text-sm text-muted-foreground">{copy.recentSharesHint}</p>
          </div>
          {shares.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => onSelect("shares")}>
              {copy.viewAll}
              <ArrowRight className="size-3.5" aria-hidden />
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {recent.length === 0 ? (
            <div className="grid place-items-center rounded-xl border border-dashed border-border px-6 py-12 text-center">
              <PackageOpen className="size-6 text-muted-foreground" aria-hidden />
              <p className="mt-3 mb-0 text-sm font-medium">{copy.noShares}</p>
              <p className="mt-1 mb-0 text-sm text-muted-foreground">{copy.noSharesHint}</p>
              <Button asChild size="sm" className="mt-4">
                <Link href={localePath(locale, "/community/upload")}>
                  <Upload className="size-3.5" aria-hidden />
                  {copy.goUpload}
                </Link>
              </Button>
            </div>
          ) : (
            <ul className="m-0 grid list-none divide-y divide-border p-0">
              {recent.map((share) => (
                <li key={share.id} className="min-w-0">
                  <Link
                    href={localePath(locale, `/community/${share.id}`)}
                    className="group flex min-w-0 items-center gap-3 py-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                  >
                    <div className="grid min-w-0 flex-1 gap-1">
                      <span className="truncate text-sm font-medium [overflow-wrap:anywhere]">{share.title}</span>
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                        <Badge variant="outline">{shareKindLabel(share.kind, t)}</Badge>
                        <time dateTime={share.created_at}>{formatShareDate(share.created_at, locale)}</time>
                      </span>
                    </div>
                    <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
