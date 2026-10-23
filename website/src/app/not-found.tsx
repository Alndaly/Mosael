
import "@fontsource-variable/noto-sans-sc";
import "@fontsource-variable/syne";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./globals.css";
import { DEFAULT_LOCALE, HTML_LANG, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

//: 字体**随包发**(`@fontsource-variable/{syne,geist,geist-mono}`):`next/font/google` 在构建时要去
//: Google 取文件,CI 没网络就整页构建失败(2026-10-24)。这三行 import 只注册 @font-face。

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
      className={` bg-paper text-foreground antialiased`}
    >
      <main className="mx-auto flex min-h-svh max-w-[96rem] flex-col items-start justify-center px-5 sm:px-8">
        <p className="m-0 font-mono text-sm font-bold tracking-widest text-flame uppercase">404</p>
        <h1 className="mt-6 mb-5 font-display text-[clamp(2rem,7vw,4.5rem)] leading-none font-extrabold tracking-[-0.03em]">
          {t.title}
        </h1>
        <p className="mt-0 mb-10 max-w-xl text-lg text-muted-foreground">{t.body}</p>
        <a
          href={localePath(DEFAULT_LOCALE)}
          className="border border-border bg-flame px-6 py-3 font-bold text-primary-foreground shadow-block transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-none"
        >
          {t.back}
        </a>
      </main>
    </div>
  );
}
