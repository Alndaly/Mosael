"use client";

import { useState } from "react";

import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { sumShareStats, type CloudIdentity, type CloudShare } from "@/lib/cloud";

import { DashboardDevices } from "./dashboard-devices";
import { DashboardHeader } from "./dashboard-header";
import { DashboardNotifications } from "./dashboard-notifications";
import { DashboardOverview } from "./dashboard-overview";
import { DashboardProfile } from "./dashboard-profile";
import { DashboardShares } from "./dashboard-shares";
import { dashboardTabHref, withoutShare, type DashboardTab } from "./dashboard-utils";

/**
 * 「我的」控制台:页头 + 五个分区。
 *
 * 身份门禁在服务端(`app/[locale]/(site)/dashboard/page.tsx`)—— 未登录根本到不了这里;
 * 这一层只管「切分区」和「删掉一条之后列表与统计一起变」。
 *
 * 分区状态不是一次性的:换 tab 会 `replaceState` 改地址栏(`?tab=`),刷新、收藏、发给别人
 * 都还能打开同一个分区;tab 本身仍是 `<Link>`,新标签打开也成立。
 *
 * 概览的五个数字由这里的 `shares` 求和得出 —— 删掉一条,列表和数字在**同一次渲染**里一起
 * 变,不会出现「列表少了一条、统计还是旧数」。
 */
export function DashboardView({
  locale,
  copy,
  accountCopy,
  viewer,
  shares: initialShares,
  initialTab,
  initialCode = "",
  loadError = "",
}: {
  locale: Locale;
  copy: Messages["dashboard"];
  accountCopy: Messages["account"];
  viewer: CloudIdentity;
  shares: CloudShare[];
  initialTab: DashboardTab;
  /** 桌面绑定带来的确认码(`/account?user_code=…` 转过来),设备分区会预填。 */
  initialCode?: string;
  loadError?: string;
}) {
  const [tab, setTab] = useState<DashboardTab>(initialTab);
  const [shares, setShares] = useState<CloudShare[]>(initialShares);
  const hasHandle = Boolean(viewer.handle?.trim());
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
              onRemoved={(id) => setShares((current) => withoutShare(current, id))}
              onGoToProfile={() => select("profile")}
            />
          )}
          {tab === "profile" && (
            <DashboardProfile locale={locale} copy={copy} viewer={viewer} onSelect={select} />
          )}
          {tab === "devices" && <DashboardDevices locale={locale} copy={accountCopy} initialCode={initialCode} />}
          {tab === "notifications" && <DashboardNotifications locale={locale} copy={copy} />}
        </div>
      </section>
    </>
  );
}
