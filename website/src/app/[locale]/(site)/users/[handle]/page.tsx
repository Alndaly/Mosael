import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, BadgeCheck, Bookmark, Download, Heart, MessageSquare, PackageOpen } from "lucide-react";

import { ShareCard } from "@/components/community/shares";
import { cookieHeader, loadPublicIdentity, loadUserShares } from "@/components/community/share-server";
import { InitialTile } from "@/components/community/tile";
import { PageGlow } from "@/components/page-hero";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { CloudApiError, type CloudIdentity } from "@/lib/cloud";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string; handle: string }>;

const STAT_ICONS = {
  downloads: Download,
  likes: Heart,
  favorites: Bookmark,
  comments: MessageSquare,
} as const;

/**
 * 公开创作者主页：一个 handle 的公开身份与全部公开分享。
 *
 * 数据来自 `GET /users/{handle}`（公开四列）与 `GET /users/{handle}/shares`（翻完所有页）：
 * 公开页能看到的，就是别人分享出去的。短名不存在时由公开身份接口给 404，不猜。
 */
export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale, handle } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).community;
  const identity = await loadPublicIdentity(handle, await cookieHeader()).catch(() => null);
  const name = identity?.display_name?.trim() || handle;
  return pageMetadata({
    locale,
    path: `/users/${handle}`,
    title: t.creatorSeoTitle.replace("{name}", name),
    description: t.creatorSeoDescription.replace("{name}", name),
  });
}

export const dynamic = "force-dynamic";

export default async function CreatorPage({ params }: { params: Params }) {
  const { locale, handle } = await params;
  if (!isLocale(locale)) notFound();
  const key = handle.trim();
  if (!key) notFound();

  const cookie = await cookieHeader();
  let identity: CloudIdentity;
  try {
    identity = await loadPublicIdentity(key, cookie);
  } catch (failure) {
    if (failure instanceof CloudApiError && failure.status === 404) notFound();
    throw failure;
  }
  const { shares, totals } = await loadUserShares(key, cookie);

  const t = getMessages(locale).community;
  const name = identity.display_name?.trim() || identity.handle || key;
  const seed = identity.avatar_seed || identity.handle || key;
  // 昵称本身已经带「官方」时不再重复画一枚徽标。
  const showOfficial = Boolean(identity.official) && !name.includes(t.official);
  const stats = [
    { key: "downloads" as const, label: t.downloads, value: totals.downloads },
    { key: "likes" as const, label: t.likes, value: totals.likes },
    { key: "favorites" as const, label: t.favorites, value: totals.favorites },
    { key: "comments" as const, label: t.comments, value: totals.comments },
  ];

  return (
    <>
      <section className="relative isolate -mt-20 overflow-hidden border-b border-border bg-paper">
        <PageGlow />
        <div className="mx-auto max-w-[76rem] px-5 pt-32 pb-10 sm:px-8 sm:pt-36">
          <Link
            href={localePath(locale, "/community")}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {t.backToCommunity}
          </Link>

          <div className="mt-7 flex flex-wrap items-center gap-5">
            <InitialTile seed={seed} name={name} size="lg" />
            <div className="min-w-0">
              <p className="m-0 font-mono text-xs font-bold tracking-widest text-primary uppercase">{t.creatorProfile}</p>
              <h1 className="mt-2 mb-0 flex flex-wrap items-center gap-2 font-display text-4xl font-bold tracking-[-0.035em] text-balance sm:text-5xl">
                {name}
                {showOfficial && (
                  <span className="inline-flex items-center gap-1 text-base font-medium text-primary">
                    <BadgeCheck className="size-5" aria-hidden />
                    {t.official}
                  </span>
                )}
              </h1>
              <p className="mt-2 mb-0 font-mono text-sm text-muted-foreground">@{identity.handle || key}</p>
            </div>
          </div>

          <dl className="m-0 mt-8 flex flex-wrap gap-x-8 gap-y-3 border-t border-border pt-5">
            {stats.map(({ key: stat, label, value }) => {
              const Icon = STAT_ICONS[stat];
              return (
                <div key={stat} className="flex items-baseline gap-2">
                  <Icon className="size-4 self-center text-muted-foreground" aria-hidden />
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="m-0 font-mono text-lg font-semibold tabular-nums">{value}</dd>
                </div>
              );
            })}
          </dl>
        </div>
      </section>

      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="m-0 font-display text-2xl font-semibold tracking-[-0.03em]">{t.publicShares}</h2>
            <span className="font-mono text-sm text-muted-foreground tabular-nums">{shares.length}</span>
          </div>

          {shares.length === 0 ? (
            <div className="mt-5 rounded-2xl border border-dashed border-border bg-card px-6 py-16 text-center">
              <PackageOpen className="mx-auto size-6 text-muted-foreground" aria-hidden />
              <p className="mt-4 mb-0 font-semibold">{t.publicSharesEmpty}</p>
              <p className="mt-1 mb-0 text-sm text-muted-foreground">{t.publicSharesEmptyHint}</p>
            </div>
          ) : (
            <ul className="m-0 mt-5 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
              {shares.map((share) => (
                <li key={share.id} className="min-w-0">
                  <ShareCard locale={locale} share={share} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </>
  );
}
