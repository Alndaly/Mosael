import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { headers } from "next/headers";
import { connection } from "next/server";
import { Link2Off } from "lucide-react";
import type * as React from "react";

import { BoardViewer } from "@/components/community/board-viewer";
import { ReportButton } from "@/components/community/item-actions";
import { SafeMarkdown } from "@/components/community/safe-markdown";
import { ShareButton } from "@/components/community/share-button";
import { CommunityDown, CommunityUnavailable, PageShell } from "@/components/community/shell";
import { BUTTON } from "@/components/community/styles";
import { StatePanel } from "@/components/community/ui";
import { isLocale, localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { isSnapshot, toFlow } from "@/lib/community/board";
import { ENDPOINTS } from "@/lib/community/endpoints";
import { fill, formatDate } from "@/lib/community/format";
import { communityEnabled, serverGet } from "@/lib/community/server";
import type { ShareDetail } from "@/lib/community/types";

type Props = { params: Promise<{ locale: string; slug: string }> };

async function load(locale: Locale, slug: string) {
  return serverGet<ShareDetail>(ENDPOINTS.shares.detail(slug), locale);
}

/**
 * Open Graph / Twitter 卡片:预览图由社区服务在第一次访问时从快照生成(ADR 0026 §5)。
 * `unlisted` 的不让搜索引擎收录 —— 「知道链接才能看」不该变成「搜得到」。
 */
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale) || !communityEnabled()) return {};
  const t = getMessages(locale);
  const result = await load(locale, slug);
  if (!result.ok) return { title: `${result.error.status === 410 ? t.boards.revokedTitle : t.boards.notFoundTitle} · Mosael`, robots: { index: false } };
  const share = result.data;
  const title = share.title || t.boards.untitled;
  const author = share.owner.display_name || share.owner.handle;
  // 预览图地址由服务给,通常是相对路径(`/api/community/v1/shares/…/og.png`):按这次请求的站点补全,
  // 本地开发时指向本地,线上指向线上 —— 不写死 SITE.url。
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const proto = requestHeaders.get("x-forwarded-proto") ?? (host?.startsWith("localhost") || host?.startsWith("127.") ? "http" : "https");
  const description = `${author} · ${fill(t.boards.cells, { count: share.snapshot.items?.length ?? 0 })} · Mosael`;
  const images = share.og_image_url ? [{ url: share.og_image_url, width: 1200, height: 630, alt: title }] : undefined;
  return {
    ...(host ? { metadataBase: new URL(`${proto}://${host}`) } : {}),
    title: `${title} · Mosael`,
    description,
    robots: share.visibility === "public" ? undefined : { index: false, follow: false },
    alternates: { canonical: `/${locale}/b/${share.slug}` },
    openGraph: { type: "website", siteName: "Mosael", title, description, url: `/${locale}/b/${share.slug}`, images },
    twitter: { card: images ? "summary_large_image" : "summary", title, description, images: images?.map((image) => image.url) },
  };
}

export default async function SharedBoardPage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const result = await load(locale, slug);

  if (!result.ok) {
    if (result.error.status === 404) notFound();
    if (result.error.status === 410) {
      return (
        <PageShell eyebrow={t.boards.title} title={t.boards.revokedTitle} narrow>
          <StatePanel icon={<Link2Off className="size-7 text-muted-foreground" aria-hidden />} title={t.boards.revokedTitle} body={t.boards.revokedBody}>
            <Link href={localePath(locale, "/boards")} className="text-sm font-semibold text-primary hover:underline">
              {t.boards.title}
            </Link>
          </StatePanel>
        </PageShell>
      );
    }
    return (
      <PageShell eyebrow={t.boards.title} title={t.boards.title} narrow>
        <CommunityDown locale={locale} message={result.error.message} />
      </PageShell>
    );
  }

  const share = result.data;
  if (!isSnapshot(share.snapshot)) {
    return (
      <PageShell eyebrow={t.boards.title} title={share.title || t.boards.untitled} narrow>
        <CommunityDown locale={locale} />
      </PageShell>
    );
  }
  const { nodes, edges } = toFlow(share);
  // 文档格的正文在服务端渲染好交给画布:markdown 渲染器不进浏览器的包,也就不会有第二套规则。
  const documents: Record<string, React.ReactNode> = Object.fromEntries(
    share.snapshot.items
      .filter((item) => item.kind === "document" && typeof item.markdown === "string")
      .map((item) => [item.id, <SafeMarkdown key={item.id} source={item.markdown ?? ""} />]),
  );
  const title = share.title || t.boards.untitled;

  return (
    // 画布占满站头以下的整屏;站脚在画布之后,往下滚才看得到。
    <div className="flex h-[calc(100dvh-5rem)] min-h-[28rem] flex-col border-b border-border">
      <header className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border bg-paper px-4 py-3 sm:px-6">
        <div className="grid min-w-0 flex-1 gap-0.5">
          <h1 className="m-0 truncate text-lg font-semibold tracking-tight sm:text-xl">{title}</h1>
          <p className="m-0 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
            <Link href={localePath(locale, `/u/${share.owner.handle}`)} className="font-medium text-foreground hover:underline">
              {share.owner.display_name || share.owner.handle}
            </Link>
            <span>
              {t.community.updated} {formatDate(share.updated_at, locale)}
            </span>
            <span>{fill(t.boards.versionLabel, { version: share.version })}</span>
            <span>{fill(t.boards.cells, { count: nodes.length })}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ReportButton locale={locale} kind="share" slug={share.slug} />
          <ShareButton title={title} label={t.boards.share} copiedLabel={t.boards.copied} />
          <Link href={localePath(locale, "/docs/start/download")} className={`${BUTTON.primary} min-h-9 px-4`}>
            {t.community.openInApp}
          </Link>
        </div>
      </header>
      <div className="min-h-0 flex-1">
        <BoardViewer locale={locale} nodes={nodes} edges={edges} documents={documents} />
      </div>
    </div>
  );
}
