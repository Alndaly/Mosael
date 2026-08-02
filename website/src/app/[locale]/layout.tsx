import type { Metadata } from "next";
import { Geist, Geist_Mono, Noto_Serif_SC } from "next/font/google";
import { notFound } from "next/navigation";

import "../globals.css";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { ThemeProvider } from "@/components/theme-provider";
import { HTML_LANG, LOCALES, isLocale, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

/**
 * 中文衬线体。Geist 只有拉丁字形,中文会掉到系统默认(macOS 是苹方,Windows 是微软雅黑)
 * —— 两台机器上看是两个产品,而且黑体在长段落里偏硬。
 *
 * 用衬线体承载中文正文是这个站"文艺"的主要来源:它慢、有笔锋,和一个做视频剪辑的本地
 * 工具的调性对得上。字重只取 400/600 —— 思源宋体全字重加起来几 MB,而官网只需要正文和标题。
 */
const notoSerifSC = Noto_Serif_SC({
  variable: "--font-serif-sc",
  subsets: ["latin"],
  weight: ["400", "600"],
  display: "swap",
});

/**
 * 这一层就是**根布局** —— `app/` 下没有第二个 layout。`<html lang>` 必须跟着语言变,
 * 而真正的根布局拿不到 `[locale]` 参数;于是全站路由都住在 `[locale]` 段下,
 * `/` 由 next.config 的 redirects 收口。
 */
export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale);
  return {
    metadataBase: new URL(SITE.url),
    title: t.meta.title,
    description: t.meta.description,
    // hreflang:两个语言版本互相指认,搜索引擎才不会把它们当重复内容处理。
    alternates: {
      canonical: `/${locale}`,
      languages: Object.fromEntries(LOCALES.map((item) => [HTML_LANG[item], `/${item}`])),
    },
    openGraph: {
      type: "website",
      siteName: "Open Studio",
      title: t.meta.title,
      description: t.meta.description,
      locale: HTML_LANG[locale],
      url: `/${locale}`,
    },
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  // 动态段什么字符串都收得下,`/fr` 不该渲染出一个中文页来。
  if (!isLocale(locale)) notFound();
  const current: Locale = locale;
  const t = getMessages(current);

  return (
    // suppressHydrationWarning:next-themes 会在客户端给 <html> 加 class,不加这个 React 会
    // 抱怨服务端与客户端不一致 —— 而那正是主题切换本来就要做的事。
    <html lang={HTML_LANG[current]} suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} ${notoSerifSC.variable} antialiased`}>
        <ThemeProvider>
          {/* 键盘用户第一个 Tab 落在这里,不必一路 Tab 穿过整条导航。 */}
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-100 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
          >
            {t.nav.skipToContent}
          </a>
          <SiteHeader locale={current} />
          <main id="main">{children}</main>
          <SiteFooter locale={current} />
        </ThemeProvider>
      </body>
    </html>
  );
}
