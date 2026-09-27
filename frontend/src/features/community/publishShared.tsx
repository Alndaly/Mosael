import { Check, Copy, ExternalLink, Hourglass } from "lucide-react";
import { toast } from "sonner";

import type { CommunityPublishResult } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { openInBrowser } from "@/features/community/communityShared";

/** 「配音, 批量 ,配音」→ ["配音", "批量"]:逗号(全角半角都认)分开、去空白、去重。 */
export function parseTags(raw: string): string[] {
  const out: string[] = [];
  for (const piece of raw.split(/[,，、]/)) {
    const tag = piece.trim();
    if (tag && !out.includes(tag)) out.push(tag);
  }
  return out.slice(0, 8);
}

/** 发完之后那一屏:状态(已上架 / 审核中)+ 链接(复制、打开)。 */
export function PublishedResult({ result }: { result: CommunityPublishResult }) {
  const t = useI18n();
  const pending = result.status === "pending";
  return (
    <div className="grid gap-3" data-testid="publish-result">
      <p className="m-0 flex items-center gap-2 text-ui-sm font-medium text-foreground">
        {pending ? <Hourglass size={14} className="text-warning" /> : <Check size={14} className="text-success" />}
        {pending ? t("communityStatusPending") : t("communityStatusPublished")}
        {result.version && <span className="text-ui-xs font-normal text-muted-foreground">v{result.version}</span>}
      </p>
      {pending && <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{t("communityPendingBody")}</p>}
      <span className="flex min-w-0 items-center gap-2">
        <Input size="sm" readOnly value={result.url} aria-label={t("boardShareLink")} className="min-w-0 flex-1" data-slug={result.slug} />
        <Button
          variant="outline"
          size="icon-sm"
          title={t("boardShareCopy")}
          aria-label={t("boardShareCopy")}
          onClick={() => {
            void navigator.clipboard?.writeText(result.url);
            toast.success(t("boardShareCopied"));
          }}
        >
          <Copy />
        </Button>
        <Button variant="outline" size="icon-sm" title={t("boardShareOpen")} aria-label={t("boardShareOpen")} onClick={() => openInBrowser(result.url)}>
          <ExternalLink />
        </Button>
      </span>
    </div>
  );
}
