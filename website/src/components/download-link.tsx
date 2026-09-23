"use client";

/**
 * 下载入口:国内走百度网盘,其余走 GitHub Releases(判据见 lib/download-channel)。
 *
 * 首屏(服务端渲染)只知道页面语言,先按语言给一个默认值;挂上之后再看访客自己选过没有、
 * 没选过就按时区判。一页上的几个入口(顶栏、首页按钮、页脚、下载页的卡片)共享同一个选择 ——
 * 在下载页切过去之后,顶栏那颗按钮也跟着变。
 */
import { Check, Download } from "lucide-react";
import * as React from "react";

import { getMessages } from "@/i18n/messages";
import type { Locale } from "@/i18n/config";
import {
  type Channel,
  channelHref,
  chinaAvailable,
  defaultChannel,
  detectChannel,
  STORAGE_KEY,
  storedChannel,
} from "@/lib/download-channel";
import { SITE } from "@/lib/site";
import { cn } from "@/lib/utils";

const listeners = new Set<(channel: Channel) => void>();

function initialChoice(): Channel {
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // 隐私模式、禁用存储:当没选过。
  }
  return (
    storedChannel(stored, SITE.baiduPan) ??
    detectChannel(
      { timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone, languages: navigator.languages },
      SITE.baiduPan,
    )
  );
}

export function useDownloadChannel(locale: Locale): [Channel, (next: Channel) => void] {
  const [channel, setChannel] = React.useState<Channel>(() => defaultChannel(locale, SITE.baiduPan));
  React.useEffect(() => {
    setChannel(initialChoice());
    listeners.add(setChannel);
    return () => {
      listeners.delete(setChannel);
    };
  }, []);
  const choose = React.useCallback((next: Channel) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // 存不下就只在这一页生效。
    }
    listeners.forEach((notify) => notify(next));
  }, []);
  return [channel, choose];
}

/** 顶栏、首页、页脚那几颗「下载」:样式由调用方给,这里只管链接指向哪条路。 */
export function DownloadLink({
  locale,
  className,
  children,
}: {
  locale: Locale;
  className?: string;
  children: React.ReactNode;
}) {
  const [channel] = useDownloadChannel(locale);
  return (
    <a href={channelHref(channel, SITE.baiduPan, SITE.releases)} target="_blank" rel="noreferrer" className={className}>
      {children}
    </a>
  );
}

/** 下载页上的两条路,并排给出;推荐的那条标出来,另一条一样能点。 */
export function DownloadChoice({ locale }: { locale: Locale }) {
  const t = getMessages(locale).downloadChannel;
  const [channel, choose] = useDownloadChannel(locale);
  const options: Array<{ id: Channel; title: string; via: string; body: string; href: string; code?: string }> = [];
  if (chinaAvailable(SITE.baiduPan)) {
    options.push({
      id: "china", title: t.china, via: t.chinaVia, body: t.chinaBody,
      href: SITE.baiduPan.url, code: SITE.baiduPan.code || undefined,
    });
  }
  options.push({ id: "global", title: t.global, via: t.globalVia, body: t.globalBody, href: SITE.releases });

  return (
    <div className="not-prose my-7 font-sans">
      <div className={cn("grid gap-3", options.length > 1 && "sm:grid-cols-2")}>
        {options.map((option) => {
          const active = options.length === 1 || option.id === channel;
          return (
            <div
              key={option.id}
              className={cn(
                "flex flex-col gap-3 rounded-2xl border p-5 transition-colors",
                active ? "border-primary/60 bg-primary/5" : "border-border bg-muted/30",
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="m-0 text-base font-semibold">{option.title}</p>
                  <p className="m-0 mt-0.5 text-sm text-muted-foreground">{option.via}</p>
                </div>
                {active && options.length > 1 && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-primary/12 px-2 py-0.5 text-xs font-medium text-primary">
                    <Check className="size-3" aria-hidden />
                    {t.recommended}
                  </span>
                )}
              </div>
              <p className="m-0 text-sm leading-relaxed text-muted-foreground">{option.body}</p>
              {option.code && (
                <p className="m-0 text-sm">
                  {t.code}:<code className="rounded bg-muted px-1.5 py-0.5 font-mono tabular-nums">{option.code}</code>
                </p>
              )}
              <a
                href={option.href}
                target="_blank"
                rel="noreferrer"
                onClick={() => choose(option.id)}
                className={cn(
                  "mt-auto inline-flex min-h-10 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                  active ? "bg-primary text-primary-foreground hover:bg-primary/88" : "border border-border hover:bg-secondary",
                )}
              >
                <Download className="size-4" aria-hidden />
                {option.title}
              </a>
            </div>
          );
        })}
      </div>
      {options.length > 1 && <p className="m-0 mt-3 text-xs text-muted-foreground">{t.switchHint}</p>}
    </div>
  );
}
