"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { Locale } from "@/i18n/config";
import { cloudAccount } from "@/lib/cloud";

/**
 * 站头的账号入口。未登录时只显示「登录」;登录后显示「账号」(邮箱和退出在账号页里)。
 *
 * 它只问云端一句 `/me` —— 不碰本地后端,也不把邮箱塞进站头那一行(窄屏放不下)。
 */
export function AccountNav({
  locale,
  loginLabel,
  accountLabel,
}: {
  locale: Locale;
  loginLabel: string;
  accountLabel: string;
}) {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    void cloudAccount
      .me()
      .then(() => {
        if (alive) setSignedIn(true);
      })
      .catch(() => {
        if (alive) setSignedIn(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (signedIn === null) return null;
  return (
    <Link
      href={`/${locale}/${signedIn ? "account" : "login"}`}
      className="hidden min-h-9 items-center rounded-full px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground sm:inline-flex"
    >
      {signedIn ? accountLabel : loginLabel}
    </Link>
  );
}
