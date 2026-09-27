import { notFound } from "next/navigation";
import { connection } from "next/server";

import { CommunityDown, CommunityUnavailable, PageShell } from "@/components/community/shell";
import { SubmitForm } from "@/components/community/submit-form";
import { isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS } from "@/lib/community/endpoints";
import { communityEnabled, serverGet } from "@/lib/community/server";
import type { ItemKind, ItemSummary } from "@/lib/community/types";

/**
 * 四个提交页(工作流 / 插件 × 新条目 / 新版本)共用的服务端外壳。登录与否在浏览器里判断
 * (令牌只在内存里),这里只管社区开没开、新版本的那个条目在不在。
 */
export async function SubmitPage({ params, kind }: { params: Promise<{ locale: string; slug?: string }>; kind: ItemKind }) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);

  if (!slug) {
    return (
      <PageShell
        eyebrow={t.community.name}
        title={kind === "workflow" ? t.submit.workflowTitle : t.submit.pluginTitle}
        lede={kind === "workflow" ? t.submit.workflowLede : t.submit.pluginLede}
        narrow
      >
        <SubmitForm locale={locale} kind={kind} />
      </PageShell>
    );
  }

  const item = await serverGet<ItemSummary>(ENDPOINTS.items.detail(kind, slug), locale);
  if (!item.ok && item.error.status === 404) notFound();
  return (
    <PageShell eyebrow={item.ok ? item.data.title : t.community.name} title={t.submit.versionTitle} lede={t.submit.versionLede} narrow>
      {item.ok ? (
        <SubmitForm locale={locale} kind={kind} version={{ slug, title: item.data.title }} />
      ) : (
        <CommunityDown locale={locale} message={item.error.message} />
      )}
    </PageShell>
  );
}
