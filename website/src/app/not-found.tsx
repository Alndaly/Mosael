import { Geist, Geist_Mono, Noto_Serif_SC } from "next/font/google";

import "./globals.css";
import { DEFAULT_LOCALE, HTML_LANG, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const notoSerifSC = Noto_Serif_SC({ variable: "--font-serif-sc", subsets: ["latin"], weight: ["400", "600"], display: "swap" });

export default function RootNotFound() {
  const t = getMessages(DEFAULT_LOCALE).notFound;
  return (
    <div lang={HTML_LANG[DEFAULT_LOCALE]} className={`${geistSans.variable} ${geistMono.variable} ${notoSerifSC.variable} antialiased bg-background text-foreground`}>
      <main className="prose-cn mx-auto flex min-h-svh max-w-5xl flex-col items-start justify-center px-6 font-serif sm:px-8">
        <p className="m-0 font-sans text-sm tracking-wide text-muted-foreground">404</p>
        <h1 className="mt-4 mb-4 text-3xl font-semibold">{t.title}</h1>
        <p className="mt-0 mb-8 text-muted-foreground">{t.body}</p>
        <a className="font-sans text-sm underline underline-offset-4 hover:no-underline" href={localePath(DEFAULT_LOCALE)}>{t.back}</a>
      </main>
    </div>
  );
}
