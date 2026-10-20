"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import type { Locale } from "@/i18n/config";
import { cloudAccount } from "@/lib/cloud";

import { COMMUNITY_RETURN_KEY, isLoginReturnPath } from "./share-utils";

/**
 * 登录后回到刚才那一步。
 *
 * 登录表单成功后固定去 `/account`(那笔在 `components/account` 里,这次不动),所以社区这边
 * 用两段小逻辑把它接回来:
 *   1. 登录页带着 `?next=` 打开时,把目的地存进 sessionStorage(只活在这个标签页);
 *   2. 账号页挂载后确认会话真的建立了,再把用户送回原处(社区页或控制台)。
 *
 * 只接受 `/<locale>/community...` 和 `/<locale>/dashboard...` 两个私有入口 —— `?next=`
 * 不能变成一个开放跳转口子。控制台(「我的」)就是从这儿回来的。
 */
export function RememberLoginReturn({ locale, next }: { locale: Locale; next?: string }) {
  React.useEffect(() => {
    if (!next || !isLoginReturnPath(next, locale)) return;
    try {
      window.sessionStorage.setItem(COMMUNITY_RETURN_KEY, next);
    } catch {
      // 隐私模式 / 存储被禁:回跳失效,但登录本身不受影响。
    }
  }, [locale, next]);
  return null;
}

export function ResumeLoginReturn({ locale }: { locale: Locale }) {
  const router = useRouter();
  React.useEffect(() => {
    let pending: string | null = null;
    try {
      pending = window.sessionStorage.getItem(COMMUNITY_RETURN_KEY);
    } catch {
      return;
    }
    if (!pending || !isLoginReturnPath(pending, locale)) return;

    let alive = true;
    const clear = () => {
      try {
        window.sessionStorage.removeItem(COMMUNITY_RETURN_KEY);
      } catch {
        // 忽略:清不掉也只是下次多跳一次。
      }
    };
    void cloudAccount
      .me()
      .then(() => {
        if (!alive) return;
        clear();
        router.replace(pending);
      })
      .catch(() => {
        // 到了账号页却还没会话(比如会话过期):丢掉过期的目的地,别让它以后突然劫持一次导航。
        clear();
      });
    return () => {
      alive = false;
    };
  }, [locale, router]);
  return null;
}
