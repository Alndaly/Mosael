import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Syne } from "next/font/google";
import { notFound } from "next/navigation";

// 思源黑体(可变字重)。**不能走 next/font/google** —— 它给 Noto Sans SC 只认 latin 子集,
// 下载下来的字体文件里没有汉字字形,中文会一路掉到系统默认,在 macOS 上落成宋体:
// 一个走硬边和重黑体的版面配上宋体,按钮里的两个字立刻像是另一个网站的。
// fontsource 这份把字体按 unicode-range 切成了上百片,浏览器只取真正用到的那几片。
import "@fontsource-variable/noto-sans-sc";
import "../globals.css";
import { SiteFooter } from "@/components/site-footer";
import { NavProgress } from "@/components/nav-progress";
import { SiteHeader } from "@/components/site-header";
import { ThemeProvider } from "@/components/theme-provider";
import { HTML_LANG, LOCALES, isLocale, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";

/**
 * 字体。
 *
 * **Syne 做标题**:几何、宽、字腔紧,字重拉到 800 之后是一张海报的骨架 —— 这个站走的是
 * 撞色和硬边,配一款循规蹈矩的 grotesk 会把那股劲卸掉一半。
 *
 * **思源黑体(可变)承担中文**。拉丁和汉字按 font-family 顺序自然分工:Syne 没有汉字字形,
 * 中文落到下一顺位,于是同一行里两种字重能对上。全站不用衬线体 —— 宋体的笔锋在大字号的
 * 实色块上会被压扁,也和硬边的调子不搭。
 */
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
 * 这一层就是**根布局** —— `app/` 下没有第二个 layout。`<html lang>` 必须跟着语言变,
 * 而真正的根布局拿不到 `[locale]` 参数;于是全站路由都住在 `[locale]` 段下,
 * `/` 由 next.config 的 redirects 收口。
 */
export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

/**
 * 视口。**必须显式写**:少了这一条,手机浏览器会按 980px 的假想桌面宽度排版再整体缩小,
 * 于是正文小到看不清、而所有断点都当自己在宽屏上 —— 移动端等于没有适配。
 *
 * 不锁 `maximumScale`:那会连双指放大都禁掉,对看不清小字的人是硬伤。
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale);
  return {
    metadataBase: new URL(SITE.url),
    title: t.meta.title,
    description: t.meta.description,
    icons: {
      icon: [
        { url: "/brand/mosael-icon-light.png", media: "(prefers-color-scheme: light)" },
        { url: "/brand/mosael-icon-dark.png", media: "(prefers-color-scheme: dark)" },
      ],
      apple: "/brand/mosael-icon-light.png",
    },
    // hreflang:两个语言版本互相指认,搜索引擎才不会把它们当重复内容处理。
    alternates: {
      canonical: `/${locale}`,
      languages: Object.fromEntries(LOCALES.map((item) => [HTML_LANG[item], `/${item}`])),
    },
    openGraph: {
      type: "website",
      siteName: "Mosael",
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
      <body className={`${syne.variable} ${geist.variable} ${geistMono.variable} antialiased`}>
        <ThemeProvider>
          {/* 键盘用户第一个 Tab 落在这里,不必一路 Tab 穿过整条导航。 */}
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-100 focus:border-2 focus:border-ink focus:bg-flame focus:px-4 focus:py-2 focus:font-medium focus:text-primary-foreground"
          >
            {t.nav.skipToContent}
          </a>
          <NavProgress />
          <SiteHeader locale={current} />
          {/* 站头固定悬浮。内页保留呼吸位；首页自己以负 margin 把品牌渐变延伸到站头背后。 */}
          <main id="main" className="pt-20">{children}</main>
          <SiteFooter locale={current} />
        </ThemeProvider>
      </body>
    </html>
  );
}
