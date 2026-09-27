import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import type * as React from "react";

import { BoardCard, GRID, PluginCard, WorkflowCard } from "@/components/community/cards";
import { Heatmap } from "@/components/community/charts";
import { Avatar } from "@/components/community/header-menus";
import { CommunityDown, CommunityUnavailable, PageShell } from "@/components/community/shell";
import { PageGlow } from "@/components/page-hero";
import { isLocale, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS } from "@/lib/community/endpoints";
import { formatDate } from "@/lib/community/format";
import { communityEnabled, serverGet } from "@/lib/community/server";
import type { Profile } from "@/lib/community/types";

type Props = { params: Promise<{ locale: string; handle: string }> };

async function load(locale: Locale, handle: string) {
  return serverGet<Profile>(ENDPOINTS.users.profile(handle), locale);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, handle } = await params;
  if (!isLocale(locale) || !communityEnabled()) return {};
  const result = await load(locale, handle);
  if (!result.ok) return {};
  const { user } = result.data;
  return { title: `${user.display_name || user.handle} (@${user.handle}) · Mosael` };
}

function Shelf({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section className="grid gap-5">
      <h2 className="m-0 flex items-center gap-2 border-b border-border pb-3 text-lg font-semibold tracking-tight">
        {title}
        <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-xs tabular-nums text-muted-foreground">{count}</span>
      </h2>
      {children}
    </section>
  );
}

/** 作者主页(ADR 0026 §7):TA 的工作流、插件、公开画板,和逐日贡献热力图。 */
export default async function ProfilePage({ params }: Props) {
  const { locale, handle } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const profile = await load(locale, handle);
  if (!profile.ok) {
    if (profile.error.status === 404) notFound();
    return (
      <PageShell eyebrow={t.community.name} title={`@${handle}`}>
        <CommunityDown locale={locale} message={profile.error.message} />
      </PageShell>
    );
  }
  // 一次取齐:最近的工作流、插件、公开画板各一页,加近一年的贡献(服务端 `GET /users/{handle}`)。
  const { user, workflows: workflowItems, plugins: pluginItems, boards: boardItems } = profile.data;

  return (
    <>
      <section className="relative isolate -mt-20 overflow-hidden border-b border-border bg-paper">
        <PageGlow />
        <div className="mx-auto flex max-w-[76rem] flex-wrap items-center gap-5 px-5 pt-30 pb-10 sm:px-8 sm:pt-34">
          <Avatar user={user} size="lg" />
          <div className="grid min-w-0 gap-1">
            <h1 className="m-0 font-display text-3xl font-bold tracking-[-0.03em] sm:text-4xl">{user.display_name || user.handle}</h1>
            <p className="m-0 font-mono text-sm text-muted-foreground">@{user.handle}</p>
            {user.created_at && (
              <p className="m-0 text-xs text-muted-foreground">
                {t.profile.joined} {formatDate(user.created_at, locale)}
              </p>
            )}
          </div>
        </div>
      </section>
      <section className="bg-paper">
        <div className="mx-auto grid max-w-[76rem] gap-14 px-5 py-10 sm:px-8 sm:pb-24">
          <section className="grid gap-4">
            <h2 className="m-0 border-b border-border pb-3 text-lg font-semibold tracking-tight">{t.profile.contributions}</h2>
            <Heatmap locale={locale} points={profile.data.contributions ?? []} />
          </section>

          <Shelf title={t.profile.workflows} count={profile.data.workflows_count}>
            {workflowItems.length > 0 ? (
              <ul className={GRID}>
                {workflowItems.map((item) => (
                  <li key={item.slug} className="grid">
                    <WorkflowCard locale={locale} item={item} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-sm text-muted-foreground">{t.profile.empty}</p>
            )}
          </Shelf>

          <Shelf title={t.profile.plugins} count={profile.data.plugins_count}>
            {pluginItems.length > 0 ? (
              <ul className={GRID}>
                {pluginItems.map((item) => (
                  <li key={item.slug} className="grid">
                    <PluginCard locale={locale} item={item} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-sm text-muted-foreground">{t.profile.empty}</p>
            )}
          </Shelf>

          <Shelf title={t.profile.boards} count={profile.data.boards_count}>
            {boardItems.length > 0 ? (
              <ul className={GRID}>
                {boardItems.map((share) => (
                  <li key={share.slug} className="grid">
                    <BoardCard locale={locale} share={share} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-sm text-muted-foreground">{t.profile.empty}</p>
            )}
          </Shelf>
        </div>
      </section>
    </>
  );
}
