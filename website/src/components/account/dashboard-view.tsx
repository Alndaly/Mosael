"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { sumShareStats, type CloudIdentity, type CloudShare } from "@/lib/cloud";
import { queryKeys } from "@/lib/queryKeys";
import { useMyShares, useViewer } from "@/lib/queries";

import { DashboardHeader } from "./dashboard-header";
import { DashboardNotifications } from "./dashboard-notifications";
import { DashboardOverview } from "./dashboard-overview";
import { DashboardProfile } from "./dashboard-profile";
import { DashboardShares } from "./dashboard-shares";
import { dashboardTabHref, withoutShare, type DashboardTab } from "./dashboard-utils";

/**
 * 「我的」控制台:页头 + 四个分区。
 *
 * 身份门禁在服务端(`app/[locale]/(site)/dashboard/page.tsx`)—— 未登录根本到不了这里;
 * 这一层只管「切分区」和「删掉一条之后列表与统计一起变」。
 *
 * 分区状态不是一次性的:换 tab 会 `replaceState` 改地址栏(`?tab=`),刷新、收藏、发给别人
 * 都还能打开同一个分区;tab 本身仍是 `<Link>`,新标签打开也成立。
 *
 * 数据只有一份来源:身份读 `useViewer()`(与站头同一条 `/me` 缓存),分享读 `useMyShares()`
 * (服务端首屏数据作为 `initialData`)。保存资料后 viewer 失效,这里的 `hasHandle` 与昵称
 * 立刻变新,不需要 `router.refresh()` 再问一次服务端。
 *
 * 概览的五个数字由这里的 `shares` 求和得出 —— 删掉一条,先就地写回同一份查询缓存,
 * 列表和数字在**同一次渲染**里一起变,不会出现「列表少了一条、统计还是旧数」。
 */
export function DashboardView({
  locale,
  copy,
  viewer,
  shares: initialShares,
  initialTab,
  loadError = "",
}: {
  locale: Locale;
  copy: Messages["dashboard"];
  viewer: CloudIdentity;
  shares: CloudShare[];
  initialTab: DashboardTab;
  loadError?: string;
}) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<DashboardTab>(initialTab);
  // 与站头同一份 /me:改完资料 invalidate 之后,handle 与「有没有 handle」跟着变新。
  const { data: liveViewer } = useViewer();
  const currentViewer = liveViewer === undefined ? viewer : liveViewer;
  const handle = currentViewer?.handle?.trim() ?? "";
  const hasHandle = Boolean(handle);
  // 首屏数据只属于**服务端那个 handle**:刚起完名字时 handle 变了,旧的那份不能当新 key 的
  // initialData(否则会被当成新鲜数据,概览停在 0 不重取)。
  const seeded = handle === (viewer.handle?.trim() ?? "") ? initialShares : undefined;
  const { data: shares = [] } = useMyShares(handle, seeded);
  const totals = sumShareStats(shares);

  const select = (next: DashboardTab) => {
    setTab(next);
    // 只改地址、不导航:换分区不该重新向服务端要一次整页。
    try {
      window.history.replaceState(null, "", dashboardTabHref(locale, next));
    } catch {
      // 某些嵌入式浏览器禁用 history:分区照切,只是地址栏不变。
    }
  };

  const removeShare = (id: string) => {
    // 就地写回查询缓存(概览统计同一份数据,数字一起变);随后 DashboardShares 会让
    // sharesByMe 与该 kind 的列表失效,重取时以云端为准。
    queryClient.setQueryData<CloudShare[]>(queryKeys.sharesByMe(handle), (current) =>
      withoutShare(current ?? [], id),
    );
  };

  return (
    <>
      <DashboardHeader locale={locale} active={tab} copy={copy} onSelect={select} />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          {tab === "overview" && (
            <DashboardOverview
              locale={locale}
              copy={copy}
              shares={shares}
              totals={totals}
              hasHandle={hasHandle}
              loadError={loadError}
              onGoToProfile={() => select("profile")}
              onSelect={select}
            />
          )}
          {tab === "shares" && (
            <DashboardShares
              locale={locale}
              copy={copy}
              shares={shares}
              hasHandle={hasHandle}
              loadError={loadError}
              onRemoved={removeShare}
              onGoToProfile={() => select("profile")}
            />
          )}
          {tab === "profile" && (
            <DashboardProfile locale={locale} copy={copy} viewer={currentViewer ?? viewer} onSelect={select} />
          )}
          {tab === "notifications" && <DashboardNotifications locale={locale} copy={copy} />}
        </div>
      </section>
    </>
  );
}
