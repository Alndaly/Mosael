import type { ReactNode } from "react";

/** 注册 / 登录 / 账号三页共用的版式:一张窄卡片,和站内其它内页一样用暖白 + 墨色 + 细边框。 */
export function AccountShell({
  title,
  lede,
  children,
}: {
  title: string;
  lede: string;
  children: ReactNode;
}) {
  return (
    <section className="bg-paper">
      <div className="mx-auto max-w-[38rem] px-5 pt-8 pb-24 sm:px-8">
        <div className="rounded-3xl border border-border bg-background p-6 sm:p-10">
          <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
          <p className="mt-4 text-sm leading-7 text-muted-foreground">{lede}</p>
          <div className="mt-8">{children}</div>
        </div>
      </div>
    </section>
  );
}
