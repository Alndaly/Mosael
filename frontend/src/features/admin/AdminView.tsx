import React from "react";

import { ShieldCheck } from "lucide-react";

import type { Workspace } from "@/api/client";
import { useDeploymentAdmin } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { EmptyState } from "@/components/layout/EmptyState";
import { CollectionTabs, PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { useOpenRequest } from "@/lib/deepLink";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { ADMIN_TABS, type AdminTab } from "@/lib/adminTabs";
import { AdminOverview } from "./AdminOverview";
import { AdminMembers } from "./AdminMembers";
import { AiRuntimeSection } from "./AiRuntimeSection";
import { AsrModelsSection } from "./AsrModelsSection";
import { DataDiagnosticsSection } from "./DataDiagnosticsSection";
import { StorageCleanupSection } from "./StorageCleanupSection";
import { DenoiseEnginesSection } from "./DenoiseEnginesSection";
import { InstallSourceSection } from "./InstallSourceSection";
import { ProviderPricingSection } from "./ProviderPricingSection";
import { ProxySection } from "./ProxySection";
import { RegistrationSection } from "./RegistrationSection";
import { SeparationEnginesSection } from "./SeparationEnginesSection";
import { SharedHostFoldersSection } from "./SharedHostFoldersSection";
import { OutboundAllowlistSection } from "./OutboundAllowlistSection";
import { VoiceCloneSection } from "./VoiceCloneSection";


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
 * 都在这里:成本规则、出站代理与重试、本机引擎的安装与下载源、备份恢复。它们此前摆在设置页,
 * 对每个成员可见 —— 普通成员看得到表单、一保存就 403;读代理被拒后还画着两个空框,等于告诉他「直连」。
 *
 * **分五个 tab**:概览(读数与两张图)、成员(账户与邀请码)、成本规则(用量按什么价入账)、
 * 引擎(这台机器上装哪些本机引擎、从哪儿装)、部署设置(谁能加入、共享文件夹、网络出口、数据)。
 * 成本规则单独一个 tab:它是一整张可筛选、可批量删的表,挤进部署设置会把其余几节压到很下面。
 * 引擎也单独一个 tab,理由相同而更甚:转写、声音克隆、人声分离、降噪四节各是一张带进度条的清单,
 * 克隆还有一张表单,合起来比部署设置其余几节加在一起还长;来这里的人要做的也是另一件事 ——
 * 点下载、盯着几个 GB 走完,而不是改一个开关。下载源(pip 镜像)只管装这些引擎的依赖,跟着引擎走,
 * 排在最前:先选好从哪儿拉,再点下面的安装。
 *
 * 版式上,页面本身是 STUDIO_PAGE —— 一条 flex 列,子项一律 `shrink-0`;每个 tab 的内容是一个
 * **不定高**的网格。行高只由内容决定,没有哪一节能被压扁、让下一节画到它身上(见 adminLayout)。
 */
export function AdminView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const [tab, setTab] = usePersistentTab<AdminTab>("admin", "overview", ADMIN_TABS);
  // 深链(gotoAdmin):统计页的「N 次未定价」→ 成本规则;转写、降噪等处「引擎没装」→ 引擎。
  // 认不出的 tab 原地不动。
  useOpenRequest("mosael:open-admin", (link) => {
    const target = ADMIN_TABS.find((one) => one === link);
    if (target) setTab(target);
  });
  //: 入口只对部署管理员显示,但地址(#/admin)谁都打得开。此前非管理员打开是四个「—」、「还没有产生花费」+「去设置价格规则」
  //: —— 把 403 画成了空(体检 UM-21)。直接说这一页是谁的。
  const admin = useDeploymentAdmin();
  if (admin === false) {
    return (
      <div className={STUDIO_PAGE} data-admin-page data-admin-forbidden="">
        <PageHeading title={t("navAdmin")} description={t("studioAdminDesc")} />
        <EmptyState icon={<ShieldCheck size={22} />} title={t("adminOnlyTitle")} body={t("adminOnlyBody")} />
      </div>
    );
  }

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
              { value: "engines", label: t("adminTabEngines") },
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
        {tab === "engines" && (
          <>
            <InstallSourceSection />
            <AsrModelsSection />
            <VoiceCloneSection />
            <SeparationEnginesSection />
            <DenoiseEnginesSection />
          </>
        )}
        {tab === "deployment" && (
          <>
            <RegistrationSection />
            {/* 这台电脑上的文件归部署管理员;共享出来的文件夹才是成员读得到的。 */}
            <SharedHostFoldersSection />
            {/* 用户给的地址能去哪些内网地址 —— 和代理一样回答「这台部署怎么出去」,排在它前面。 */}
            <OutboundAllowlistSection />
            {/* 代理和重试挨着:回答的是同一个问题 —— 这台部署的 AI 调用怎么出去。 */}
            <ProxySection />
            <AiRuntimeSection />
            <DataDiagnosticsSection />
            {/* 没人认领的文件:列出来,确认后才删(后端 domain/storage_cleanup)。挨着备份恢复 —— 都是这台部署的数据目录。 */}
            <StorageCleanupSection />
          </>
        )}
      </div>
    </div>
  );
}
