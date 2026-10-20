import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CommunityHeader } from "@/components/community/community-header";
import { CommunityLanding } from "@/components/community/landing";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { listPlugins, listWorkflows } from "@/lib/registry";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).community;
  return pageMetadata({
    locale,
    path: "/community",
    title: t.homeSeoTitle,
    description: t.homeSeoDescription,
    keywords: t.homeKeywords,
  });
}

/**
 * 保持按请求渲染:构建页数不变(135),分享在浏览器里按当前语言各取一次。
 * 这页本身没有服务端取数 —— 官方内容来自构建期读好的 registry,用户分享由落地页组件取。
 */
export const dynamic = "force-dynamic";

/**
 * 社区首页(落地页)。
 *
 * **两组,不是一张混排列表**:
 *
 * - 插件:官方静态卡片(权限 / 工具 / 安装,来自 `lib/registry`)+ 当前语言的插件分享;
 * - 工作流:官方静态卡片(节点数 / 阶段)+ 当前语言的工作流分享。
 *
 * 每组都是「官方在前、分享在后」,合并 / 去重 / 取数规则和 `/plugins`、`/workflows`
 * 共用同一份 `listed-shares.ts`。**搜索、排序、翻页不在这页** —— 它们留在各自的市场页,
 * 这里的「查看全部」直接过去。
 *
 * 「去上传」只出现一次,在页头。这里没有空态:某组没有分享时照常只有官方卡片,
 * 云端不可达时也只少掉分享那几张(取数失败被吞成空数组,页面上没有错误块)。
 */
export default async function CommunityPage({ params }: { params: Params }) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const t = getMessages(locale).community;
  // 列表来自仓库里真的能装的 manifest / 模板,不是另抄的一份(见 lib/registry)。
  const plugins = listPlugins(locale);
  const workflows = listWorkflows(locale);

  return (
    <>
      <CommunityHeader
        locale={locale}
        counts={{ plugins: plugins.length, workflows: workflows.length }}
        title={t.homeTitle}
        lede={t.homeLede}
        // 整页只有这一个上传入口(两组之间、空态都不再放第二个)。
        contribute={{ label: t.uploadCta, href: localePath(locale, "/community/upload") }}
      />
      <section className="bg-paper">
        <div className="mx-auto max-w-[76rem] px-5 py-10 sm:px-8 sm:pb-24">
          <CommunityLanding locale={locale} plugins={plugins} workflows={workflows} />
        </div>
      </section>
    </>
  );
}
