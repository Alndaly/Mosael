"use client";

import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";

import { GithubMark, GoogleMark } from "@/components/icons";
import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { cloudAccount } from "@/lib/cloud";
import {
  enabledOAuthProviders,
  oauthStartUrl,
  type OAuthProviderName,
  type OAuthReturnPage,
} from "@/lib/oauth";

/**
 * 登录 / 注册页的第三方入口:一颗 GitHub、一颗 Google。
 *
 * 不另立一套皮肤:外框就是站里的 `Button variant="outline"`,高度、圆角、聚焦环和账号表单
 * 的主按钮同一档。按钮是原生 `<a>`(经 `Button asChild`),所以键盘、回车、右键新窗口都和
 * 普通链接一样,不需要给点击补键盘处理。
 *
 * 可用性只认 `/oauth/providers`:**没配置的那一颗不出现**,不只是禁用;请求失败也按没配置
 * 处理。点击后先切到"正在前往…"并置 `aria-busy`,随后同源 GET 交给 Cloud 302。
 */
export function OAuthButtons({
  locale,
  copy,
  from,
}: {
  locale: Locale;
  copy: Messages["account"];
  from: OAuthReturnPage;
}) {
  const [providers, setProviders] = useState<OAuthProviderName[] | null>(null);
  const [pending, setPending] = useState<OAuthProviderName | null>(null);

  useEffect(() => {
    let alive = true;
    cloudAccount
      .oauthProviders()
      .then((body) => {
        if (alive) setProviders(enabledOAuthProviders(body));
      })
      .catch(() => {
        // 问不到就当作没启用:不画一个点下去只会报错的按钮。
        if (alive) setProviders([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 未配置 / 还在确认 / 请求失败:三种情况都不渲染,连分隔线也不占位。
  if (!providers || providers.length === 0) return null;

  return (
    <div className="grid gap-4">
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-border" aria-hidden />
        <span className="text-[12px] font-medium text-muted-foreground">{copy.oauthOr}</span>
        <span className="h-px flex-1 bg-border" aria-hidden />
      </div>
      <div className={providers.length > 1 ? "grid gap-2.5 sm:grid-cols-2" : "grid gap-2.5"}>
        {providers.map((provider) => {
          const busy = pending === provider;
          const label = provider === "github" ? copy.oauthGithub : copy.oauthGoogle;
          return (
            <Button
              key={provider}
              asChild
              variant="outline"
              aria-busy={busy}
              onClick={() => setPending(provider)}
              className="h-12 w-full rounded-full px-4 text-[14px] font-semibold focus-visible:border-ring focus-visible:ring-4 focus-visible:ring-ring/30"
            >
              <a href={oauthStartUrl(provider, locale, from)} aria-label={label}>
                {busy ? (
                  <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
                ) : provider === "github" ? (
                  <GithubMark className="size-4" />
                ) : (
                  <GoogleMark className="size-4" />
                )}
                <span>{busy ? copy.oauthRedirecting : label}</span>
              </a>
            </Button>
          );
        })}
      </div>
    </div>
  );
}
