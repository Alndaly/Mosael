import Link from "next/link";
import { CloudOff, PlugZap } from "lucide-react";
import type * as React from "react";

import { PageGlow } from "@/components/page-hero";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { cn } from "@/lib/utils";

/**
 * 社区页的外壳:页头(小标题 + 大标题 + 一句话)和版心。登录、账号、提交、审核、统计这些
 * 不在「插件 / 工作流」标签页里的页用它;逛的那几页用 CommunityHeader。
 */
export function PageShell({
  eyebrow,
  title,
  lede,
  actions,
  narrow = false,
  children,
}: {
  eyebrow?: string;
  title: string;
  lede?: string;
  actions?: React.ReactNode;
  narrow?: boolean;
  children: React.ReactNode;
}) {
  const width = narrow ? "max-w-xl" : "max-w-[76rem]";
  return (
    <>
      <section className="relative isolate -mt-20 overflow-hidden border-b border-border bg-paper">
        <PageGlow />
        <div className={cn("mx-auto px-5 pt-30 pb-8 sm:px-8 sm:pt-34", width)}>
          {eyebrow && <p className="m-0 font-mono text-xs font-bold tracking-widest text-primary uppercase">{eyebrow}</p>}
          <div className="mt-3 flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
            <div className="min-w-0 max-w-2xl">
              <h1 className="m-0 font-display text-3xl font-bold tracking-[-0.03em] text-balance sm:text-4xl">{title}</h1>
              {lede && <p className="mt-3 mb-0 text-base leading-7 text-muted-foreground">{lede}</p>}
            </div>
            {actions && <div className="flex flex-wrap gap-2.5">{actions}</div>}
          </div>
        </div>
      </section>
      <section className="bg-paper">
        <div className={cn("mx-auto px-5 py-10 sm:px-8 sm:pb-24", width)}>{children}</div>
      </section>
    </>
  );
}

/** 没配 `COMMUNITY_API_URL`:社区未开放。不回退到静态索引(ADR 0026 §8)。 */
export function CommunityUnavailable({ locale }: { locale: Locale }) {
  const t = getMessages(locale).community;
  return (
    <PageShell eyebrow={t.name} title={t.unavailableTitle} narrow>
      <div className="grid place-items-center gap-4 rounded-2xl border border-dashed border-border px-6 py-16 text-center">
        <PlugZap className="size-7 text-muted-foreground" aria-hidden />
        <p className="m-0 max-w-md text-sm leading-6 text-muted-foreground">{t.unavailableBody}</p>
        <Link href={localePath(locale, "/docs")} className="text-sm font-semibold text-primary hover:underline">
          {t.unavailableDocs}
        </Link>
      </div>
    </PageShell>
  );
}

/** 配了服务、但这次没连上(或回了 5xx)。 */
export function CommunityDown({ locale, message }: { locale: Locale; message?: string }) {
  const t = getMessages(locale).community;
  return (
    <div className="grid place-items-center gap-3 rounded-2xl border border-dashed border-border px-6 py-16 text-center">
      <CloudOff className="size-7 text-muted-foreground" aria-hidden />
      <p className="m-0 font-semibold">{t.errorTitle}</p>
      <p className="m-0 max-w-md text-sm leading-6 text-muted-foreground">{message || t.errorBody}</p>
    </div>
  );
}
