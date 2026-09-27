import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { LineChart } from "@/components/community/charts";
import { CommunityHeader } from "@/components/community/community-header";
import { CommunityDown, CommunityUnavailable } from "@/components/community/shell";
import { isLocale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS, collection } from "@/lib/community/endpoints";
import { fill, formatCount } from "@/lib/community/format";
import { communityEnabled, serverGet } from "@/lib/community/server";
import { METRICS, type StatsOverview, type Timeseries } from "@/lib/community/types";
import { cn } from "@/lib/utils";

type Props = { params: Promise<{ locale: string }>; searchParams: Promise<{ days?: string | string[] }> };

const RANGES = [30, 90] as const;

export async function generateMetadata({ params }: Pick<Props, "params">): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).stats;
  return { title: `${t.title} · Mosael`, description: t.lede };
}

/** 社区统计(ADR 0026 §7):总数、四条逐日走势、热门条目。图在服务端画成 SVG,不进 JS 包。 */
export default async function StatsPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  await connection();
  if (!communityEnabled()) return <CommunityUnavailable locale={locale} />;
  const t = getMessages(locale);
  const { days: rawDays } = await searchParams;
  const days = RANGES.find((range) => String(range) === rawDays) ?? RANGES[0];

  const [overview, ...series] = await Promise.all([
    serverGet<StatsOverview>(ENDPOINTS.stats.overview, locale),
    ...METRICS.map((metric) => serverGet<Timeseries>(ENDPOINTS.stats.timeseries(metric, days), locale)),
  ]);

  // 热门:工作流、插件、资产各取前几名,合在一起按下载数排。
  const top = overview.ok
    ? [...(overview.data.top_workflows ?? []), ...(overview.data.top_plugins ?? []), ...(overview.data.top_assets ?? [])].sort(
        (a, b) => b.downloads - a.downloads,
      )
    : [];
  const totals = overview.ok
    ? ([
        ["users", overview.data.users],
        ["workflows", overview.data.workflows],
        ["plugins", overview.data.plugins],
        ["assets", overview.data.assets],
        ["shares", overview.data.shares],
        ["downloads", overview.data.downloads],
      ] as const)
    : [];

  return (
    <>
      <CommunityHeader locale={locale} active="stats" title={t.stats.title} lede={t.stats.lede} />
      <section className="bg-paper">
        <div className="mx-auto grid max-w-[76rem] gap-10 px-5 py-10 sm:px-8 sm:pb-24">
          {!overview.ok ? (
            <CommunityDown locale={locale} />
          ) : (
            <>
              <dl className="m-0 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                {totals.map(([key, value]) => (
                  <div key={key} className="grid gap-1 rounded-2xl border border-border bg-card p-5">
                    <dt className="text-xs text-muted-foreground">{t.stats.totals[key]}</dt>
                    <dd className="m-0 font-display text-3xl font-bold tracking-tight tabular-nums">{formatCount(value, locale)}</dd>
                  </div>
                ))}
              </dl>

              <div className="grid gap-4">
                <nav aria-label={t.stats.title} className="flex gap-2">
                  {RANGES.map((range) => (
                    <Link
                      key={range}
                      href={`${localePath(locale, "/community/stats")}${range === RANGES[0] ? "" : `?days=${range}`}`}
                      aria-current={range === days ? "page" : undefined}
                      scroll={false}
                      className={cn(
                        "inline-flex h-9 items-center rounded-full border px-3.5 text-sm font-medium",
                        range === days ? "border-foreground bg-foreground text-background" : "border-border bg-card text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {fill(t.stats.range, { days: range })}
                    </Link>
                  ))}
                </nav>
                <div className="grid gap-4 md:grid-cols-2">
                  {METRICS.map((metric, index) => {
                    const result = series[index];
                    // 服务回的点是 `{date, value}`;图表几何按 `{date, count}` 算。
                    const points = result.ok ? result.data.points.map((point) => ({ date: point.date, count: point.value })) : [];
                    return <LineChart key={metric} locale={locale} days={days} title={t.stats.series[metric]} points={points} />;
                  })}
                </div>
              </div>

              <section className="grid gap-4">
                <h2 className="m-0 border-b border-border pb-3 text-lg font-semibold tracking-tight">{t.stats.top}</h2>
                {top.length > 0 ? (
                  <ol className="m-0 grid list-none gap-0 overflow-hidden rounded-2xl border border-border bg-card p-0">
                    {top.map((item, index) => {
                      const max = top[0].downloads || 1;
                      return (
                        <li key={`${item.kind}-${item.slug}`} className="relative grid grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-3 border-border px-5 py-3 not-last:border-b">
                          {/* 条形在底下垫一层,长度按下载数比例:不另画一张图也看得出差距。 */}
                          <span aria-hidden className="absolute inset-y-0 left-0 bg-primary/6" style={{ width: `${(item.downloads / max) * 100}%` }} />
                          <span className="relative font-mono text-xs text-muted-foreground tabular-nums">{index + 1}</span>
                          <Link
                            href={localePath(locale, `${collection(item.kind)}/${item.slug}`)}
                            className="relative min-w-0 truncate text-sm font-semibold hover:text-primary"
                          >
                            {item.title}
                            <span className="ml-2 text-xs font-normal text-muted-foreground">{t.account.kind[item.kind]}</span>
                          </Link>
                          <span className="relative font-mono text-sm tabular-nums">{formatCount(item.downloads, locale)}</span>
                        </li>
                      );
                    })}
                  </ol>
                ) : (
                  <p className="m-0 text-sm text-muted-foreground">{t.stats.noTop}</p>
                )}
              </section>
            </>
          )}
        </div>
      </section>
    </>
  );
}
