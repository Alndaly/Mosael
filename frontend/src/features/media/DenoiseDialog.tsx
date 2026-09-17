import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { denoiseAsset, listDenoiseEngines, type DenoiseStrength } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { gotoJob } from "@/lib/deepLink";
import { cn } from "@/lib/utils";

const STRENGTH_LABELS: Record<DenoiseStrength, MessageKey> = {
  light: "denoiseStrengthLight",
  medium: "denoiseStrengthMedium",
  strong: "denoiseStrengthStrong",
};

/**
 * 给一份素材降噪(ADR-0017)。素材库的两个菜单、剪辑台片段的右键菜单共用这一个。
 *
 * 选的只有两件事:**下手多重**、**用哪种方式**。引擎清单来自后端注册表 —— 这里不认识任何
 * 引擎名,只读每个引擎自己说的「有没有档位」「会不会去掉音乐」「现在能不能用」。
 */
export function DenoiseDialog({ assetId, onClose }: { assetId: string | null; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const open = assetId !== null;
  const engines = useQuery({ queryKey: ["denoise-engines"], queryFn: listDenoiseEngines, enabled: open, staleTime: 30_000 });
  const [engine, setEngine] = React.useState("");
  const [strength, setStrength] = React.useState<DenoiseStrength>("medium");
  // 空 = 内置的那个(后端 auto 挑的就是它)。显示时落到清单里第一个不去音乐的。
  const list = engines.data ?? [];
  const chosen = list.find((one) => one.engine === engine) ?? list.find((one) => !one.removes_music);
  const strengths = (chosen?.strengths ?? []) as DenoiseStrength[];

  React.useEffect(() => {
    if (!open) {
      setEngine("");
      setStrength("medium");
    }
  }, [open]);

  const run = useMutation({
    mutationFn: () => denoiseAsset(assetId as string, { engine: chosen?.engine ?? "", strength }),
    onSuccess: (job) => {
      void qc.invalidateQueries({ queryKey: ["jobs"] });
      toast.success(t("denoiseQueued"), { action: { label: t("denoiseViewTask"), onClick: () => gotoJob(job.id) } });
      onClose();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={t("denoiseTitle")}
      className="sm:max-w-md"
      footer={
        <>
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={!chosen?.ready} loading={run.isPending} onClick={() => run.mutate()}>
            {t("denoiseStart")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5">
        <div className="grid gap-2" role="radiogroup" aria-label={t("denoiseMethod")}>
          <span className="text-ui-sm font-medium">{t("denoiseMethod")}</span>
          {list.map((one) => {
            const selected = one.engine === chosen?.engine;
            return (
              <button
                key={one.engine}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={!one.ready}
                onClick={() => setEngine(one.engine)}
                className={cn(
                  "grid gap-0.5 rounded-md border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                  selected ? "border-primary bg-[color-mix(in_oklab,var(--primary)_8%,transparent)]" : "border-border hover:bg-secondary",
                )}
              >
                <span className="text-ui-sm font-medium">{one.label}</span>
                {/* 会去掉音乐的那种**必须说出来** —— 用户说"降噪"时没想把配乐也拿掉。 */}
                <span className="text-ui-xs leading-[1.45] text-muted-foreground">
                  {!one.ready
                    ? t("denoiseEngineUnready")
                    : one.removes_music
                      ? t("denoiseRemovesMusic")
                      : t("denoiseKeepsMusic")}
                </span>
              </button>
            );
          })}
        </div>
        {/* 没有档位的方式(人声提取)不摆这个旋钮 —— 拨了也没用。 */}
        {strengths.length > 0 && (
          <div className="grid gap-2">
            <span className="text-ui-sm font-medium">{t("denoiseStrength")}</span>
            <div className={SEGMENTED_LIST} role="radiogroup" aria-label={t("denoiseStrength")}>
              {strengths.map((one) => (
                <button
                  key={one}
                  type="button"
                  role="radio"
                  aria-checked={strength === one}
                  className={segmentedTriggerClass(strength === one)}
                  onClick={() => setStrength(one)}
                >
                  {t(STRENGTH_LABELS[one])}
                </button>
              ))}
            </div>
            <small className="text-ui-xs leading-[1.45] text-muted-foreground">{t("denoiseStrengthHint")}</small>
          </div>
        )}
        <p className="m-0 text-ui-xs leading-[1.45] text-muted-foreground">{t("denoiseOutputNote")}</p>
      </div>
    </ModalShell>
  );
}
