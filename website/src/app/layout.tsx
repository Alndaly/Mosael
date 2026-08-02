import type { Metadata } from "next";
import { Geist, Geist_Mono, Noto_Serif_SC } from "next/font/google";
import "./globals.css";

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

export const metadata: Metadata = {
  title: "Open Studio · 让灵感落进时间线",
  description: "本地优先的 AI 视频工作台。剪辑、字幕、配音、发布 —— 一个工作台完成全部创作。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning:主题切换会在客户端给 <html> 加 class,不加这个 React 会
    // 抱怨服务端与客户端不一致 —— 而那正是主题切换本来就要做的事。
    <html lang="zh-CN" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} ${notoSerifSC.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
