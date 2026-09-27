import { ShieldAlert, ShieldCheck } from "lucide-react";

import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

/** 三种声明(和人物资产的授权声明同一组值,后端 entities.catalog.CONSENT_KINDS)。说法是嗓子的,不是肖像的。 */
const KINDS: { kind: string; label: MessageKey; help: MessageKey }[] = [
  { kind: "self", label: "voiceConsentSelf", help: "voiceConsentSelfHelp" },
  { kind: "authorized", label: "voiceConsentAuthorized", help: "voiceConsentAuthorizedHelp" },
  { kind: "fictional", label: "voiceConsentFictional", help: "voiceConsentFictionalHelp" },
];

/**
 * 克隆音色的授权声明(ADR 0028 §5,数字人方案「合规」):这把嗓子是谁的 —— 本人、已取得本人单独同意、虚构(AI 生成或原创)。
 *
 * 建克隆音色时**必须选一项**;升级前建的音色是「未声明」,用于数字人(让它说话、对口型)之前要补上。取值和人物资产的
 * 授权声明同一组(后端 entities.catalog.CONSENT_KINDS);说明写的是嗓子 —— 那边说的是肖像,照搬过来就答非所问。
 */
export function VoiceConsentPicker({
  name,
  value,
  onChange,
  disabled,
}: {
  /** 同一页上可能有好几组(每个音色一组),单选按钮要各自成组。 */
  name: string;
  value: string;
  onChange: (kind: string) => void;
  disabled?: boolean;
}) {
  const t = useI18n();
  return (
    <div role="radiogroup" aria-label={t("voiceConsentTitle")} className="grid gap-1.5" data-voice-consent="">
      {KINDS.map((one) => (
        <label
          key={one.kind}
          className={cn(
            "grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] gap-x-2 rounded-md border px-3 py-2",
            value === one.kind ? "border-primary bg-accent" : "border-border",
            disabled && "cursor-not-allowed opacity-60",
          )}
        >
          <input
            type="radio"
            name={name}
            className="mt-0.5"
            checked={value === one.kind}
            disabled={disabled}
            onChange={() => onChange(one.kind)}
          />
          <span className="text-ui-sm font-medium">{t(one.label)}</span>
          <span className="col-start-2 text-ui-xs leading-relaxed text-muted-foreground">{t(one.help)}</span>
        </label>
      ))}
    </div>
  );
}

/** 一行状态:能不能用于数字人,以及声明的时间。 */
export function VoiceConsentStatus({ kind, declaredAt }: { kind: string; declaredAt?: string | null }) {
  const t = useI18n();
  const declared = kind !== "undeclared";
  return (
    <p className={cn("m-0 flex items-center gap-1.5 text-ui-xs", declared ? "text-muted-foreground" : "text-warning")}>
      {declared ? <ShieldCheck size={13} /> : <ShieldAlert size={13} />}
      {t(declared ? "voiceConsentOk" : "voiceConsentMissing")}
      {declared && declaredAt ? ` · ${t("entityConsentDeclaredAt").replace("{at}", declaredAt.slice(0, 10))}` : ""}
    </p>
  );
}
