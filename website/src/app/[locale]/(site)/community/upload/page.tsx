import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { AlertCircle, ArrowLeft } from "lucide-react";

import { UploadForm } from "@/components/community/upload-form";
import { cookieHeader, loadViewer } from "@/components/community/share-server";
import { communityLoginHref } from "@/components/community/share-utils";
import { PageGlow } from "@/components/page-hero";
import { isLocale, localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { CloudApiError, type CloudIdentity } from "@/lib/cloud";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;

/** 私有的写作页:登录后才能到,不进搜索索引。 */
export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).community;
  return {
    ...pageMetadata({
      locale,
      path: "/community/upload",
      title: t.uploadSeoTitle,
      description: t.uploadSeoDescription,
    }),
    robots: { index: false, follow: false },
  };
}

function UploadError({ locale, message }: { locale: Locale; message: string }) {
  const t = getMessages(locale).community;
  return (
    <div className="mx-auto grid max-w-[76rem] items-start gap-4 px-5 py-24 sm:px-8">
      <h1 className="m-0 font-display text-3xl font-bold tracking-tight">{t.uploadTitle}</h1>
      <div
        role="alert"
        className="flex max-w-2xl flex-wrap items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
      >
        <AlertCircle className="size-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1">{message}</span>
      </div>
      <div className="flex flex-wrap gap-3">
        <Link href={localePath(locale, "/community/upload")} className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
          {t.retry}
        </Link>
        <Link href={localePath(locale, "/community")} className="text-sm text-muted-foreground underline-offset-4 hover:underline">
          {t.backToCommunity}
        </Link>
      </div>
    </div>
  );
}

/**
 * 上传页。
 *
 * 未登录 → 去登录页,并带 `?next=` 回来(登录页 + 账号页两段小逻辑把它接上,见
 * `login-return.tsx`)。登录了但还没有昵称 → 表单里先起名,保存后继续填同一份内容。
 */
export const dynamic = "force-dynamic";

export default async function CommunityUploadPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).community;
  const uploadPath = localePath(locale, "/community/upload");

  let viewer: CloudIdentity | null = null;
  let failure = "";
  try {
    viewer = await loadViewer(await cookieHeader());
  } catch (error) {
    failure = error instanceof CloudApiError ? error.text(locale) : t.loadFailed;
  }

  if (!viewer && !failure) {
    redirect(communityLoginHref(locale, uploadPath));
  }
  if (!viewer) {
    return <UploadError locale={locale} message={failure} />;
  }

  return (
    <>
      <section className="relative isolate -mt-20 overflow-hidden border-b border-border bg-paper">
        <PageGlow />
        <div className="mx-auto max-w-[76rem] px-5 pt-30 pb-10 sm:px-8 sm:pt-34">
          <Link
            href={localePath(locale, "/community")}
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {t.backToCommunity}
          </Link>
          <p className="mt-6 mb-0 font-mono text-xs font-bold tracking-widest text-primary uppercase">{t.name}</p>
          <h1 className="mt-3 mb-0 font-display text-4xl font-bold tracking-[-0.035em] text-balance sm:text-5xl">
            {t.uploadTitle}
          </h1>
          <p className="mt-3 mb-0 max-w-2xl text-base leading-7 text-muted-foreground">{t.uploadLede}</p>
        </div>
      </section>
      <section className="bg-paper">
        <div className="mx-auto max-w-[46rem] px-5 py-10 sm:px-8 sm:pb-24">
          <UploadForm locale={locale} viewer={viewer} />
        </div>
      </section>
    </>
  );
}
