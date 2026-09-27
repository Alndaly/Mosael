import { useQuery } from "@tanstack/react-query";

import { listAssets, type Asset, type GenerationOption } from "@/api/client";
import { assetKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import type { FrameSlot } from "@/features/ai-studio/sourceFrames";

/**
 * 数字人那几条描述符规则在生成页上的样子(ADR 0028 §2):
 *
 * - `duration_follows`:成片长度等于那份素材的长度 —— 模型不收时长,时长那一栏写明「跟着驱动音频」,不留一个
 *   看着能选、其实不起作用的控件;
 * - `truncates_role`:那份素材比所选时长长的部分会被截掉(万相 2.7 的驱动音频)—— 所选时长短于它时提醒截掉几秒,
 *   一键改成按它的长度(夹进模型允许的范围)。
 */
function capabilityRole(model: GenerationOption | null | undefined, key: "duration_follows" | "truncates_role"): string {
  const value = (model?.capabilities as Record<string, unknown> | undefined)?.[key];
  return typeof value === "string" ? value : "";
}

export function durationFollowsRole(model: GenerationOption | null | undefined): string {
  return capabilityRole(model, "duration_follows");
}

/** 「时长跟着驱动音频」—— 放在时长那一栏的位置上。 */
export function DurationFollowsNote({ role }: { role: string }) {
  const t = useI18n();
  return (
    <span data-duration-follows={role} className="text-ui-xs leading-relaxed text-muted-foreground">
      {t("genDurationFollows").replace("{role}", t(`genParam_${role}` as never))}
    </span>
  );
}

/** 所选时长比挂着的那份素材短、而这个模型会截掉多出来的部分时,说截掉几秒,给一个「按它的长度」。 */
export function TruncationHint({
  model,
  workspaceId,
  frames,
  durationSeconds,
  bounds,
  onUseSourceLength,
}: {
  model: GenerationOption | null | undefined;
  workspaceId: string;
  frames: Record<string, FrameSlot[]>;
  durationSeconds: string;
  bounds: { min?: number; max?: number };
  onUseSourceLength: (seconds: number) => void;
}) {
  const t = useI18n();
  const role = capabilityRole(model, "truncates_role");
  const assetId = role ? (frames[role]?.[0]?.assetId ?? "") : "";
  const library = useQuery({
    queryKey: assetKeys.list(workspaceId),
    queryFn: () => listAssets(workspaceId),
    enabled: Boolean(assetId),
  });
  const asset = (library.data ?? []).find((one: Asset) => one.id === assetId);
  const sourceSeconds = Number((asset?.media_info as { duration?: number } | undefined)?.duration ?? 0);
  const chosen = Number(durationSeconds);
  if (!role || !assetId || !(sourceSeconds > 0) || !(chosen > 0) || sourceSeconds <= chosen) return null;
  const whole = Math.ceil(sourceSeconds);
  const fitted = Math.min(bounds.max ?? whole, Math.max(bounds.min ?? 1, whole));
  const label = t(`genParam_${role}` as never);
  return (
    <div role="status" data-truncation-hint="" className="flex flex-wrap items-center gap-2 text-ui-xs text-warning">
      <span className="min-w-0 flex-1">
        {t("genDurationTruncates")
          .replace("{role}", label)
          .replace("{source}", String(Math.round(sourceSeconds * 10) / 10))
          .replace("{cut}", String(Math.round((sourceSeconds - chosen) * 10) / 10))}
      </span>
      {fitted !== chosen && (
        <Button type="button" size="sm" variant="outline" onClick={() => onUseSourceLength(fitted)}>
          {t("genDurationUseSource").replace("{seconds}", String(fitted))}
        </Button>
      )}
    </div>
  );
}
