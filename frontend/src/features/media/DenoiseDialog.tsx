import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Info } from "lucide-react";
import { toast } from "sonner";

import { denoiseAsset, listDenoiseEngines, type DenoiseStrength } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { gotoJob, gotoSettings } from "@/lib/deepLink";
import { cn } from "@/lib/utils";

//: 分组小标题比选项本身轻一档 —— 和选项同号同色时,「方式」「强度」读起来像又一个选项。
const SECTION_LABEL = "text-ui-xs font-medium text-muted-foreground";

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
      className="sm:max-w-lg"
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
      <div className="grid gap-6">
        <div className="grid gap-2.5">
          <span className={SECTION_LABEL}>{t("denoiseMethod")}</span>
          <div className="grid gap-2" role="radiogroup" aria-label={t("denoiseMethod")}>
            {list.map((one) => {
              const selected = one.engine === chosen?.engine;
              const hintId = `denoise-hint-${one.engine}`;
              const needsSetup = !one.ready && Boolean(one.setup_hint);
              return (
                <div
                  key={one.engine}
                  className={cn(
                    "overflow-hidden rounded-lg border transition-colors",
                    selected ? "border-primary bg-[color-mix(in_oklab,var(--primary)_8%,transparent)]" : "border-border",
                  )}
                >
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    aria-describedby={needsSetup ? hintId : undefined}
                    disabled={!one.ready}
                    onClick={() => setEngine(one.engine)}
                    className="flex w-full cursor-pointer items-start gap-3 px-3.5 py-3 text-left transition-colors enabled:hover:bg-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-not-allowed"
                  >
                    {/* 单选圆点:选中的那一张一眼能认出来,不只靠边框颜色。 */}
                    <span
                      aria-hidden
                      className={cn(
                        "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border",
                        selected ? "border-primary" : "border-muted-foreground/50",
                      )}
                    >
                      {selected && <span className="size-2 rounded-full bg-primary" />}
                    </span>
                    <span className={cn("grid min-w-0 gap-1", !one.ready && "opacity-60")}>
                      <span className="flex flex-wrap items-center gap-2 text-ui-sm font-medium leading-5">
                        {one.label}
                        {/* 会去掉音乐的**单独标出来** —— 用户说"降噪"时没想把配乐也拿掉,而说明文字
                            是会被略读的。 */}
                        {one.removes_music && (
                          <span className="rounded-sm bg-[color-mix(in_oklab,var(--warning)_16%,transparent)] px-1.5 py-px text-ui-2xs font-medium text-foreground">
                            {t("denoiseRemovesMusicBadge")}
                          </span>
                        )}
                      </span>
                      <span className="text-ui-xs leading-[1.5] text-muted-foreground">{one.description}</span>
                    </span>
                  </button>
                  {/* 没准备好时说去哪儿准备 —— 这句话由引擎自己给,这里不认识任何引擎。它接在说明下面、
                      和文字对齐,只是不跟着变灰;不另起一条色带 —— 那样一张卡被切成两截,和别的卡不像一组。
                      放在单选按钮外面,是因为禁用的按钮里不能再套按钮。 */}
                  {needsSetup && (
                    <div className="-mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 pb-3 pl-[2.625rem] pr-3.5 text-ui-xs leading-[1.5]">
                      <span id={hintId} className="text-muted-foreground">
                        {one.setup_hint}
                      </span>
                      {one.installable && (
                        <Button
                          variant="link"
                          size="xs"
                          className="h-auto gap-1 px-0 font-medium"
                          onClick={() => {
                            onClose();
                            gotoSettings("denoise");
                          }}
                        >
                          <Download size={12} /> {t("denoiseGoDownload")}
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        {/* 没有档位的引擎不摆这个旋钮 —— 拨了也没用。 */}
        {strengths.length > 0 && (
          <div className="grid gap-2.5">
            <span className={SECTION_LABEL}>{t("denoiseStrength")}</span>
            {/* 三档等分整行 —— 挤在左边、右边空一大截时,看着像没排完。 */}
            <div className={cn(SEGMENTED_LIST, "grid w-full auto-cols-fr grid-flow-col")} role="radiogroup" aria-label={t("denoiseStrength")}>
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
            <p className="m-0 text-ui-xs leading-[1.5] text-muted-foreground">{t("denoiseStrengthHint")}</p>
          </div>
        )}
        {/* 结果会落在哪儿:不是设置项,是一句交代,做成一条安静的提示,别和上面的说明文字混成一片。 */}
        <p className="m-0 flex items-start gap-2 rounded-md bg-panel-subtle px-3 py-2.5 text-ui-xs leading-[1.5] text-muted-foreground">
          <Info size={14} className="mt-px shrink-0" aria-hidden />
          {t("denoiseOutputNote")}
        </p>
      </div>
    </ModalShell>
  );
}
