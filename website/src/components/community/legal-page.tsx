import { FileText } from "lucide-react";

import { PageShell } from "@/components/community/shell";
import type { Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";

/**
 * 《用户协议》《隐私政策》的占位页。
 *
 * 两份文本由运营者提供(ADR 0026 §2:国内上线要求),服务里只存版本号和同意时间。在运营者给出
 * 正式文本之前,这里**明说它还没有**,而不是放一段看起来像条款的模板 —— 一段没人认领的条款比
 * 没有条款更糟。换成正式文本时,同时改 `NEXT_PUBLIC_COMMUNITY_TERMS_VERSION` 和服务端的版本号。
 */
export function LegalPlaceholder({ locale, kind }: { locale: Locale; kind: "terms" | "privacy" }) {
  const t = getMessages(locale);
  const title = kind === "terms" ? t.legal.termsTitle : t.legal.privacyTitle;
  return (
    <PageShell eyebrow={t.community.name} title={title} narrow>
      <div className="grid gap-4 rounded-2xl border border-dashed border-border px-6 py-10">
        <FileText className="size-6 text-muted-foreground" aria-hidden />
        <p className="m-0 text-sm leading-7 text-muted-foreground">{t.legal.placeholder}</p>
        <p className="m-0 text-sm text-muted-foreground">
          {t.legal.contact}
          <a className="font-semibold text-primary hover:underline" href={SITE.email}>
            {SITE.email.replace(/^mailto:/, "")}
          </a>
        </p>
      </div>
    </PageShell>
  );
}
