/**
 * 内页页头。
 *
 * 首页那条纸色带压缩成一条:方格底 + 大标题 + 一句引言,底下是 2px 的墨线。内页和首页
 * 因此是同一个站,而不是三张各画各的页面。标题比首页小一档 —— 内页的主角是内容,不是标题。
 */
export function PageHero({ eyebrow, title, lede }: { eyebrow?: string; title: string; lede: string }) {
  return (
    <section className="border-b-2 border-ink bg-paper bg-rule bg-[size:80px_80px]">
      <div className="mx-auto max-w-[96rem] px-5 pt-16 pb-14 sm:px-8 sm:pt-24">
        {eyebrow && (
          <p className="m-0 mb-6 inline-flex items-center gap-2.5 border-2 border-ink bg-card px-3 py-1.5 font-mono text-xs font-bold tracking-widest uppercase">
            <span className="size-2 bg-flame" />
            {eyebrow}
          </p>
        )}
        <h1 className="mt-0 mb-0 font-display text-[clamp(2.25rem,7vw,5rem)] leading-[0.95] font-extrabold tracking-[-0.03em]">
          {title}
        </h1>
        <p className="mt-8 mb-0 max-w-2xl text-lg text-muted-foreground">{lede}</p>
      </div>
    </section>
  );
}
