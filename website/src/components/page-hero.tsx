/**
 * 内页页头。
 *
 * 内页共享的开放式页头。大面积留白和渐变字承接首页品牌，不再用外框把每一页切成卡片。
 */
export function PageHero({ eyebrow, title, lede }: { eyebrow?: string; title: string; lede: string }) {
  return (
    <section className="relative isolate -mt-20 overflow-hidden bg-paper">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_12%_18%,rgba(114,87,233,0.16),transparent_32%),radial-gradient(circle_at_88%_0%,rgba(255,139,120,0.14),transparent_28%)] dark:bg-[radial-gradient(circle_at_12%_18%,rgba(114,87,233,0.2),transparent_34%),radial-gradient(circle_at_88%_0%,rgba(255,139,120,0.08),transparent_28%)]" />
      <div className="mx-auto max-w-[88rem] px-5 pt-40 pb-18 sm:px-8 sm:pt-48 sm:pb-24">
        {eyebrow && (
          <p className="m-0 mb-6 inline-flex items-center gap-2.5 font-mono text-xs font-bold tracking-widest text-primary uppercase">
            <span className="size-1.5 rounded-full bg-primary" />
            {eyebrow}
          </p>
        )}
        <h1 className="mt-0 mb-0 max-w-[12ch] bg-gradient-to-r from-foreground via-foreground to-primary bg-clip-text font-display text-[clamp(3.25rem,8vw,7rem)] leading-[0.9] font-[720] tracking-[-0.055em] text-transparent">
          {title}
        </h1>
        <p className="mt-8 mb-0 max-w-2xl text-base leading-8 text-muted-foreground sm:text-lg">{lede}</p>
      </div>
    </section>
  );
}
