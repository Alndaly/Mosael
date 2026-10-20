import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { AlertCircle } from "lucide-react";

import { DashboardView } from "@/components/account/dashboard-view";
import {
  dashboardLoginHref,
  defaultDashboardTab,
  normalizeDashboardTab,
} from "@/components/account/dashboard-utils";
import { cookieHeader, loadUserShares, loadViewer } from "@/components/community/share-server";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { CloudApiError, type CloudShare } from "@/lib/cloud";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;
type SearchParams = Promise<{ tab?: string | string[]; user_code?: string | string[] }>;

/** 私有的控制台:登录后才能到,不进搜索索引。 */
export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).dashboard;
  return {
    ...pageMetadata({ locale, path: "/dashboard", title: t.seoTitle, description: t.seoDescription }),
    robots: { index: false, follow: false },
  };
}

/** 查询串里的值可能是数组;控制台只认第一个。 */
function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

/**
 * 「我的」控制台。
 *
 * 门禁和社区上传页同一套:服务端读会话(第一方 HttpOnly cookie → `/me`),未登录就 **307**
 * 去登录页并带 `?next=` 回来。没有昵称(刚注册、还没起名)也放进来 —— 直接停在「个人信息」,
 * 那里有一句「先起个名字」(见 `defaultDashboardTab`),而不是把概览留成一片空白。
 *
 * 页面本身只做取数:身份(公开三列,不含 email)、这个人的公开分享、以及按分享 `stats` 求和。
 * 交互(切分区 / 删除 / 改身份 / 设备)都在 `DashboardView` 那一层。
 */
export const dynamic = "force-dynamic";

export default async function DashboardPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  const search = await searchParams;
  const copy = getMessages(locale).dashboard;
  const accountCopy = getMessages(locale).account;

  const cookie = await cookieHeader();
  let viewer: Awaited<ReturnType<typeof loadViewer>> = null;
  let failure = "";
  try {
    viewer = await loadViewer(cookie);
  } catch (error) {
    failure = error instanceof CloudApiError ? error.text(locale) : copy.loadFailed;
  }

  // 401(没登录)不是错误:去登录页,登录完回到这里。云端故障则留在原地给可重试的说明。
  if (!viewer && !failure) redirect(dashboardLoginHref(locale));

  if (!viewer) {
    return (
      <section className="bg-paper">
        <div className="mx-auto grid max-w-[76rem] items-start gap-4 px-5 py-24 sm:px-8">
          <h1 className="m-0 font-display text-3xl font-bold tracking-tight">{copy.title}</h1>
          <div
            role="alert"
            className="flex max-w-2xl flex-wrap items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1">{failure || copy.loadFailed}</span>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link
              href={localePath(locale, "/dashboard")}
              className="text-sm font-semibold text-primary underline-offset-4 hover:underline"
            >
              {copy.retry}
            </Link>
            <Link
              href={localePath(locale, "/community")}
              className="text-sm text-muted-foreground underline-offset-4 hover:underline"
            >
              {getMessages(locale).community.backToCommunity}
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const handle = viewer.handle?.trim() ?? "";
  let shares: CloudShare[] = [];
  let loadError = "";
  if (handle) {
    try {
      shares = (await loadUserShares(handle, cookie)).shares;
    } catch (error) {
      loadError = error instanceof CloudApiError ? error.text(locale) : copy.sharesLoadFailed;
    }
  }

  const initialTab = normalizeDashboardTab(search.tab) || defaultDashboardTab(Boolean(handle));

  return (
    <DashboardView
      locale={locale}
      copy={copy}
      accountCopy={accountCopy}
      viewer={viewer}
      shares={shares}
      initialTab={initialTab}
      initialCode={first(search.user_code)}
      loadError={loadError}
    />
  );
}
