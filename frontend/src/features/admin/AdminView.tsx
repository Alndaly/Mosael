import React from "react";

import type { Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CollectionTabs, PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { useOpenRequest } from "@/lib/deepLink";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { AdminOverview } from "./AdminOverview";
import { AdminMembers } from "./AdminMembers";
import { AiRuntimeSection } from "./AiRuntimeSection";
import { DataDiagnosticsSection } from "./DataDiagnosticsSection";
import { InstallSourceSection } from "./InstallSourceSection";
import { ProviderPricingSection } from "./ProviderPricingSection";
import { ProxySection } from "./ProxySection";
import { RegistrationSection } from "./RegistrationSection";
import { SharedHostFoldersSection } from "./SharedHostFoldersSection";

const TABS = ["overview", "members", "pricing", "deployment"] as const;
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
 * **判据是「谁能写」,不是「在哪个菜单里顺手」。** 后端只许部署管理员写的东西(ensure_deployment_admin)
 * 都在这里:成本规则、出站代理与重试、安装源、备份恢复。它们此前摆在设置页,对每个成员可见 ——
 * 普通成员看得到表单、一保存就 403;读代理被拒后还画着两个空框,等于告诉他「直连」。
 *
 * **分四个 tab**:概览(读数与两张图)、成员(账户与邀请码)、成本规则(用量按什么价入账)、
 * 部署设置(谁能加入、共享文件夹、网络出口、安装源、数据)。成本规则单独一个 tab:它是一整张
 * 可筛选、可批量删的表,挤进部署设置会把其余几节压到很下面。
 *
 * 版式上,页面本身是 STUDIO_PAGE —— 一条 flex 列,子项一律 `shrink-0`;每个 tab 的内容是一个
 * **不定高**的网格。行高只由内容决定,没有哪一节能被压扁、让下一节画到它身上(见 adminLayout)。
 */
export function AdminView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const [tab, setTab] = usePersistentTab<AdminTab>("admin", "overview", TABS);
  // 深链(gotoAdmin):统计页的「N 次未定价」→ 成本规则。认不出的 tab 原地不动。
  useOpenRequest("mosael:open-admin", (link) => {
    const target = TABS.find((one) => one === link);
    if (target) setTab(target);
  });

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
              { value: "pricing", label: t("adminTabPricing") },
              { value: "deployment", label: t("adminTabDeployment") },
            ]}
          />
        </div>
      </div>
      {/* 各个 tab 同一个宽度:铺满内容区,和设置页、插件页一致。部署设置此前单独收窄到 max-w-4xl,
          右边空出半屏,和上面铺满的 tab 栏对不齐(用户指出过)。 */}
      <div data-admin-panel={tab} className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-10">
        {tab === "overview" && <AdminOverview onConfigurePricing={() => setTab("pricing")} />}
        {tab === "members" && <AdminMembers onOpenDeployment={() => setTab("deployment")} />}
        {tab === "pricing" && <ProviderPricingSection workspace={workspace} />}
        {tab === "deployment" && (
          <>
            <RegistrationSection />
            {/* 这台电脑上的文件归部署管理员;共享出来的文件夹才是成员读得到的。 */}
            <SharedHostFoldersSection />
            {/* 代理和重试挨着:回答的是同一个问题 —— 这台部署的 AI 调用怎么出去。 */}
            <ProxySection />
            <AiRuntimeSection />
            <InstallSourceSection />
            <DataDiagnosticsSection />
          </>
        )}
      </div>
    </div>
  );
}
