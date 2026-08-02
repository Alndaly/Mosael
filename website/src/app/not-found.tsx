import { Geist, Geist_Mono, Syne } from "next/font/google";

import "@fontsource-variable/noto-sans-sc";
import "./globals.css";
import { DEFAULT_LOCALE, HTML_LANG, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

const syne = Syne({
  variable: "--font-display-latin",
  subsets: ["latin"],
  weight: ["600", "700", "800"],
});
const geist = Geist({ variable: "--font-body-latin", subsets: ["latin"] });
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

/**
 * 落在所有路由之外的 404 —— `/fr`、`/dosc` 这种。
 *
 * 这时候连 `[locale]/layout.tsx` 都没进去(那一层才是根布局,见它自己的说明),Next 会给
 * 这一页配一个默认的 html/body 外壳,所以字体变量和 globals.css 得在这里自己引一遍。
 *
 * 语言只能退到默认值:URL 本身就已经不成立,从里面猜语言没有意义。
 */
export default function RootNotFound() {
  const t = getMessages(DEFAULT_LOCALE).notFound;

  return (
    <div
      lang={HTML_LANG[DEFAULT_LOCALE]}
      className={`${syne.variable} ${geist.variable} ${geistMono.variable} bg-paper text-foreground antialiased`}
    >
      <main className="mx-auto flex min-h-svh max-w-[96rem] flex-col items-start justify-center px-5 sm:px-8">
        <p className="m-0 font-mono text-sm font-bold tracking-widest text-flame uppercase">404</p>
        <h1 className="mt-6 mb-5 font-display text-[clamp(2rem,7vw,4.5rem)] leading-none font-extrabold tracking-[-0.03em]">
          {t.title}
        </h1>
        <p className="mt-0 mb-10 max-w-xl text-lg text-muted-foreground">{t.body}</p>
        <a
          href={localePath(DEFAULT_LOCALE)}
          className="border-2 border-ink bg-flame px-6 py-3 font-bold text-primary-foreground shadow-block transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-none"
        >
          {t.back}
        </a>
      </main>
    </div>
  );
}
