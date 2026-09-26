import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";

/**
 * 插件工具旁的「需确认」:智能体调它之前会先开一张确认卡。
 *
 * 判据是后端算好的 `effects`(backend domain/effects:none / paid / external / local-code)——
 * 这里不再推一遍「只读就不用问」,只把 none 以外的标出来,悬停说清是哪一种后果。
 * 空串(老市场索引里没有这一项)不标:不知道就不说,而不是猜一个。
 */
const WHY: Record<string, MessageKey> = {
  paid: "pluginToolEffectPaid",
  external: "pluginToolEffectExternal",
  "local-code": "pluginToolEffectLocalCode",
};

export function ToolEffectBadge({ effects }: { effects?: string | null }) {
  const t = useI18n();
  if (!effects || effects === "none") return null;
  // 不认识的取值按「对外」说 —— 和后端同一个保守方向(needs_card 对不认识的也要问)。
  const why = t(WHY[effects] ?? "pluginToolEffectExternal");
  return (
    <small
      className="whitespace-nowrap rounded-full bg-warning/15 px-1.5 py-px text-ui-2xs text-warning"
      title={why}
      aria-label={`${t("pluginToolNeedsConfirm")}: ${why}`}
    >
      {t("pluginToolNeedsConfirm")}
    </small>
  );
}
