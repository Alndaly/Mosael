import React from "react";

import { useI18n } from "@/app/preferences";
import { CollectionTabs, PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { AdminOverview } from "./AdminOverview";
import { AdminMembers } from "./AdminMembers";
import { RegistrationSection } from "./RegistrationSection";
import { SharedHostFoldersSection } from "./SharedHostFoldersSection";

const TABS = ["overview", "members", "deployment"] as const;
export type AdminTab = (typeof TABS)[number];

/**
 * 管理员控制台 —— **这台部署**的状况。
 *
 * 和「设置」是两件事,所以它是侧边栏里独立的一格,不挤在设置页里:设置回答"我怎么用这个应用"
 * (外观、我的密钥、我的默认模型);这里回答"这台部署怎么样" —— 谁进来了、谁在花钱、谁的
 * 客户端还停在旧版本。
 *
 * 入口只对部署管理员显示(见 AppShell),后端每条路由也各自把关 —— 藏起来的入口不是权限。
 *
 * **分三个 tab**:概览(读数与两张图)、成员(账户与邀请码)、部署设置(谁能加入、共享文件夹)。
 * 此前是一整条长页,七块东西一路排下去,读的和改的混在一起。
 *
 * 版式上,页面本身是 STUDIO_PAGE —— 一条 flex 列,子项一律 `shrink-0`;每个 tab 的内容是一个
 * **不定高**的网格。行高只由内容决定,没有哪一节能被压扁、让下一节画到它身上(见 adminLayout)。
 */
export function AdminView() {
  const t = useI18n();
  const [tab, setTab] = usePersistentTab<AdminTab>("admin", "overview", TABS);

  return (
    <div className={STUDIO_PAGE} data-admin-page>
      <div className="grid min-w-0 gap-4">
        <PageHeading title={t("navAdmin")} description={t("studioAdminDesc")} />
        <div className="border-b border-divider">
          <CollectionTabs
            label={t("adminTabsLabel")}
            value={tab}
            onChange={setTab}
            items={[
              { value: "overview", label: t("adminTabOverview") },
              { value: "members", label: t("adminTabMembers") },
              { value: "deployment", label: t("adminTabDeployment") },
            ]}
          />
        </div>
      </div>
      {/* 三个 tab 同一个宽度:铺满内容区,和设置页、插件页一致。部署设置此前单独收窄到 max-w-4xl,
          右边空出半屏,和上面铺满的 tab 栏对不齐(用户指出过)。 */}
      <div data-admin-panel={tab} className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-10">
        {tab === "overview" && <AdminOverview />}
        {tab === "members" && <AdminMembers onOpenDeployment={() => setTab("deployment")} />}
        {tab === "deployment" && (
          <>
            <RegistrationSection />
            {/* 这台电脑上的文件归部署管理员;共享出来的文件夹才是成员读得到的。 */}
            <SharedHostFoldersSection />
          </>
        )}
      </div>
    </div>
  );
}
