"use client";

import { useEffect, useRef } from "react";

import { toast } from "sonner";
import type { Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

import type { OAuthOutcome } from "./dashboard-utils";

/**
 * 第三方登录结果的提示。
 *
 * **为什么在控制台**:云端的回调固定回到 `/<locale>/account?oauth=created|existing`
 * (见 `cloud/api/oauth.py`),而 `/account` 现在只是一个永久跳转到控制台的壳子 ——
 * 结果码被透传到这里,由控制台把它说清,不再丢一句「你已登录」。
 *
 * 身份真的建立了才播报:控制台的服务端门禁已经确认会话,未登录根本到不了这一层。
 * `ref` 保证 StrictMode 的重放 / 一次挂载只弹一遍。
 */
export function OAuthOutcomeToast({ locale, outcome }: { locale: Locale; outcome: OAuthOutcome }) {
  const shown = useRef(false);

  useEffect(() => {
    if (!outcome || shown.current) return;
    shown.current = true;
    const copy = getMessages(locale).account;
    toast.success(outcome === "created" ? copy.oauthCreated : copy.oauthExisting);
  }, [locale, outcome]);

  return null;
}
