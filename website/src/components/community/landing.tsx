"use client";

/**
 * 社区首页(落地页):三段,插件 / 工作流 / 创意画板。
 *
 * 前两段都是「官方静态卡片在前,当前语言的用户分享在后」,和 `/plugins`、`/workflows` 用
 * **同一份规则**:
 *
 * - 取数:`fetchListedShares`(经 `useListedShares`)按 `kind` 各取一次,请求里带当前语言;
 * - 合并:`listedShares` 跳过命中静态 slug 的官方分享(否则同一件东西画两张),再按新→旧排;
 * - 排序:`mergeListing` 把官方卡片全部放在分享卡片之前。
 *
 * 第三段「创意画板」只有用户分享:官方内容里没有 board,所以没有静态卡片、没有合并,
 * 一条画布分享都没有时整段不渲染(不画空块)。
 *
 * 这里**没有搜索 / 排序 / 分页**,也没有空态和错误块:搜索、筛选在各自的市场页
 * (「查看全部」过去);某组没有分享就只显示官方卡片,云端不可达时分享为空 —— 官方内容
 * 不该因为社区服务挂了而消失,页面上也不出现红色错误块。
 */
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { PluginCard, useListedShares, WorkflowCard } from "@/components/community/browse";
import { listedShares, mergeListing } from "@/components/community/listed-shares";
import { ShareCard } from "@/components/community/shares";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import type { PluginEntry, WorkflowEntry } from "@/lib/registry";

const GRID = "m-0 grid list-none grid-cols-[minmax(0,1fr)] gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3";

/** 一组的小标题 + 「查看全部」。链接直接指到那一组自己的市场页,搜索 / 筛选在那儿。 */
function GroupHeader({
  id,
  title,
  label,
  href,
}: {
  id: string;
  title: string;
  label: string;
  href: string;
}) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-border pb-3">
      <h2 id={id} className="m-0 font-display text-2xl font-bold tracking-tight">
        {title}
      </h2>
      <Link
        href={href}
        className="inline-flex items-center gap-1.5 rounded-full text-sm font-semibold text-primary transition-colors hover:text-primary/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        {label}
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </div>
  );
}

function PluginGroup({ locale, plugins }: { locale: Locale; plugins: PluginEntry[] }) {
  const t = getMessages(locale);
  const shares = useListedShares("plugin", locale);
  // 先按**全部**静态官方 slug 去重,再合并 —— 规则与 /plugins 完全一致。
  const officialSlugs = plugins.map((plugin) => plugin.slug);
  const items = mergeListing(plugins, listedShares(shares, officialSlugs));
  // 某组一条都没有(官方是静态的,理论上不会):不画空块,整组不出现。
  if (items.length === 0) return null;
  return (
    <section className="grid gap-4" aria-labelledby="community-plugins">
      <GroupHeader
        id="community-plugins"
        title={t.plugins.title}
        label={t.community.viewAll}
        href={localePath(locale, "/plugins")}
      />
      <ul className={GRID}>
        {items.map((entry) => (
          <li
            key={entry.kind === "official" ? `plugin-${entry.official.slug}` : `share-${entry.share.id}`}
            className="grid"
          >
            {entry.kind === "official" ? (
              <PluginCard locale={locale} plugin={entry.official} />
            ) : (
              <ShareCard locale={locale} share={entry.share} />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function WorkflowGroup({ locale, workflows }: { locale: Locale; workflows: WorkflowEntry[] }) {
  const t = getMessages(locale);
  const shares = useListedShares("workflow", locale);
  const officialSlugs = workflows.map((workflow) => workflow.slug);
  const items = mergeListing(workflows, listedShares(shares, officialSlugs));
  if (items.length === 0) return null;
  return (
    <section className="grid gap-4" aria-labelledby="community-workflows">
      <GroupHeader
        id="community-workflows"
        title={t.workflows.title}
        label={t.community.viewAll}
        href={localePath(locale, "/workflows")}
      />
      <ul className={GRID}>
        {items.map((entry) => (
          <li
            key={entry.kind === "official" ? `workflow-${entry.official.slug}` : `share-${entry.share.id}`}
            className="grid"
          >
            {entry.kind === "official" ? (
              <WorkflowCard locale={locale} workflow={entry.official} />
            ) : (
              <ShareCard locale={locale} share={entry.share} />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * 第三组:创意画板。**只**来自用户分享 —— 官方内容里没有 board,所以这里没有官方静态
 * 卡片,也不走 `mergeListing`。一条分享都没有时整组不出现,和另外两组的规则一致。
 */
function BoardGroup({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const fetched = useListedShares("board", locale);
  // 和另外两组同一份排序规则(新→旧);画布没有官方 slug 要去重,所以官方集合是空的。
  const shares = listedShares(fetched, []);
  // 画布没有官方兜底内容:空组没有任何东西可画,整段不渲染。
  if (shares.length === 0) return null;
  return (
    <section className="grid gap-4" aria-labelledby="community-boards">
      <GroupHeader
        id="community-boards"
        title={t.boards.title}
        label={t.community.viewAll}
        href={localePath(locale, "/boards")}
      />
      <ul className={GRID}>
        {shares.map((share) => (
          <li key={`share-${share.id}`} className="grid">
            <ShareCard locale={locale} share={share} />
          </li>
        ))}
      </ul>
    </section>
  );
}

export function CommunityLanding({
  locale,
  plugins,
  workflows,
}: {
  locale: Locale;
  plugins: PluginEntry[];
  workflows: WorkflowEntry[];
}) {
  return (
    <div className="grid gap-12">
      <PluginGroup locale={locale} plugins={plugins} />
      <WorkflowGroup locale={locale} workflows={workflows} />
      <BoardGroup locale={locale} />
    </div>
  );
}
