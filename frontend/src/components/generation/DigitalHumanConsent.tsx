import { useI18n } from "@/app/preferences";

/**
 * 数字人(挂了驱动音频的说话照片、对口型)提交前的那一格授权确认(ADR 0028 §5)。
 *
 * 后端的生成漏斗对带驱动音频的请求一律要 `digital_human_consent`,没有就 422 —— 这里只是让人在提交前看见、
 * 自己勾上。**不给默认值**:替他勾上等于替他声明。AI 工作台和画板的生成格共用这一份。
 */
export function DigitalHumanConsent({ checked, onChange }: { checked: boolean; onChange: (next: boolean) => void }) {
  const t = useI18n();
  return (
    <label
      className="grid cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2 gap-y-0.5"
      data-digital-human-consent=""
    >
      <input type="checkbox" className="mt-0.5" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="text-ui-sm font-medium">{t("genDigitalHumanConsent")}</span>
      <span className="col-start-2 text-ui-xs leading-relaxed text-muted-foreground">{t("genDigitalHumanConsentHint")}</span>
    </label>
  );
}
