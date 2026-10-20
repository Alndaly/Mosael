"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import { cloudAccount } from "@/lib/cloud";

/**
 * 站头的账号入口。未登录时显示「登录」,登录后显示「账号」(邮箱和退出在账号页里)。
 *
 * 未登录那颗是**次级按钮**:复用账号页那颗 `Button variant="outline"`,描边 + 次要文字色,
 * 与「下载」的实心主色隔开一级 —— 它在站头里紧贴「下载」左侧,是这一簇里唯一的次级按钮。
 * 已登录的「账号」保持原来的文字链接,不跟着换皮肤(账号不是主行动,也不该更像按钮)。
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
  if (signedIn) {
    return (
      <Link
        href={`/${locale}/account`}
        className="hidden min-h-9 items-center rounded-full px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground sm:inline-flex"
      >
        {accountLabel}
      </Link>
    );
  }
  return (
    <Button
      asChild
      variant="outline"
      size="lg"
      className="hidden rounded-full border-border bg-transparent px-4 text-muted-foreground hover:bg-secondary hover:text-foreground sm:inline-flex"
    >
      <Link href={`/${locale}/login`}>{loginLabel}</Link>
    </Button>
  );
}
