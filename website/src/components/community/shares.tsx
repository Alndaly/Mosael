"use client";

/**
 * 一张用户分享卡片。
 *
 * 这里**只剩卡片**:早先的 `ShareBrowser`(搜索 / 类型 / 排序 / 游标翻页 + 空态)只被
 * `/community` 用过;社区首页改成两组落地页后,搜索和筛选留在 `/plugins`、`/workflows`,
 * 那套浏览 UI 没有第二个使用者,已经删掉(见 `browse.tsx` 里的 PluginBrowser /
 * WorkflowBrowser —— 它们用这份卡片,不用旧的列表组件)。
 */
import Link from "next/link";
import { BadgeCheck, Bookmark, Download, Heart, MessageSquare } from "lucide-react";

import { InitialTile } from "@/components/community/tile";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { toPlainText } from "@/lib/inline-markdown";
import { shareKindLabel } from "@/lib/shareKind";
import type { CloudShare, CloudShareKind } from "@/lib/cloud";
import { cn } from "@/lib/utils";

const CARD =
  "group flex min-w-0 flex-col rounded-2xl border border-border bg-card p-5 transition-[border-color,transform,box-shadow] hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-[0_10px_30px_-18px_color-mix(in_oklab,var(--primary)_60%,transparent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transition-none motion-reduce:hover:translate-y-0";

function Stat({ icon: Icon, label, value }: { icon: typeof Download; label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="sr-only">{label}</span>
      <span className="font-mono tabular-nums">{value}</span>
    </span>
  );
}

/**
 * 一张分享卡:作者(首字母色块头像 + 昵称)、标题、摘要、类型、四项统计。
 *
 * 作者名只用 `display_name` —— 后端公开响应里也只有 `display_name` / `handle` /
 * `avatar_seed` 三列,公开页面连邮箱的边都碰不到。
 */
export function ShareCard({ locale, share }: { locale: Locale; share: CloudShare }) {
  const t = getMessages(locale).community;
  const name = share.author.display_name?.trim() || share.author.handle || "—";
  const summary = share.summary?.trim() ? toPlainText(share.summary) : "";
  // 官方插件分享也要说清是「插件」,不能因为原先把 board 以外的都当工作流而标错。

  return (
    <Link href={localePath(locale, `/community/${share.id}`)} className={CARD}>
      <div className="flex min-w-0 items-center gap-3.5">
        <InitialTile seed={share.author.avatar_seed || share.author.handle || share.id} name={name} size="md" />
        <div className="grid min-w-0 gap-0.5">
          <h3 className="m-0 line-clamp-2 text-base font-semibold tracking-tight group-hover:text-primary">{share.title}</h3>
          <span className="inline-flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
            <span className="truncate">{name}</span>
            {share.author.official && (
              <span className="inline-flex shrink-0 items-center gap-0.5 font-medium text-primary">
                <BadgeCheck className="size-3.5" aria-hidden />
                {t.official}
              </span>
            )}
            <span aria-hidden> · </span>
            <span className="shrink-0">{shareKindLabel(share.kind, t)}</span>
          </span>
        </div>
      </div>
      <p
        className={cn(
          "mt-4 mb-0 line-clamp-3 flex-1 text-sm leading-6",
          summary ? "text-muted-foreground" : "text-muted-foreground/70",
        )}
      >
        {summary || t.noSummary}
      </p>
      <div className="mt-5 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border pt-4 text-xs text-muted-foreground">
        <Stat icon={Download} label={t.downloads} value={share.stats.downloads} />
        <Stat icon={Heart} label={t.likes} value={share.stats.likes} />
        <Stat icon={Bookmark} label={t.favorites} value={share.stats.favorites} />
        <Stat icon={MessageSquare} label={t.comments} value={share.stats.comments} />
      </div>
    </Link>
  );
}
